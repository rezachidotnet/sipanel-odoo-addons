# -*- coding: utf-8 -*-
"""Component snapshot + quantity/cost engine (GAP-B03..B07, C0-D07, C0-D08, C2-D03, C5-D01, AM-02, AM-04)."""
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import (
    guard, guard_ctx,
    ACCEPTANCE, BASIS, CERTAINTY, DIMENSION_FAMILY, DISCLOSURE, EXECUTION_MODE, KIND, NO_ACTION_REASON,
    PERCENT_BASES, PLACEMENT, PRESETS, RESPONSIBILITY, ROUNDING_MODE, find_cycle, preset_from_axes,
    round_to_increment, sha256_of)

COST_GROUP = 'sipanel_commercial_scope_core.group_scope_cost_viewer'
ESTIMATOR_GROUP = 'sipanel_commercial_scope_core.group_scope_estimator'
REASON_GROUPS = 'sipanel_commercial_scope_core.group_scope_estimator,sipanel_commercial_scope_core.group_scope_auditor,sipanel_commercial_scope_core.group_scope_cost_viewer'

ORIGIN = [('master', 'Master'), ('added', 'Added'), ('overridden', 'Overridden'), ('removed', 'Removed'),
          ('transferred', 'Transferred'), ('split_remainder', 'Split remainder'), ('split_destination', 'Split destination')]
COST_SOURCE = [('product_cost', 'Product cost'), ('manual_estimate', 'Manual estimate'), ('derived', 'Derived'),
               ('not_applicable', 'Not applicable')]
COST_STATUS = [('known', 'Known'), ('known_zero', 'Known zero'), ('missing', 'Missing'), ('not_applicable', 'Not applicable')]
RESOLUTION = [('open', 'Open'), ('resolved_product', 'Resolved to product'), ('approved_new_product', 'Approved new product'),
              ('allowance', 'Allowance'), ('customer', 'Customer'), ('deferred', 'Deferred'), ('not_required', 'Not required')]
DRIVER_FIELDS = ('basis', 'rate', 'fixed_qty', 'manual_qty', 'percent', 'base_component_ids', 'uom_id', 'rounding_increment', 'rounding_mode')


class SipanelQuoteScopeComponent(models.Model):
    _name = 'sipanel.quote.scope.component'
    _description = 'SIPANEL quote scope component snapshot'
    _order = 'revision_id, sequence, id'
    _check_company_auto = True

    revision_id = fields.Many2one('sipanel.quote.scope.revision', required=True, readonly=True, ondelete='cascade', index=True)
    quote_scope_id = fields.Many2one(related='revision_id.quote_scope_id', store=True, index=True)
    company_id = fields.Many2one(related='revision_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    occurrence_uid = fields.Char(required=True, readonly=True, copy=False, default=lambda self: str(uuid.uuid4()), index=True)
    source_occurrence_key = fields.Char(readonly=True)
    source_line_id = fields.Many2one('sipanel.scope.recipe.line', readonly=True, ondelete='restrict')
    copy_from_id = fields.Many2one('sipanel.quote.scope.component', readonly=True, ondelete='restrict')
    moved_from_id = fields.Many2one('sipanel.quote.scope.component', readonly=True, ondelete='restrict')
    moved_to_id = fields.Many2one('sipanel.quote.scope.component', readonly=True, ondelete='restrict')
    origin = fields.Selection(ORIGIN, required=True, default='added', readonly=True)
    active_state = fields.Selection([('active', 'Active'), ('tombstone', 'Tombstone')], required=True, default='active')
    sequence = fields.Integer(required=True, default=10)
    name = fields.Char(compute='_compute_name')
    kind = fields.Selection(KIND, required=True, default='product')
    product_id = fields.Many2one('product.product', ondelete='restrict')
    description = fields.Text()
    # Immutable snapshot of the master recipe line's customer label (see the
    # revision model). Only really-stored terms are copied into each column.
    customer_label_fa = fields.Char()
    customer_label_en = fields.Char()
    customer_label_resolved = fields.Char(readonly=True)
    label_provenance = fields.Json(readonly=True)
    spec_json = fields.Json()
    uom_id = fields.Many2one('uom.uom', required=True, ondelete='restrict')
    uom_name_snapshot = fields.Char(readonly=True)
    dimension_family = fields.Selection(DIMENSION_FAMILY, required=True, default='count')
    basis = fields.Selection(BASIS, required=True, default='fixed')
    rate = fields.Float(digits=(16, 6), default=0.0)
    fixed_qty = fields.Float(digits=(16, 6), default=0.0)
    manual_qty = fields.Float(digits=(16, 6), default=0.0)
    manual_qty_set = fields.Boolean(default=False, help="MANUAL basis: False/None is 'missing', not zero.")
    percent = fields.Float(digits=(16, 4), default=0.0)
    base_component_ids = fields.Many2many('sipanel.quote.scope.component', 'sipanel_component_percent_base_rel',
                                          'component_id', 'base_id', string='Base components')
    rounding_increment = fields.Float(digits=(16, 6), default=0.0)
    rounding_mode = fields.Selection(ROUNDING_MODE, required=True, default='none')
    # engine outputs
    calc_raw_qty = fields.Float(digits=(16, 6), compute='_compute_quantities', store=True, recursive=True)
    calc_rounded_qty = fields.Float(digits=(16, 6), compute='_compute_quantities', store=True, recursive=True)
    final_qty = fields.Float(digits=(16, 6), compute='_compute_quantities', store=True, recursive=True)
    qty_kind = fields.Selection([('physical', 'Physical'), ('none', 'None')], compute='_compute_quantities', store=True, recursive=True)
    qty_override = fields.Boolean(default=False)
    override_qty = fields.Float(digits=(16, 6), default=0.0)
    override_reason = fields.Text(groups=REASON_GROUPS)
    override_driver_fp = fields.Char(readonly=True, copy=False)
    override_stale = fields.Boolean(compute='_compute_override_stale', store=True)
    override_before_qty = fields.Float(digits=(16, 6), readonly=True)
    override_after_qty = fields.Float(digits=(16, 6), readonly=True)
    # cost snapshot
    cost_source = fields.Selection(COST_SOURCE, required=True, default='product_cost')
    unit_cost = fields.Monetary(currency_field='currency_id', groups=COST_GROUP)
    cost_uom_id = fields.Many2one('uom.uom', readonly=True, ondelete='restrict', groups=COST_GROUP)
    cost_uom_factor = fields.Float(digits=(16, 6), default=1.0, readonly=True, groups=COST_GROUP,
                                   help="Multiplier from unit_cost (per cost_uom) to cost per component uom (PT-26).")
    cost_source_date = fields.Datetime(readonly=True, groups=COST_GROUP)
    cost_source_company_id = fields.Many2one('res.company', readonly=True, groups=COST_GROUP)
    product_value_id = fields.Many2one('product.value', readonly=True, ondelete='restrict', groups=COST_GROUP)
    manual_cost_user_id = fields.Many2one('res.users', readonly=True, groups=COST_GROUP)
    manual_cost_date = fields.Datetime(readonly=True, groups=COST_GROUP)
    manual_cost_reason = fields.Text(groups=REASON_GROUPS)
    cost_status = fields.Selection(COST_STATUS, compute='_compute_cost_status', store=True)
    known_zero_reason = fields.Text(groups=REASON_GROUPS)
    cost_amount = fields.Monetary(currency_field='currency_id', compute='_compute_cost_amount', store=True,
                                  recursive=True, groups=COST_GROUP)
    eligible_for_rollup = fields.Boolean(compute='_compute_eligible', store=True)
    stale_cost = fields.Boolean(compute='_compute_stale_cost', groups=COST_GROUP)
    # treatment axes (AM-02)
    responsibility = fields.Selection(RESPONSIBILITY, required=True, default='sipanel')
    placement = fields.Selection(PLACEMENT, required=True, default='included_parent')
    acceptance = fields.Selection(ACCEPTANCE, compute='_compute_acceptance', store=True)
    certainty = fields.Selection(CERTAINTY, required=True, default='firm')
    provisional_basis = fields.Text()
    provisional_amount = fields.Monetary(currency_field='currency_id')
    disclosure = fields.Selection(DISCLOSURE, required=True, default='customer_eligible')
    treatment_preset = fields.Selection(PRESETS, compute='_compute_preset', store=True)
    activity_id = fields.Many2one('account.analytic.account', ondelete='restrict')
    system_id = fields.Many2one('account.analytic.account', ondelete='restrict')
    execution_mode = fields.Selection(EXECUTION_MODE, required=True, default='stock_issue')
    execution_owner = fields.Selection([('native_line_owner', 'NATIVE_LINE_OWNER'), ('component_bridge_owner', 'COMPONENT_BRIDGE_OWNER'),
                                        ('none', 'None')], compute='_compute_execution_owner', store=True)
    no_action_reason = fields.Selection(NO_ACTION_REASON)
    resolution_owner_id = fields.Many2one('res.users')
    resolution_note = fields.Text()
    resolution_state = fields.Selection(RESOLUTION, required=True, default='not_required')

    _occurrence_uid_unique = models.Constraint('UNIQUE(revision_id, occurrence_uid)', 'Occurrence uid must be unique within a revision (stable across amendments).')

    # ------------------------------------------------------------ computes
    @api.depends('product_id', 'description', 'customer_label_en', 'customer_label_fa', 'customer_label_resolved')
    def _compute_name(self):
        for c in self:
            c.name = (c.product_id.display_name or c.customer_label_resolved or c.customer_label_en
                      or c.customer_label_fa or (c.description or '')[:64])

    @api.depends('basis', 'rate', 'fixed_qty', 'manual_qty', 'manual_qty_set', 'percent', 'base_component_ids.final_qty',
                 'base_component_ids.uom_id', 'rounding_increment', 'rounding_mode', 'qty_override', 'override_qty',
                 'revision_id.scope_qty', 'active_state', 'uom_id')
    def _compute_quantities(self):
        Family = self.env['sipanel.uom.family']
        for c in self:
            if c.basis == 'percent_of_cost':
                c.calc_raw_qty = c.calc_rounded_qty = c.final_qty = 0.0
                c.qty_kind = 'none'
                continue
            if c.basis == 'per_scope_qty':
                raw = (c.revision_id.scope_qty or 0.0) * (c.rate or 0.0)
            elif c.basis == 'fixed':
                raw = c.fixed_qty or 0.0
            elif c.basis == 'manual':
                raw = c.manual_qty if c.manual_qty_set else 0.0
            else:  # percent_of_quantity
                total = 0.0
                for b in c.base_component_ids:
                    if b.active_state != 'active':
                        continue
                    qty = b.final_qty or 0.0
                    if b.uom_id != c.uom_id and Family.check_compatible(b.uom_id, c.uom_id, raise_if_failure=False):
                        qty = b.uom_id._compute_quantity(qty, c.uom_id, round=False)
                    total += qty
                raw = total * (c.percent or 0.0) / 100.0
            rounded = round_to_increment(raw, c.rounding_increment, c.rounding_mode)
            c.calc_raw_qty = raw
            c.calc_rounded_qty = rounded
            c.final_qty = c.override_qty if c.qty_override else rounded
            c.qty_kind = 'physical'

    def _driver_fingerprint(self):
        self.ensure_one()
        return sha256_of({
            'basis': self.basis, 'rate': self.rate, 'fixed': self.fixed_qty, 'manual': self.manual_qty,
            'percent': self.percent, 'bases': sorted(self.base_component_ids.mapped('occurrence_uid')),
            'uom': self.uom_id.id, 'round': [self.rounding_increment, self.rounding_mode],
            'scope_qty': self.revision_id.scope_qty,
            'base_qty': [b.final_qty for b in self.base_component_ids.sorted('id')],
        })

    @api.depends('qty_override', 'override_driver_fp', 'basis', 'rate', 'fixed_qty', 'manual_qty', 'percent',
                 'base_component_ids.final_qty', 'uom_id', 'rounding_increment', 'rounding_mode', 'revision_id.scope_qty')
    def _compute_override_stale(self):
        for c in self:
            c.override_stale = bool(c.qty_override and c.override_driver_fp and c._driver_fingerprint() != c.override_driver_fp)

    @api.depends('cost_source', 'unit_cost', 'known_zero_reason', 'product_value_id', 'responsibility', 'kind')
    def _compute_cost_status(self):
        for c in self:
            if c.responsibility == 'customer' or c.cost_source == 'not_applicable':
                c.cost_status = 'not_applicable'
            elif c.cost_source == 'derived':
                c.cost_status = 'known'
            elif c.kind == 'estimate_only' and c.cost_source == 'product_cost':
                c.cost_status = 'missing'
            elif float_is_zero(c.unit_cost or 0.0, precision_digits=6):
                c.cost_status = 'known_zero' if c.known_zero_reason else 'missing'
            else:
                c.cost_status = 'known'

    @api.depends('final_qty', 'unit_cost', 'cost_uom_factor', 'cost_source', 'percent', 'base_component_ids.cost_amount',
                 'base_component_ids.active_state', 'active_state', 'cost_status')
    def _compute_cost_amount(self):
        for c in self:
            if c.cost_status == 'not_applicable':
                c.cost_amount = 0.0
            elif c.cost_source == 'derived':
                base = sum(b.cost_amount for b in c.base_component_ids if b.active_state == 'active')
                c.cost_amount = base * (c.percent or 0.0) / 100.0
            else:
                c.cost_amount = (c.final_qty or 0.0) * (c.unit_cost or 0.0) * (c.cost_uom_factor or 1.0)

    @api.depends('responsibility', 'active_state', 'origin', 'acceptance', 'placement')
    def _compute_eligible(self):
        for c in self:
            # origin is lineage only: a TRANSFERRED destination copy is a live component; the source side is tombstoned
            c.eligible_for_rollup = (
                c.responsibility == 'sipanel' and c.active_state == 'active'
                and c.acceptance in ('base', 'accepted')
            )

    @api.depends('revision_id.quote_scope_id.acceptance_state')
    def _compute_acceptance(self):
        for c in self:
            c.acceptance = c.revision_id.quote_scope_id.acceptance_state or 'base'

    @api.depends('responsibility', 'placement', 'acceptance', 'certainty', 'disclosure')
    def _compute_preset(self):
        for c in self:
            c.treatment_preset = preset_from_axes(c.responsibility, c.placement, c.acceptance, c.certainty, c.disclosure)

    @api.depends('execution_mode', 'revision_id.quote_scope_id.source_version_id.anchor_owner_mode', 'responsibility')
    def _compute_execution_owner(self):
        for c in self:
            if c.execution_mode == 'no_action' or c.responsibility == 'customer':
                c.execution_owner = 'none'
            elif c.execution_mode == 'native_anchor_covered':
                c.execution_owner = 'native_line_owner'
            else:
                c.execution_owner = c.revision_id.quote_scope_id.source_version_id.anchor_owner_mode or 'component_bridge_owner'

    def _compute_stale_cost(self):
        days = self.env['sipanel.config'].cost_stale_days()
        now = fields.Datetime.now()
        for c in self:
            c.stale_cost = bool(days and c.cost_source == 'product_cost' and c.cost_source_date
                                and (now - c.cost_source_date).days > days)

    # ------------------------------------------------------------ constraints
    @api.constrains('basis', 'percent', 'base_component_ids', 'revision_id', 'active_state', 'origin', 'uom_id', 'dimension_family',
                    'execution_mode', 'no_action_reason', 'certainty', 'provisional_basis', 'disclosure', 'qty_override', 'override_reason')
    def _check_component(self):
        _ = self.env._
        for c in self:
            if c.active_state != 'active':
                continue
            if c.basis in PERCENT_BASES:
                if c.percent <= 0:
                    raise ValidationError(_("Percent must be > 0 (%s).", c.display_name))
                if c in c.base_component_ids:
                    raise ValidationError(_("Component %s cannot reference itself.", c.display_name))
                if any(b.revision_id != c.revision_id for b in c.base_component_ids):
                    raise ValidationError(_("Percent bases must belong to the same scope revision (cross-scope reference refused)."))
                if any(b.basis in PERCENT_BASES for b in c.base_component_ids):
                    raise ValidationError(_("Percent-on-percent is forbidden."))
                if any(b.active_state != 'active' for b in c.base_component_ids):
                    raise ValidationError(_("A percent base is tombstoned or transferred: relocate the dependent line explicitly (%s).", c.display_name))
                if c.basis == 'percent_of_quantity':
                    fams = set(c.base_component_ids.mapped('dimension_family'))
                    if len(fams) > 1 or (fams and c.dimension_family not in fams):
                        raise ValidationError(_("PERCENT_OF_QUANTITY bases must share the dimension family (%s).", c.display_name))
                if c.basis == 'percent_of_cost' and any(b.cost_source == 'derived' for b in c.base_component_ids):
                    raise ValidationError(_("PERCENT_OF_COST bases must be direct-cost components."))
            if c.execution_mode == 'no_action' and not c.no_action_reason:
                raise ValidationError(_("NO_ACTION requires a reason (%s).", c.display_name))
            if c.certainty == 'provisional' and not c.provisional_basis:
                raise ValidationError(_("PROVISIONAL components need a customer-visible basis (%s).", c.display_name))
            if c.qty_override and not c.sudo().override_reason:
                raise ValidationError(_("A quantity override requires a reason (%s).", c.display_name))
        for rev in self.mapped('revision_id'):
            edges = {x.id: set(x.base_component_ids.ids) for x in rev.component_ids}
            if find_cycle(edges):
                raise ValidationError(_("Percent bases form a cycle."))

    # ------------------------------------------------------------ CRUD guards (sealed = immutable, PT-24)
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs.mapped('revision_id')._check_working('add components to')
        recs.mapped('revision_id')._reset_review_if_stale()
        return recs

    def write(self, vals):
        if not guard(self.env, 'sipanel_seal_transaction'):
            self.mapped('revision_id')._check_working('modify components of')
        if 'qty_override' in vals or 'override_qty' in vals:
            for c in self:
                before = c.final_qty
                super(SipanelQuoteScopeComponent, c).write(vals)
                if c.qty_override:
                    c.write({'override_driver_fp': c._driver_fingerprint(), 'override_before_qty': before,
                             'override_after_qty': c.final_qty})
                    self.env['sipanel.scope.audit.event'].log(
                        c, 'override_qty', before={'final_qty': before}, after={'final_qty': c.final_qty},
                        reason=c.sudo().override_reason, revision_ref=c.revision_id.display_name)
            self.mapped('revision_id')._reset_review_if_stale()
            return True
        res = super().write(vals)
        if not guard(self.env, 'sipanel_seal_transaction'):
            self.mapped('revision_id')._reset_review_if_stale()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_working(self):
        self.mapped('revision_id')._check_working('delete components of')
        if any(c.moved_to_id or c.moved_from_id or c.copy_from_id for c in self):
            raise UserError(self.env._("Components with lineage cannot be deleted; tombstone them instead."))

    def action_tombstone(self):
        for c in self:
            dependents = c.revision_id.component_ids.filtered(lambda x: c in x.base_component_ids and x.active_state == 'active')
            if dependents:
                raise UserError(self.env._("%(n)s is a base of %(d)s; relocate the dependent first.",
                                           n=c.display_name, d=', '.join(dependents.mapped('display_name'))))
            c.write({'active_state': 'tombstone', 'origin': 'removed' if c.origin == 'master' else c.origin})
            self.env['sipanel.scope.audit.event'].log(c, 'tombstone', revision_ref=c.revision_id.display_name)
        return True

    def action_confirm_override(self):
        """Reviewer confirms a stale override is still wanted (value retained, never reset)."""
        for c in self:
            c.write({'override_driver_fp': c._driver_fingerprint()})
            self.env['sipanel.scope.audit.event'].log(c, 'override_confirmed', after={'final_qty': c.final_qty},
                                                      revision_ref=c.revision_id.display_name)
        return True

    def action_clear_override(self):
        for c in self:
            before = c.final_qty
            c.write({'qty_override': False, 'override_driver_fp': False})
            self.env['sipanel.scope.audit.event'].log(c, 'override_cleared', before={'final_qty': before},
                                                      after={'final_qty': c.final_qty}, revision_ref=c.revision_id.display_name)
        return True

    # ------------------------------------------------------------ cost snapshot (C5-D01, PT-26, PT-28)
    def _product_cost_snapshot_vals(self, product, company, target_uom):
        """Read the current governed product cost, converted to the component uom; provenance included."""
        product = product.with_company(company)
        unit_cost = product.standard_price or 0.0
        cost_uom = product.uom_id
        factor = 1.0
        if cost_uom and target_uom and cost_uom != target_uom:
            Family = self.env['sipanel.uom.family']
            Family.check_compatible(cost_uom, target_uom)
            # cost per target uom = cost per cost_uom * (target qty expressed in cost uom)
            factor = target_uom._compute_quantity(1.0, cost_uom, round=False)
        pv = self.env['product.value'].sudo().search(
            [('product_id', '=', product.id), ('company_id', '=', company.id), ('move_id', '=', False)],
            order='date desc, id desc', limit=1)
        return {
            'cost_source': 'product_cost', 'unit_cost': unit_cost, 'cost_uom_id': cost_uom.id,
            'cost_uom_factor': factor, 'cost_source_date': fields.Datetime.now(),
            'cost_source_company_id': company.id, 'product_value_id': pv.id or False,
        }

    def action_refresh_product_cost(self):
        for c in self.filtered(lambda c: c.cost_source == 'product_cost' and c.product_id):
            before = c.sudo().unit_cost
            vals = c._product_cost_snapshot_vals(c.product_id, c.company_id, c.uom_id)
            c.write(vals)
            self.env['sipanel.scope.audit.event'].log(c, 'refresh_cost', before={'unit_cost': before},
                                                      after={'unit_cost': vals['unit_cost']}, revision_ref=c.revision_id.display_name)
        return True

    def set_manual_cost(self, unit_cost, reason):
        for c in self:
            c.write({'cost_source': 'manual_estimate', 'unit_cost': unit_cost, 'cost_uom_id': c.uom_id.id, 'cost_uom_factor': 1.0,
                     'manual_cost_user_id': self.env.uid, 'manual_cost_date': fields.Datetime.now(), 'manual_cost_reason': reason,
                     'product_value_id': False})
            self.env['sipanel.scope.audit.event'].log(c, 'manual_cost', after={'unit_cost': unit_cost}, reason=reason,
                                                      revision_ref=c.revision_id.display_name)
        return True

    # ------------------------------------------------------------ payloads
    def _customer_payload(self, language):
        """Allowlist builder: the only path to customer text (C7-D01, C0-D09)."""
        self.ensure_one()
        if self.disclosure != 'customer_eligible' or self.active_state != 'active':
            return None
        # Prefer the term resolved when the snapshot was taken. Revisions created
        # before STEP 2A have no resolved term, so they keep the historical
        # language-pair lookup and their sealed artifacts stay byte-identical.
        label = self.customer_label_resolved
        if not label:
            label = self.customer_label_fa if (language or '').startswith('fa') else self.customer_label_en
            label = label or (self.customer_label_fa or self.customer_label_en)
        if not label:
            return None
        payload = {'label': label}
        if self.placement != 'no_customer_line' and self.qty_kind == 'physical':
            payload['qty'] = self.final_qty
            payload['uom'] = self.uom_name_snapshot or self.uom_id.with_context(lang=language or 'en_US').name
        if self.certainty == 'provisional':
            payload['provisional_basis'] = self.provisional_basis
        return payload

    def _snapshot_payload(self):
        self.ensure_one()
        return {
            'uid': self.occurrence_uid, 'seq': self.sequence, 'product': self.product_id.id, 'basis': self.basis,
            'rate': self.rate, 'fixed': self.fixed_qty, 'manual': self.manual_qty, 'percent': self.percent,
            'bases': sorted(self.base_component_ids.mapped('occurrence_uid')),
            'final_qty': self.final_qty, 'uom': self.uom_id.id, 'axes': [self.responsibility, self.placement, self.certainty, self.disclosure],
            'active': self.active_state, 'origin': self.origin, 'unit_cost': self.sudo().unit_cost, 'cost_amount': self.sudo().cost_amount,
        }
