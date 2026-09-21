# -*- coding: utf-8 -*-
"""sale.order.line guards: anchor ownership, sealed structure protection, governed qty transition, note sync
(GAP-B01, C02, C03, C04; SV-03, SV-05, SV-06, IF-03)."""
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx

STRUCTURE_FIELDS = {'sequence', 'display_type', 'is_optional'}
ANCHOR_FROZEN_FIELDS = {'product_id', 'product_uom_id', 'display_type', 'linked_line_id', 'combo_item_id', 'order_id', 'product_template_id'}

# STEP 2B. Provenance of a generated separately-billable line. These must never be
# settable by a user, an import, an RPC context or sudo: they are the audit trail
# that ties invoice revenue back to a governed Scope component.
PROJECTION_FIELDS = {
    'sipanel_is_generated', 'sipanel_origin_key', 'sipanel_source_component_id',
    'sipanel_source_revision_id', 'sipanel_source_quote_scope_id', 'sipanel_source_scope_id',
    'sipanel_snapshot_language', 'sipanel_placement_snapshot', 'sipanel_certainty_snapshot',
    'sipanel_qty_provenance', 'sipanel_price_provenance', 'sipanel_invoice_gate',
}
# Commercial fields of a generated line: frozen once the revision is sealed.
GENERATED_COMMERCIAL_FIELDS = {'product_id', 'product_uom_id', 'product_uom_qty', 'price_unit',
                               'discount', 'tax_ids', 'name'}


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    sipanel_quote_scope_ids = fields.One2many('sipanel.quote.scope', 'anchor_line_id', string='Anchored scopes (all)', copy=False)
    sipanel_quote_scope_id = fields.Many2one('sipanel.quote.scope', string='Anchored scope', compute='_compute_sipanel_scope', store=True)
    sipanel_is_anchor = fields.Boolean(compute='_compute_sipanel_scope', store=True)
    sipanel_guard_state = fields.Selection([('free', 'Free'), ('sealed', 'Sealed'), ('accepted', 'Accepted')],
                                           compute='_compute_sipanel_guard', store=True)
    sipanel_is_scoped_section = fields.Boolean(compute='_compute_sipanel_scoped_section', store=True)
    sipanel_copied_from_line_id = fields.Integer(copy=False, readonly=True, help="Source line id at duplication (scope copy map).")
    # ---- STEP 2B: separately-billable projection provenance (copy=False on purpose:
    # a duplicated quotation must get its OWN projection from its own components)
    sipanel_is_generated = fields.Boolean(readonly=True, copy=False, index=True,
                                          help="Projected from a governed Scope component.")
    sipanel_origin_key = fields.Char(readonly=True, copy=False, index=True,
                                     help="Stable key of the source component within its revision.")
    sipanel_source_component_id = fields.Many2one('sipanel.quote.scope.component', readonly=True, copy=False,
                                                  ondelete='restrict', index=True)
    sipanel_source_revision_id = fields.Many2one('sipanel.quote.scope.revision', readonly=True, copy=False,
                                                 ondelete='restrict', index=True)
    sipanel_source_quote_scope_id = fields.Many2one('sipanel.quote.scope', readonly=True, copy=False,
                                                    ondelete='restrict')
    sipanel_source_scope_id = fields.Many2one('sipanel.scope', readonly=True, copy=False, ondelete='restrict')
    sipanel_snapshot_language = fields.Char(readonly=True, copy=False)
    sipanel_placement_snapshot = fields.Char(readonly=True, copy=False)
    sipanel_certainty_snapshot = fields.Char(readonly=True, copy=False)
    sipanel_qty_provenance = fields.Char(readonly=True, copy=False)
    sipanel_price_provenance = fields.Char(readonly=True, copy=False)
    sipanel_invoice_gate = fields.Char(readonly=True, copy=False,
                                       help="Non-empty when this generated line must not be invoiced yet.")

    # One live projected line per source component, enforced in the database as well
    # as in the upsert: a retry, a module upgrade or a double click must not be able
    # to create a second revenue line for the same component.
    _sipanel_origin_key_unique = models.UniqueIndex(
        "(sipanel_origin_key) WHERE sipanel_origin_key IS NOT NULL")

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

    # ---------------------------------------------------------- STEP 2B projection guards
    @api.model
    def _sipanel_projection_guarded(self):
        """True only when the projection engine itself is running."""
        return guard(self.env, 'sipanel_projection') or guard(self.env, 'sipanel_seal_transaction')

    @api.model_create_multi
    def create(self, vals_list):
        if not self._sipanel_projection_guarded():
            for vals in vals_list:
                spoofed = PROJECTION_FIELDS & set(vals)
                if spoofed:
                    # a supplied source id, a crafted origin key or a generated flag from
                    # an import, an RPC payload or sudo() must not be able to forge the
                    # provenance that invoice revenue is audited against
                    raise UserError(self.env._(
                        "Fields %s are set by the SIPANEL Scope projection only and cannot be "
                        "supplied when creating a sale order line.", ', '.join(sorted(spoofed))))
        return super().create(vals_list)

    def write(self, vals):
        ctx = self.env.context
        if not self._sipanel_projection_guarded():
            spoofed = PROJECTION_FIELDS & set(vals)
            if spoofed:
                raise UserError(self.env._(
                    "Fields %s are governed Scope provenance and cannot be written directly.",
                    ', '.join(sorted(spoofed))))
            frozen = GENERATED_COMMERCIAL_FIELDS & set(vals)
            if frozen:
                sealed = self.filtered(
                    lambda l: l.sipanel_is_generated and l.sipanel_source_revision_id
                    and l.sipanel_source_revision_id.state != 'working')
                if sealed:
                    raise UserError(self.env._(
                        "Line %(l)s is projected from sealed Scope revision %(r)s; %(f)s cannot "
                        "change. Amend the Scope and reseal instead.",
                        l=sealed[0].display_name, r=sealed[0].sipanel_source_revision_id.display_name,
                        f=', '.join(sorted(frozen))))
        if not guard(self.env, 'sipanel_governed_transition') and not guard(self.env, 'sipanel_seal_transaction'):
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
                    if 'price_unit' in vals and rev.state != 'working' and not guard(self.env, 'sipanel_apply_price'):
                        raise UserError(self.env._("Scope %s is sealed; price changes require an amendment.", scope.display_name))
                if line.sipanel_is_scoped_section and STRUCTURE_FIELDS & set(vals):
                    sealed = line.order_id.sipanel_quote_scope_ids.filtered(
                        lambda s: s.optional_section_line_id == line and s.revision_ids.filtered(lambda r: r.state != 'working'))
                    if sealed:
                        raise UserError(self.env._("Section %s structures a sealed Scope and cannot be moved or retyped.", line.display_name))
        res = super().write(vals)
        if 'name' in vals and not guard(self.env, 'sipanel_note_sync'):
            for line in self.filtered('sipanel_is_anchor'):
                rev = line.sipanel_quote_scope_id.current_revision_id
                if rev.state == 'working':
                    rev.with_context(**guard_ctx('sipanel_note_sync')).write({'final_note': vals['name'], 'note_manually_edited': True})
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_consumed_projection(self):
        """A projected line that has been invoiced, delivered or operationally
        consumed is history, not a draft artefact."""
        for line in self.filtered('sipanel_is_generated'):
            if line.invoice_lines:
                raise UserError(self.env._(
                    "Line %s is already invoiced; it cannot be removed. Use a credit note or a "
                    "change order.", line.display_name))
            if line.qty_delivered:
                raise UserError(self.env._(
                    "Line %s has delivered quantity; it cannot be removed.", line.display_name))
            rev = line.sipanel_source_revision_id
            if rev and rev.state != 'working' and not self._sipanel_projection_guarded():
                raise UserError(self.env._(
                    "Line %s is projected from a sealed Scope revision and cannot be deleted.",
                    line.display_name))

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

    # ---------------------------------------------------------- STEP 2B invoice flow
    def _prepare_invoice_line(self, **optional_values):
        """Carry the governed provenance onto the invoice line and keep the
        frozen resolved description. The rest - taxes, fiscal position, currency,
        rounding - stays exactly as Odoo prepared it."""
        vals = super()._prepare_invoice_line(**optional_values)
        if self.sipanel_is_generated:
            vals.update({
                'sipanel_source_component_id': self.sipanel_source_component_id.id,
                'sipanel_source_revision_id': self.sipanel_source_revision_id.id,
                'sipanel_source_quote_scope_id': self.sipanel_source_quote_scope_id.id,
                'sipanel_source_scope_id': self.sipanel_source_scope_id.id,
                'sipanel_origin_key': self.sipanel_origin_key,
                'sipanel_source_line_id': self.id,
            })
            # the invoice must repeat the text the customer already accepted, not a
            # freshly translated product name
            if self.name:
                vals['name'] = self.name
        return vals

    # ---------------------------------------------------------- STEP 2B procurement ownership
    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        """Exactly one operational demand owner per component.

        The frozen ownership architecture already decides this per component:
        COMPONENT_BRIDGE_OWNER means SIPANEL execution creates the demand, and
        NATIVE_LINE_OWNER means the native Sale line does and SIPANEL only links
        (see sipanel.execution.adapter.create_or_link). Projecting a component
        onto a Sale Line must not silently add a second owner, so a generated
        line whose component is bridge-owned is skipped here.
        """
        native = self.browse()
        for line in self:
            comp = line.sipanel_source_component_id
            if line.sipanel_is_generated and comp and comp.execution_owner == 'component_bridge_owner':
                continue
            native |= line
        if not native:
            return True
        return super(SaleOrderLine, native)._action_launch_stock_rule(
            previous_product_uom_qty=previous_product_uom_qty)

    def _sipanel_portal_binding(self):
        """Data injected in the portal template for anchor lines (revision id + seal hash)."""
        self.ensure_one()
        scope = self.sipanel_quote_scope_id
        rev = scope.current_revision_id if scope else False
        if rev and rev.state == 'sent_sealed':
            return {'revision_id': rev.id, 'seal_hash': rev.sealed_hash}
        return {}
