# -*- coding: utf-8 -*-
"""Projection job: reads native carriers only, never writes a journal/analytic/valuation record (GAP-E02..E07).

Route -> terminal event (IF-01: `stock.move.value` is a field; `product.value` is a model; SV-15/SV-17):
  shared_stock      : done outgoing stock.move linked by target (value field)           | excluded: PO, receipt, internal transfer, bill
  direct_purchase   : posted vendor bill line on the linked purchase.order.line          | excluded: PO commitment, receipt value, payment
  mfg_material      : done outgoing stock.move of the MO's finished product (issue)       | excluded: raw moves, workorder AAL, timesheets
  site_labour       : approved timesheet analytic lines on the linked project/task        | excluded: payroll duplicate
  equipment_service : posted vendor bill line on the linked PO line, or approved expense  | excluded: PO commitment
  return_credit     : refund bill line / returned move, linked as reversal_of             | never double reversal
  freight_landed    : NONE (deferred; stock_landed_costs not installed)
"""
from odoo import api, fields, models

ROUTE_BY_MODE = {'stock_issue': 'shared_stock', 'buy_direct': 'direct_purchase', 'manufacture': 'mfg_material',
                 'labour': 'site_labour', 'equipment_service': 'equipment_service', 'native_anchor_covered': 'shared_stock'}


class SipanelActualProjection(models.AbstractModel):
    _name = 'sipanel.actual.projection'
    _description = 'SIPANEL actual cost projection job'

    @api.model
    def refresh_order(self, order):
        """Rebuild events/allocations for one order's demands. Idempotent (natural keys)."""
        Event = self.env['sipanel.actual.cost.event'].with_context(sipanel_projection=True).sudo()
        Alloc = self.env['sipanel.actual.allocation'].with_context(sipanel_projection=True).sudo()
        Policy = self.env['sipanel.cost.recognition.policy'].sudo()
        company = order.company_id
        demands = self.env['sipanel.execution.demand'].sudo().search([('order_id', '=', order.id), ('state', 'not in', ('failed',))])
        touched = Event
        for d in demands:
            route = ROUTE_BY_MODE.get(d.execution_mode)
            if not route:
                continue
            policy = Policy.approved_for(route, company)
            for cand in self._candidates(d, route):
                key = Event.make_key(cand['model'], cand['res_id'], cand['component_type'], company)
                vals = dict(cand, source_key=key, company_id=company.id, policy_id=policy.id or False,
                            inclusion=(cand.get('inclusion') or 'included') if policy else 'policy_missing',
                            inclusion_policy_version=policy.version if policy else 0,
                            project_id=d.project_id.id, system_id=d.system_id.id, activity_id=d.activity_id.id,
                            source_model=cand['model'], source_res_id=cand['res_id'])
                for k in ('model', 'res_id', 'reversal_key'):
                    vals.pop(k, None)
                ev = Event.search([('source_key', '=', key)], limit=1)
                if ev:
                    ev.write(vals)
                else:
                    ev = Event.create(vals)
                if cand.get('reversal_key'):
                    orig = Event.search([('source_key', '=', cand['reversal_key'])], limit=1)
                    if orig and ev.reversal_of_id != orig:
                        ev.write({'reversal_of_id': orig.id})
                touched |= ev
                if ev.inclusion == 'included':
                    alloc = ev.allocation_ids.filtered(lambda a: a.demand_id == d and a.allocation_basis == 'target_link')
                    if alloc:
                        alloc.write({'amount': ev.amount})
                    else:
                        ev.allocation_ids.filtered(lambda a: a.allocation_basis == 'unallocated').unlink()
                        Alloc.create({'event_id': ev.id, 'demand_id': d.id, 'component_id': d.component_id.id, 'quote_scope_id': d.quote_scope_id.id,
                                      'allocation_basis': 'target_link', 'amount': ev.amount})
        # dimension-only events (project match, no target) => UNALLOCATED bucket (PT-29)
        projects = order.sipanel_quote_scope_ids.mapped('project_id') | self.env['sipanel.config'].default_project()
        for cand in self._project_candidates(projects, company):
            key = Event.make_key(cand['model'], cand['res_id'], cand['component_type'], company)
            if Event.search([('source_key', '=', key)], limit=1):
                continue
            policy = Policy.approved_for(cand['route'], company)
            vals = dict(cand, source_key=key, company_id=company.id, policy_id=policy.id or False,
                        inclusion='included' if policy else 'policy_missing', inclusion_policy_version=policy.version if policy else 0,
                        source_model=cand['model'], source_res_id=cand['res_id'])
            for k in ('model', 'res_id', 'route'):
                vals.pop(k, None)
            ev = Event.create(vals)
            if ev.inclusion == 'included':
                Alloc.create({'event_id': ev.id, 'allocation_basis': 'unallocated', 'amount': 0.0})
            touched |= ev
        # revenue: posted customer invoice lines linked to anchor lines, minus credits
        for scope in order.sipanel_quote_scope_ids.filtered('active'):
            for aml in self.env['account.move.line'].sudo().search([('sale_line_ids', 'in', scope.anchor_line_id.id), ('parent_state', '=', 'posted'),
                                                                    ('move_id.move_type', 'in', ('out_invoice', 'out_refund')), ('display_type', '=', 'product')]):
                sign = -1 if aml.move_id.move_type == 'out_refund' else 1
                key = Event.make_key('account.move.line', aml.id, 'revenue', company)
                vals = {'source_key': key, 'company_id': company.id, 'source_model': 'account.move.line', 'source_res_id': aml.id,
                        'component_type': 'revenue', 'layer': 'recognized', 'inclusion': 'included', 'amount': sign * aml.price_subtotal,
                        'event_date': aml.move_id.invoice_date or aml.date, 'project_id': scope.project_id.id, 'system_id': scope.system_id.id}
                ev = Event.search([('source_key', '=', key)], limit=1)
                ev.write(vals) if ev else Event.create(vals)
                ev = ev or Event.search([('source_key', '=', key)], limit=1)
                if not ev.allocation_ids:
                    Alloc.create({'event_id': ev.id, 'quote_scope_id': scope.id, 'allocation_basis': 'target_link', 'amount': ev.amount})
                touched |= ev
        self.env['sipanel.scope.audit.event'].log(order, 'refresh_actuals', after={'events': len(touched)})
        return touched

    # ------------------------------------------------------------------ candidates per demand
    def _candidates(self, d, route):
        out = []
        for t in d.target_ids:
            rec = t.target_record().exists()
            if not rec:
                continue
            if t.target_model == 'stock.move':
                out += self._from_stock_move(rec, route)
            elif t.target_model == 'stock.picking':
                for mv in rec.move_ids:
                    out += self._from_stock_move(mv, route)
            elif t.target_model == 'purchase.order.line':
                out += self._from_purchase_line(rec, d)
            elif t.target_model == 'mrp.production':
                out += self._from_production(rec)
            elif t.target_model in ('project.project', 'project.task'):
                out += self._from_timesheets(rec, t.target_model)
            elif t.target_model == 'hr.expense':
                out += self._from_expense(rec)
        return out

    def _from_stock_move(self, mv, route):
        if mv.state != 'done':
            return [{'model': 'stock.move', 'res_id': mv.id, 'component_type': 'material', 'layer': 'operational', 'inclusion': 'excluded_duplicate',
                     'amount': 0.0, 'event_date': fields.Date.to_date(mv.date) if mv.date else fields.Date.today(),
                     'qty': mv.quantity or mv.product_uom_qty, 'uom_id': mv.product_uom.id, 'qty_kind': 'consumed'}]
        is_out = mv.location_dest_id.usage in ('customer', 'production', 'inventory') or getattr(mv, 'is_out', False)
        if not is_out:
            # receipts / internal transfers: shown as operational, excluded from recognised cost
            return [{'model': 'stock.move', 'res_id': mv.id, 'component_type': 'material', 'layer': 'operational', 'inclusion': 'excluded_duplicate',
                     'amount': 0.0, 'event_date': fields.Date.to_date(mv.date), 'qty': mv.quantity, 'uom_id': mv.product_uom.id, 'qty_kind': 'received'}]
        value = abs(mv.value or 0.0)  # IF-01: field `value` on stock.move
        returned = mv.origin_returned_move_id if 'origin_returned_move_id' in mv._fields else False
        cand = {'model': 'stock.move', 'res_id': mv.id, 'component_type': 'material', 'layer': 'recognized', 'amount': value,
                'event_date': fields.Date.to_date(mv.date), 'qty': mv.quantity, 'uom_id': mv.product_uom.id, 'qty_kind': 'consumed',
                'cost_source_zero': value == 0.0}
        if returned:
            cand.update({'amount': -value, 'qty_kind': 'returned', 'reversal_key': self.env['sipanel.actual.cost.event'].make_key('stock.move', returned.id, 'material', mv.company_id)})
        return [cand]

    def _from_purchase_line(self, pol, d):
        out = [{'model': 'purchase.order.line', 'res_id': pol.id, 'component_type': 'service' if pol.product_id.type == 'service' else 'material',
                'layer': 'commitment', 'inclusion': 'excluded_duplicate', 'amount': 0.0, 'event_date': fields.Date.to_date(pol.date_planned) or fields.Date.today(),
                'qty': pol.product_qty, 'uom_id': pol.product_uom_id.id, 'qty_kind': 'none'}]
        ctype = 'equipment' if d.execution_mode == 'equipment_service' else ('service' if pol.product_id.type == 'service' else 'material')
        for aml in pol.invoice_lines.filtered(lambda l: l.parent_state == 'posted'):
            is_refund = aml.move_id.move_type == 'in_refund'
            amount = abs(aml.balance) * (-1 if is_refund else 1)
            cand = {'model': 'account.move.line', 'res_id': aml.id, 'component_type': ctype, 'layer': 'recognized', 'amount': amount,
                    'event_date': aml.move_id.invoice_date or aml.date, 'qty': aml.quantity, 'uom_id': aml.product_uom_id.id, 'qty_kind': 'received' if not is_refund else 'returned'}
            if is_refund:
                orig = pol.invoice_lines.filtered(lambda l: l.parent_state == 'posted' and l.move_id.move_type == 'in_invoice')[:1]
                if orig:
                    cand['reversal_key'] = self.env['sipanel.actual.cost.event'].make_key('account.move.line', orig.id, ctype, aml.company_id)
            out.append(cand)
        # receipt moves for the same PO line are excluded duplicates
        for mv in pol.move_ids.filtered(lambda m: m.state == 'done'):
            out.append({'model': 'stock.move', 'res_id': mv.id, 'component_type': 'material', 'layer': 'operational', 'inclusion': 'excluded_duplicate',
                        'amount': 0.0, 'event_date': fields.Date.to_date(mv.date), 'qty': mv.quantity, 'uom_id': mv.product_uom.id, 'qty_kind': 'received'})
        return out

    def _from_production(self, mo):
        out = []
        # raw consumption and workorder analytic lines are shown as WIP and excluded (never added to the finished issue)
        for mv in mo.move_raw_ids.filtered(lambda m: m.state == 'done'):
            out.append({'model': 'stock.move', 'res_id': mv.id, 'component_type': 'material', 'layer': 'wip', 'inclusion': 'excluded_duplicate',
                        'amount': 0.0, 'event_date': fields.Date.to_date(mv.date), 'qty': mv.quantity, 'uom_id': mv.product_uom.id, 'qty_kind': 'consumed'})
        for wo in mo.workorder_ids:
            for aal in (wo.wc_analytic_account_line_ids if 'wc_analytic_account_line_ids' in wo._fields else self.env['account.analytic.line']):
                out.append({'model': 'account.analytic.line', 'res_id': aal.id, 'component_type': 'labour', 'layer': 'wip', 'inclusion': 'excluded_duplicate',
                            'amount': 0.0, 'event_date': aal.date, 'qty': aal.unit_amount, 'qty_kind': 'hours'})
        # terminal: finished-product issue (outgoing done move of the produced product, same reference or origin)
        Move = self.env['stock.move'].sudo()
        domain = [('product_id', '=', mo.product_id.id), ('state', '=', 'done'), ('company_id', '=', mo.company_id.id),
                  ('location_dest_id.usage', 'in', ('customer', 'production', 'inventory')), ('production_id', '=', False), ('raw_material_production_id', '=', False)]
        refs = mo.reference_ids if 'reference_ids' in mo._fields else self.env['stock.reference']
        issues = Move.search(domain + ['|', ('origin', '=', mo.origin), ('reference_ids', 'in', refs.ids)]) if refs else Move.search(domain + [('origin', '=', mo.origin)])
        for mv in issues:
            value = abs(mv.value or 0.0)
            out.append({'model': 'stock.move', 'res_id': mv.id, 'component_type': 'material', 'layer': 'recognized', 'amount': value,
                        'event_date': fields.Date.to_date(mv.date), 'qty': mv.quantity, 'uom_id': mv.product_uom.id, 'qty_kind': 'consumed', 'cost_source_zero': value == 0.0})
        if not issues:
            for mv in mo.move_finished_ids.filtered(lambda m: m.state == 'done'):
                out.append({'model': 'stock.move', 'res_id': mv.id, 'component_type': 'material', 'layer': 'wip', 'inclusion': 'excluded_duplicate',
                            'amount': 0.0, 'event_date': fields.Date.to_date(mv.date), 'qty': mv.quantity, 'uom_id': mv.product_uom.id, 'qty_kind': 'produced'})
        return out

    def _from_timesheets(self, rec, model):
        domain = [('project_id', '=', rec.id)] if model == 'project.project' else [('task_id', '=', rec.id)]
        out = []
        for ts in self.env['account.analytic.line'].sudo().search(domain + [('employee_id', '!=', False)]):
            if 'validated' in ts._fields and not ts.validated:
                out.append({'model': 'account.analytic.line', 'res_id': ts.id, 'component_type': 'labour', 'layer': 'operational', 'inclusion': 'excluded_duplicate',
                            'amount': 0.0, 'event_date': ts.date, 'qty': ts.unit_amount, 'qty_kind': 'hours'})
                continue
            amount = abs(ts.amount or 0.0)  # SV-17: amount = -hours x hourly_cost
            out.append({'model': 'account.analytic.line', 'res_id': ts.id, 'component_type': 'labour', 'layer': 'recognized', 'amount': amount,
                        'event_date': ts.date, 'qty': ts.unit_amount, 'uom_id': ts.product_uom_id.id, 'qty_kind': 'hours', 'cost_source_zero': amount == 0.0})
        return out

    def _from_expense(self, exp):
        if exp.state not in ('approved', 'posted', 'in_payment', 'paid'):
            return []
        return [{'model': 'hr.expense', 'res_id': exp.id, 'component_type': 'equipment', 'layer': 'recognized', 'amount': exp.total_amount,
                 'event_date': exp.date, 'qty': exp.quantity, 'qty_kind': 'none'}]

    def _project_candidates(self, projects, company):
        """Recognised events attributable to the project dimension but not to any target link => UNALLOCATED."""
        out = []
        for project in projects:
            for ts in self.env['account.analytic.line'].sudo().search([('project_id', '=', project.id), ('employee_id', '!=', False), ('company_id', '=', company.id)]):
                out.append({'model': 'account.analytic.line', 'res_id': ts.id, 'component_type': 'labour', 'layer': 'recognized', 'route': 'site_labour',
                            'amount': abs(ts.amount or 0.0), 'event_date': ts.date, 'qty': ts.unit_amount, 'qty_kind': 'hours', 'project_id': project.id})
            if 'project_id' in self.env['hr.expense']._fields:
                for exp in self.env['hr.expense'].sudo().search([('project_id', '=', project.id), ('state', 'in', ('approved', 'posted', 'in_payment', 'paid')), ('company_id', '=', company.id)]):
                    out.append({'model': 'hr.expense', 'res_id': exp.id, 'component_type': 'equipment', 'layer': 'recognized', 'route': 'equipment_service',
                                'amount': exp.total_amount, 'event_date': exp.date, 'qty': exp.quantity, 'qty_kind': 'none', 'project_id': project.id})
            if project.account_id:
                for aml in self.env['account.move.line'].sudo().search([('parent_state', '=', 'posted'), ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
                                                                        ('display_type', '=', 'product'), ('company_id', '=', company.id),
                                                                        ('analytic_distribution', '!=', False), ('purchase_line_id', '=', False)]):
                    if str(project.account_id.id) in ','.join((aml.analytic_distribution or {}).keys()):
                        sign = -1 if aml.move_id.move_type == 'in_refund' else 1
                        out.append({'model': 'account.move.line', 'res_id': aml.id, 'component_type': 'service', 'layer': 'recognized', 'route': 'direct_purchase',
                                    'amount': sign * abs(aml.balance), 'event_date': aml.move_id.invoice_date or aml.date, 'qty': aml.quantity, 'qty_kind': 'none', 'project_id': project.id})
        return out

    @api.model
    def cron_refresh_all(self):
        orders = self.env['sale.order'].search([('sipanel_has_scopes', '=', True), ('state', '=', 'sale')])
        for o in orders:
            self.refresh_order(o)
        return True
