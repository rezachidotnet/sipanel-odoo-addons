# -*- coding: utf-8 -*-
"""Execution adapters (GAP-D05, D07, D08, D09; C8-D03). Native approval boundaries stay native: everything is created in draft."""
from odoo import api, fields, models
from odoo.exceptions import UserError


class SipanelExecutionAdapter(models.AbstractModel):
    _name = 'sipanel.execution.adapter'
    _description = 'SIPANEL execution adapter dispatcher'

    # ------------------------------------------------------------------ dispatch
    @api.model
    def create_or_link(self, demand):
        handler = getattr(self, f"_adapt_{demand.execution_mode}", None)
        if handler is None:
            raise UserError(self.env._("No adapter for execution mode %s.", demand.execution_mode))
        if demand.owner == 'native_line_owner' and demand.execution_mode != 'native_anchor_covered':
            # NATIVE_LINE_OWNER demands are LINKED only, never CREATED (C8-D01)
            return self._adapt_native_anchor_covered(demand)
        return handler(demand)

    @api.model
    def cancel_delta(self, demand):
        """Reduce unreserved planned demand; done documents are never deleted (PT-19)."""
        for t in demand.target_ids:
            rec = t.target_record().exists()
            if not rec:
                continue
            if t.target_model == 'purchase.order.line' and rec.order_id.state in ('draft', 'sent'):
                rec.write({'product_qty': 0.0})
            elif t.target_model == 'mrp.production' and rec.state in ('draft', 'confirmed') and not rec.qty_produced:
                rec.action_cancel()
            elif t.target_model == 'stock.move' and rec.state not in ('done', 'cancel'):
                rec._action_cancel()
            else:
                demand.write({'reversal_required': True})
        demand.write({'state': 'cancelled'})
        return True

    @api.model
    def reduce_planned(self, demand, qty):
        """Reduce unreserved planned quantity on the demand's draft targets by `qty`; cancel when nothing remains; never delete."""
        remaining = qty
        for t in demand.target_ids:
            rec = t.target_record().exists()
            if not rec or remaining <= 0:
                continue
            if t.target_model == 'stock.move' and rec.state not in ('done', 'cancel'):
                cut = min(rec.product_uom_qty, remaining)
                rec.write({'product_uom_qty': rec.product_uom_qty - cut})
                if not rec.product_uom_qty:
                    rec._action_cancel()
                remaining -= cut
            elif t.target_model == 'purchase.order.line' and rec.order_id.state in ('draft', 'sent'):
                cut = min(rec.product_qty, remaining)
                rec.write({'product_qty': rec.product_qty - cut})
                remaining -= cut
            elif t.target_model == 'mrp.production' and rec.state in ('draft', 'confirmed') and not rec.qty_produced:
                cut = min(rec.product_qty, remaining)
                if cut >= rec.product_qty:
                    rec.action_cancel()
                else:
                    rec.write({'product_qty': rec.product_qty - cut})
                remaining -= cut
        if remaining > 1e-6:
            demand.write({'reversal_required': True})
        if demand.normalized_qty - (qty - remaining) <= 1e-6:
            demand.write({'state': 'cancelled'})
        return True

    # ------------------------------------------------------------------ helpers
    def _link(self, demand, model, res_id, link_kind='created', qty=None, reference=None, label=None):
        return self.env['sipanel.execution.target'].create({
            'demand_id': demand.id, 'target_model': model, 'target_res_id': res_id, 'link_kind': link_kind,
            'allocated_qty': demand.normalized_qty if qty is None else qty, 'uom_id': demand.uom_id.id,
            'stock_reference_id': reference.id if reference else False, 'origin_label': label or demand.order_id.name,
        })

    def _analytic_distribution(self, demand):
        """Project / System / Activity as analytic distribution (SV-15). Project via project.account_id."""
        dist = {}
        accounts = self.env['account.analytic.account']
        if demand.project_id and demand.project_id.account_id:
            accounts |= demand.project_id.account_id
        if demand.system_id:
            accounts |= demand.system_id
        if demand.activity_id:
            accounts |= demand.activity_id
        if accounts:
            dist[','.join(str(a.id) for a in accounts)] = 100.0
        return dist

    def _reference(self, demand):
        name = f"SIPANEL/{demand.order_id.name}/{demand.quote_scope_id.scope_uid[:8]}"
        ref = self.env['stock.reference'].search([('name', '=', name)], limit=1) or self.env['stock.reference'].create({'name': name})
        if 'stock_reference_ids' in demand.order_id._fields and ref not in demand.order_id.stock_reference_ids:
            demand.order_id.write({'stock_reference_ids': [(4, ref.id)]})
        return ref

    # ------------------------------------------------------------------ adapters
    @api.model
    def _adapt_stock_issue(self, demand):
        Config = self.env['sipanel.config']
        ptype = Config.stock_issue_picking_type()
        if not ptype:
            raise UserError(self.env._("Stock issue operation type is not configured (sipanel_scope.stock_issue_picking_type_id)."))
        ref = self._reference(demand)
        picking = self.env['stock.picking'].create({
            'picking_type_id': ptype.id, 'location_id': ptype.default_location_src_id.id, 'location_dest_id': ptype.default_location_dest_id.id,
            'origin': demand.order_id.name, 'company_id': demand.company_id.id, 'partner_id': demand.order_id.partner_id.id,
        })
        move = self.env['stock.move'].create({
            'product_id': demand.product_id.id, 'product_uom_qty': demand.normalized_qty,
            'product_uom': demand.uom_id.id, 'picking_id': picking.id, 'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id, 'company_id': demand.company_id.id, 'origin': demand.order_id.name,
        })
        ref.write({'move_ids': [(4, move.id)]})
        self._link(demand, 'stock.picking', picking.id, reference=ref)
        self._link(demand, 'stock.move', move.id, reference=ref)
        demand.write({'state': 'created'})
        return True

    @api.model
    def _adapt_buy_direct(self, demand):
        product = demand.product_id
        seller = product._select_seller(quantity=demand.normalized_qty, uom_id=demand.uom_id) if hasattr(product, '_select_seller') else False
        if not seller:
            raise UserError(self.env._("No vendor configured for %s; BUY_DIRECT needs a vendor (adapter preflight).", product.display_name))
        po = self.env['purchase.order'].search([('partner_id', '=', seller.partner_id.id), ('company_id', '=', demand.company_id.id), ('state', '=', 'draft'),
                                                ('origin', '=', demand.order_id.name), ('currency_id', '=', demand.company_id.currency_id.id)], limit=1)
        if not po:
            po = self.env['purchase.order'].create({'partner_id': seller.partner_id.id, 'company_id': demand.company_id.id, 'origin': demand.order_id.name,
                                                    'currency_id': demand.company_id.currency_id.id})
        pol = self.env['purchase.order.line'].create({
            'order_id': po.id, 'product_id': product.id, 'name': product.display_name, 'product_qty': demand.normalized_qty,
            'product_uom_id': demand.uom_id.id, 'price_unit': seller.price, 'date_planned': fields.Datetime.now(),
            'analytic_distribution': self._analytic_distribution(demand),
        })
        self._link(demand, 'purchase.order.line', pol.id)
        demand.write({'state': 'created'})
        return True

    @api.model
    def _adapt_manufacture(self, demand):
        product = demand.product_id
        bom = self.env['mrp.bom']._bom_find(product, company_id=demand.company_id.id, bom_type='normal').get(product)
        if not bom:
            raise UserError(self.env._("No manufacturing BoM for %s.", product.display_name))
        vals = {'product_id': product.id, 'product_qty': demand.normalized_qty, 'product_uom_id': demand.uom_id.id, 'bom_id': bom.id,
                'company_id': demand.company_id.id, 'origin': demand.order_id.name}
        if 'project_id' in self.env['mrp.production']._fields and demand.project_id:
            vals['project_id'] = demand.project_id.id
        mo = self.env['mrp.production'].create(vals)
        ref = self._reference(demand)
        if 'reference_ids' in mo._fields:
            mo.write({'reference_ids': [(4, ref.id)]})
        self._link(demand, 'mrp.production', mo.id, reference=ref)
        demand.write({'state': 'created'})
        return True

    @api.model
    def _adapt_labour(self, demand):
        """Link the execution project/task only; never create timesheets (BQ-07=A, PT-20)."""
        project = demand.project_id or self.env['sipanel.config'].default_project()
        if not project:
            raise UserError(self.env._("No project to link labour demand %s.", demand.display_name))
        self._link(demand, 'project.project', project.id, link_kind='linked_existing')
        anchor = demand.quote_scope_id.anchor_line_id
        if 'task_id' in anchor._fields and anchor.task_id:
            self._link(demand, 'project.task', anchor.task_id.id, link_kind='linked_existing')
        demand.write({'state': 'linked'})
        return True

    @api.model
    def _adapt_equipment_service(self, demand):
        return self._adapt_buy_direct(demand)

    @api.model
    def _adapt_native_anchor_covered(self, demand):
        anchor = demand.quote_scope_id.anchor_line_id
        linked = False
        if 'move_ids' in anchor._fields:
            for mv in anchor.move_ids.filtered(lambda m: m.state != 'cancel'):
                self._link(demand, 'stock.move', mv.id, link_kind='native_anchor_covered', qty=mv.product_uom_qty)
                linked = True
        if 'purchase_line_ids' in anchor._fields:
            for pol in anchor.purchase_line_ids:
                self._link(demand, 'purchase.order.line', pol.id, link_kind='native_anchor_covered', qty=pol.product_qty)
                linked = True
        if 'task_id' in anchor._fields and anchor.task_id:
            self._link(demand, 'project.task', anchor.task_id.id, link_kind='native_anchor_covered')
            linked = True
        if 'project_id' in anchor._fields and anchor.project_id:
            self._link(demand, 'project.project', anchor.project_id.id, link_kind='native_anchor_covered')
            linked = True
        demand.write({'state': 'linked' if linked else 'planned'})
        return True

    @api.model
    def _adapt_no_action(self, demand):
        demand.write({'state': 'fulfilled'})
        return True
