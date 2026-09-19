# -*- coding: utf-8 -*-
"""Atomic split/move with lineage and cost conservation (GAP-B08, C3-D04, PT-06, PT-07)."""
from odoo import api, fields, models
from odoo.exceptions import LockError, UserError
from odoo.tools import float_compare, float_is_zero
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx


class SipanelWizardSplitMove(models.TransientModel):
    _name = 'sipanel.wizard.split.move'
    _description = 'Split / move components to another Scope of the same order'

    source_scope_id = fields.Many2one('sipanel.quote.scope', required=True)
    order_id = fields.Many2one(related='source_scope_id.order_id')
    destination_mode = fields.Selection([('new', 'New Scope on this order'), ('existing', 'Existing working Scope')], required=True, default='new')
    destination_scope_id = fields.Many2one('sipanel.quote.scope', domain="[('order_id', '=', order_id), ('id', '!=', source_scope_id)]")
    new_label = fields.Char(help="Customer label of the new Scope (destination)")
    new_optional = fields.Boolean(string='Destination is optional (OFFERED)')
    dependent_policy = fields.Selection([('block', 'Block if a percent line depends on a moved line'),
                                         ('move_dependents', 'Move dependent percent lines too'),
                                         ('rebase', 'Rebase dependents on the remaining lines')], required=True, default='block')
    line_ids = fields.One2many('sipanel.wizard.split.move.line', 'wizard_id')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        sid = res.get('source_scope_id') or self.env.context.get('default_source_scope_id')
        if sid:
            scope = self.env['sipanel.quote.scope'].browse(sid)
            res['line_ids'] = [(0, 0, {'component_id': c.id, 'available_qty': c.final_qty, 'move_qty': 0.0})
                               for c in scope.current_revision_id.component_ids.filtered(lambda c: c.active_state == 'active')]
        return res

    def action_split(self):
        self.ensure_one()
        _ = self.env._
        src_scope = self.source_scope_id
        src_rev = src_scope.current_revision_id
        src_rev._check_working('split components of')
        selected = self.line_ids.filtered(lambda l: l.move_qty > 0 or l.move_all)
        if not selected:
            raise UserError(_("Select at least one component to move."))
        try:
            src_scope.lock_for_update()
            if self.destination_scope_id:
                self.destination_scope_id.lock_for_update()
        except LockError:
            raise UserError(_("Another split is in progress on this Scope; retry."))
        moved_full = selected.filtered(lambda l: l.move_all or float_compare(l.move_qty, l.available_qty, precision_digits=6) >= 0).mapped('component_id')
        moved_partial = selected - selected.filtered(lambda l: l.component_id in moved_full)
        # dependency gate (PT-07)
        rev_comps = src_rev.component_ids.filtered(lambda c: c.active_state == 'active')
        dependents = rev_comps.filtered(lambda c: c.base_component_ids & moved_full and c not in moved_full)
        if dependents and self.dependent_policy == 'block':
            raise UserError(_("Cannot move %(m)s alone: %(d)s depend(s) on it. Choose 'move dependents too' or 'rebase'.",
                              m=', '.join(moved_full.mapped('display_name')), d=', '.join(dependents.mapped('display_name'))))
        if dependents and self.dependent_policy == 'move_dependents':
            moved_full |= dependents
        for c in moved_full:
            if c.basis in ('percent_of_quantity', 'percent_of_cost') and (c.base_component_ids - moved_full):
                if self.dependent_policy != 'move_dependents':
                    raise UserError(_("%s references bases that stay behind; move its bases too.", c.display_name))
                moved_full |= c.base_component_ids
        cost_before = sum(src_rev.sudo().component_ids.filtered('eligible_for_rollup').mapped('cost_amount'))
        # destination
        if self.destination_mode == 'existing':
            dest_scope = self.destination_scope_id
            if not dest_scope or dest_scope.current_revision_id.state != 'working':
                raise UserError(_("Destination must be a working Scope of the same order."))
        else:
            dest_scope = self._create_destination(src_scope)
        dest_rev = dest_scope.current_revision_id
        Comp = self.env['sipanel.quote.scope.component'].sudo()
        id_map = {}
        for c in moved_full.sorted(lambda c: (c.sequence, c.id)):
            vals = c.copy_data({'revision_id': dest_rev.id, 'base_component_ids': False, 'moved_from_id': c.id,
                                'origin': 'transferred', 'copy_from_id': False})[0]
            vals.pop('occurrence_uid', None)
            for k in ('unit_cost', 'cost_uom_id', 'cost_uom_factor', 'cost_source_date', 'cost_source_company_id', 'product_value_id',
                      'manual_cost_user_id', 'manual_cost_date', 'manual_cost_reason', 'override_reason', 'known_zero_reason'):
                v = c.sudo()[k]
                vals[k] = v.id if hasattr(v, 'id') else v
            id_map[c.id] = Comp.create(vals).id
        for c in moved_full:
            if c.base_component_ids:
                Comp.browse(id_map[c.id]).write({'base_component_ids': [(6, 0, [id_map[b.id] for b in c.base_component_ids if b.id in id_map])]})
        # rebase dependents left behind
        if dependents and self.dependent_policy == 'rebase':
            for d in dependents - moved_full:
                remaining = d.base_component_ids - moved_full
                if not remaining:
                    raise UserError(_("%s would have no base left; move it too.", d.display_name))
                d.write({'base_component_ids': [(6, 0, remaining.ids)]})
        for c in moved_full:
            c.write({'moved_to_id': id_map[c.id]})
        moved_full.write({'active_state': 'tombstone', 'origin': 'transferred'})
        # partial moves: source remainder + destination part
        for l in moved_partial:
            c = l.component_id
            if c.basis in ('percent_of_quantity', 'percent_of_cost'):
                raise UserError(_("Percent lines cannot be partially moved (%s).", c.display_name))
            remainder = c.final_qty - l.move_qty
            vals = c.copy_data({'revision_id': dest_rev.id, 'base_component_ids': False, 'moved_from_id': c.id, 'origin': 'split_destination',
                                'copy_from_id': False, 'basis': 'fixed', 'fixed_qty': l.move_qty,
                                'qty_override': False, 'override_driver_fp': False})[0]
            vals.pop('occurrence_uid', None)
            for k in ('unit_cost', 'cost_uom_id', 'cost_uom_factor', 'cost_source_date', 'cost_source_company_id', 'product_value_id',
                      'manual_cost_user_id', 'manual_cost_date', 'manual_cost_reason', 'known_zero_reason'):
                v = c.sudo()[k]
                vals[k] = v.id if hasattr(v, 'id') else v
            dest = Comp.create(vals)
            c.write({'basis': 'fixed', 'fixed_qty': remainder, 'qty_override': False, 'override_driver_fp': False,
                     'origin': 'split_remainder', 'moved_to_id': dest.id})
            if float_compare(c.final_qty + dest.final_qty, l.available_qty, precision_digits=6) != 0:
                raise UserError(_("Split arithmetic error on %s.", c.display_name))
        src_rev.invalidate_recordset()
        dest_rev.invalidate_recordset()
        cost_after = sum(src_rev.sudo().component_ids.filtered('eligible_for_rollup').mapped('cost_amount')) + \
            sum(dest_rev.sudo().component_ids.filtered('eligible_for_rollup').mapped('cost_amount'))
        if dest_scope.is_optional:
            cost_after = sum(src_rev.sudo().component_ids.filtered('eligible_for_rollup').mapped('cost_amount')) + \
                sum(dest_rev.sudo().component_ids.filtered(lambda c: c.active_state == 'active' and c.responsibility == 'sipanel').mapped('cost_amount'))
        if float_compare(cost_before, cost_after, precision_digits=4) != 0:
            raise UserError(_("Cost conservation violated: before %(b).4f, after %(a).4f. Nothing was saved.", b=cost_before, a=cost_after))
        for rev in (src_rev, dest_rev):
            rev.with_context(**guard_ctx('sipanel_note_sync')).write({'note_reviewed': False})
        self.env['sipanel.scope.audit.event'].log(
            src_scope, 'split_move', after={'moved_full': list(id_map.keys()), 'partial': moved_partial.mapped('component_id').ids,
                                            'destination_scope_id': dest_scope.id, 'cost_before': cost_before, 'cost_after': cost_after},
            revision_ref=src_rev.display_name)
        return {'type': 'ir.actions.act_window', 'res_model': 'sipanel.quote.scope', 'res_id': dest_scope.id, 'view_mode': 'form'}

    def _create_destination(self, src_scope):
        src_rev = src_scope.current_revision_id
        order = src_scope.order_id
        version = src_scope.source_version_id
        section = None
        if self.new_optional:
            section = order.order_line.filtered(lambda l: l.display_type == 'line_section' and l.is_optional)[:1]
            if not section:
                section = self.env['sale.order.line'].create({'order_id': order.id, 'display_type': 'line_section', 'name': self.env._('Options'),
                                                              'is_optional': True, 'sequence': max(order.order_line.mapped('sequence') or [0]) + 10})
        line = self.env['sale.order.line'].with_context(**guard_ctx('sipanel_anchor_create')).create({
            'order_id': order.id, 'product_id': src_scope.anchor_line_id.product_id.id,
            'product_uom_qty': 0.0 if self.new_optional else src_scope.anchor_line_id.product_uom_qty,
            'product_uom_id': src_scope.anchor_line_id.product_uom_id.id,
            'name': self.new_label or src_scope.anchor_line_id.name,
            'sequence': (section.sequence + 1) if section else src_scope.anchor_line_id.sequence + 1,
            'price_unit': 0.0,
        })
        dest = self.env['sipanel.quote.scope'].create({
            'order_id': order.id, 'source_scope_id': src_scope.source_scope_id.id, 'source_version_id': version.id,
            'is_adhoc': src_scope.is_adhoc, 'anchor_line_id': line.id, 'is_optional': self.new_optional,
            'optional_section_line_id': section.id if section else False,
            'acceptance_state': 'offered' if self.new_optional else 'base', 'system_id': src_scope.system_id.id,
        })
        rev = self.env['sipanel.quote.scope.revision'].create({
            'quote_scope_id': dest.id, 'revision': 1, 'language': src_rev.language, 'quote_uom_id': src_rev.quote_uom_id.id,
            'base_uom_id': src_rev.base_uom_id.id, 'uom_factor': src_rev.uom_factor,
            'label_fa': self.new_label or src_rev.label_fa, 'label_en': self.new_label or src_rev.label_en,
            'fx_source_currency_id': order.currency_id.id, 'fx_rate': 1.0, 'fx_date': fields.Date.today(), 'fx_source': 'company_currency',
        })
        dest.write({'current_revision_id': rev.id})
        if self.new_optional:
            rev.with_context(**guard_ctx('sipanel_seal_transaction')).write({'offered_scope_qty': src_rev.scope_qty})
        return dest


class SipanelWizardSplitMoveLine(models.TransientModel):
    _name = 'sipanel.wizard.split.move.line'
    _description = 'Split / move line'

    wizard_id = fields.Many2one('sipanel.wizard.split.move', required=True, ondelete='cascade')
    component_id = fields.Many2one('sipanel.quote.scope.component', required=True)
    available_qty = fields.Float(digits=(16, 6))
    move_qty = fields.Float(digits=(16, 6))
    move_all = fields.Boolean()
