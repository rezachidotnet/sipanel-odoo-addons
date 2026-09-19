# -*- coding: utf-8 -*-
"""sale.order.line guards: anchor ownership, sealed structure protection, governed qty transition, note sync
(GAP-B01, C02, C03, C04; SV-03, SV-05, SV-06, IF-03)."""
from odoo import api, fields, models
from odoo.exceptions import UserError

STRUCTURE_FIELDS = {'sequence', 'display_type', 'is_optional'}
ANCHOR_FROZEN_FIELDS = {'product_id', 'product_uom_id', 'display_type', 'linked_line_id', 'combo_item_id', 'order_id', 'product_template_id'}


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    sipanel_quote_scope_ids = fields.One2many('sipanel.quote.scope', 'anchor_line_id', copy=False)
    sipanel_quote_scope_id = fields.Many2one('sipanel.quote.scope', compute='_compute_sipanel_scope', store=True)
    sipanel_is_anchor = fields.Boolean(compute='_compute_sipanel_scope', store=True)
    sipanel_guard_state = fields.Selection([('free', 'Free'), ('sealed', 'Sealed'), ('accepted', 'Accepted')],
                                           compute='_compute_sipanel_guard', store=True)
    sipanel_is_scoped_section = fields.Boolean(compute='_compute_sipanel_scoped_section', store=True)
    sipanel_copied_from_line_id = fields.Integer(copy=False, readonly=True, help="Source line id at duplication (scope copy map).")

    @api.depends('sipanel_quote_scope_ids', 'sipanel_quote_scope_ids.active')
    def _compute_sipanel_scope(self):
        for line in self:
            scope = line.sipanel_quote_scope_ids.filtered('active')[:1]
            line.sipanel_quote_scope_id = scope
            line.sipanel_is_anchor = bool(scope)

    @api.depends('sipanel_quote_scope_id.current_revision_id.state', 'sipanel_quote_scope_id.accepted_revision_id')
    def _compute_sipanel_guard(self):
        for line in self:
            scope = line.sipanel_quote_scope_id
            if not scope:
                line.sipanel_guard_state = 'free'
            elif scope.accepted_revision_id:
                line.sipanel_guard_state = 'accepted'
            elif scope.revision_ids.filtered(lambda r: r.state != 'working'):
                line.sipanel_guard_state = 'sealed'
            else:
                line.sipanel_guard_state = 'free'

    @api.depends('order_id.sipanel_quote_scope_ids.optional_section_line_id')
    def _compute_sipanel_scoped_section(self):
        for line in self:
            line.sipanel_is_scoped_section = bool(line.display_type) and line in line.order_id.sipanel_quote_scope_ids.mapped('optional_section_line_id')

    # ---------------------------------------------------------- guards
    def _sipanel_sealed_scopes(self):
        return self.mapped('sipanel_quote_scope_id').filtered(lambda s: s.revision_ids.filtered(lambda r: r.state != 'working'))

    def write(self, vals):
        ctx = self.env.context
        if not ctx.get('sipanel_governed_transition') and not ctx.get('sipanel_seal_transaction'):
            for line in self:
                scope = line.sipanel_quote_scope_id
                if scope:
                    rev = scope.current_revision_id
                    if ANCHOR_FROZEN_FIELDS & set(vals) and scope.revision_ids.filtered(lambda r: r.state != 'working'):
                        raise UserError(self.env._("Line %s anchors a sealed Scope; its product/unit/structure cannot change.", line.display_name))
                    if 'product_uom_qty' in vals and rev.state != 'working':
                        if scope.is_optional and rev.state == 'sent_sealed':
                            raise UserError(self.env._("Quantity of an optional Scope changes only through the governed acceptance transition."))
                        raise UserError(self.env._("Scope %s is sealed; amend it to change the quantity.", scope.display_name))
                    if 'price_unit' in vals and rev.state != 'working' and not ctx.get('sipanel_apply_price'):
                        raise UserError(self.env._("Scope %s is sealed; price changes require an amendment.", scope.display_name))
                if line.sipanel_is_scoped_section and STRUCTURE_FIELDS & set(vals):
                    sealed = line.order_id.sipanel_quote_scope_ids.filtered(
                        lambda s: s.optional_section_line_id == line and s.revision_ids.filtered(lambda r: r.state != 'working'))
                    if sealed:
                        raise UserError(self.env._("Section %s structures a sealed Scope and cannot be moved or retyped.", line.display_name))
        res = super().write(vals)
        if 'name' in vals and not ctx.get('sipanel_note_sync'):
            for line in self.filtered('sipanel_is_anchor'):
                rev = line.sipanel_quote_scope_id.current_revision_id
                if rev.state == 'working':
                    rev.with_context(sipanel_note_sync=True).write({'final_note': vals['name'], 'note_manually_edited': True})
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_sealed_scope(self):
        for line in self:
            if line.sipanel_quote_scope_id:
                if line.sipanel_quote_scope_id.revision_ids.filtered(lambda r: r.state != 'working'):
                    raise UserError(self.env._("Line %s anchors a sealed Scope and cannot be deleted.", line.display_name))
                raise UserError(self.env._("Line %s anchors a Scope; remove the Scope first.", line.display_name))
            if line.sipanel_is_scoped_section:
                sealed = line.order_id.sipanel_quote_scope_ids.filtered(
                    lambda s: s.optional_section_line_id == line and s.revision_ids.filtered(lambda r: r.state != 'working'))
                if sealed:
                    raise UserError(self.env._("Section %s structures a sealed Scope and cannot be deleted (IF-03 guard).", line.display_name))

    def _can_be_edited_on_portal(self):
        self.ensure_one()
        res = super()._can_be_edited_on_portal()
        scope = self.sipanel_quote_scope_id
        if scope:
            return res and scope.is_optional and scope.current_revision_id.state == 'sent_sealed'
        return res

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        for line, vals in zip(self, vals_list):
            vals['sipanel_copied_from_line_id'] = line.id
        return vals_list

    def _sipanel_portal_binding(self):
        """Data injected in the portal template for anchor lines (revision id + seal hash)."""
        self.ensure_one()
        scope = self.sipanel_quote_scope_id
        rev = scope.current_revision_id if scope else False
        if rev and rev.state == 'sent_sealed':
            return {'revision_id': rev.id, 'seal_hash': rev.sealed_hash}
        return {}
