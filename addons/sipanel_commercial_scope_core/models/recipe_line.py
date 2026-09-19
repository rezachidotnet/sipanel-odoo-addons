# -*- coding: utf-8 -*-
"""Recipe occurrence (GAP-A04, GAP-A05, GAP-A08; C0-D03, C2-D02, C2-D03)."""
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .sipanel_tools import (BASIS, CERTAINTY, DIMENSION_FAMILY, DISCLOSURE, EXECUTION_MODE, KIND,
                            NO_ACTION_REASON, PERCENT_BASES, PLACEMENT, RESPONSIBILITY, ROUNDING_MODE,
                            find_cycle)


class SipanelScopeRecipeLine(models.Model):
    _name = 'sipanel.scope.recipe.line'
    _description = 'SIPANEL recipe line (master occurrence)'
    _order = 'version_id, sequence, id'
    _check_company_auto = True

    version_id = fields.Many2one('sipanel.scope.version', required=True, readonly=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='version_id.company_id', store=True, index=True)
    occurrence_key = fields.Char(required=True, readonly=True, copy=False, default=lambda self: str(uuid.uuid4()))
    sequence = fields.Integer(required=True, default=10)
    name = fields.Char(compute='_compute_name')
    kind = fields.Selection(KIND, required=True, default='product')
    product_id = fields.Many2one('product.product', ondelete='restrict')
    internal_description = fields.Text()
    customer_label_fa = fields.Char()
    customer_label_en = fields.Char()
    customer_eligible = fields.Boolean(default=False)
    spec_json = fields.Json()
    uom_id = fields.Many2one('uom.uom', required=True, ondelete='restrict')
    dimension_family = fields.Selection(DIMENSION_FAMILY, required=True, default='count')
    basis = fields.Selection(BASIS, required=True, default='per_scope_qty')
    rate = fields.Float(digits=(16, 6), default=0.0, help="Component unit per BASE unit of the scope.")
    fixed_qty = fields.Float(digits=(16, 6), default=0.0)
    manual_qty_default = fields.Float(digits=(16, 6), default=0.0)
    percent = fields.Float(digits=(16, 4), default=0.0)
    base_line_ids = fields.Many2many('sipanel.scope.recipe.line', 'sipanel_recipe_percent_base_rel',
                                     'line_id', 'base_id', string='Base lines')
    rounding_increment = fields.Float(digits=(16, 6), required=True, default=0.0)
    rounding_mode = fields.Selection(ROUNDING_MODE, required=True, default='none')
    activity_id = fields.Many2one('account.analytic.account', ondelete='restrict')
    execution_mode = fields.Selection(EXECUTION_MODE, required=True, default='stock_issue')
    no_action_reason = fields.Selection(NO_ACTION_REASON)
    cost_policy = fields.Selection([('product_cost', 'Product cost'), ('manual_estimate', 'Manual estimate'),
                                    ('derived', 'Derived')], required=True, default='product_cost')
    manual_cost_default = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    responsibility = fields.Selection(RESPONSIBILITY, required=True, default='sipanel')
    placement = fields.Selection(PLACEMENT, required=True, default='included_parent')
    certainty = fields.Selection(CERTAINTY, required=True, default='firm')
    disclosure = fields.Selection(DISCLOSURE, required=True, default='customer_eligible')
    resolution_owner_id = fields.Many2one('res.users')
    resolution_note = fields.Text()

    _occurrence_key_unique = models.Constraint('UNIQUE(occurrence_key)', 'Occurrence key must be unique.')
    _rate_positive = models.Constraint('CHECK(rate >= 0 AND fixed_qty >= 0 AND rounding_increment >= 0)',
                                       'Rates, fixed quantities and rounding increments must be >= 0.')

    @api.depends('product_id', 'internal_description', 'kind')
    def _compute_name(self):
        for l in self:
            l.name = l.product_id.display_name if l.product_id else (l.internal_description or '')[:64] or self.env._('Estimate only')

    @api.onchange('basis')
    def _onchange_basis(self):
        if self.basis == 'percent_of_cost':
            self.cost_policy = 'derived'
        elif self.cost_policy == 'derived':
            self.cost_policy = 'product_cost'

    @api.onchange('version_id')
    def _onchange_version_defaults(self):
        v = self.version_id
        if v:
            self.responsibility = v.default_responsibility
            self.placement = v.default_placement
            self.certainty = v.default_certainty
            self.disclosure = v.default_disclosure

    # ---------------------------------------------------------------- constraints
    @api.constrains('kind', 'product_id', 'resolution_owner_id', 'internal_description', 'basis', 'percent',
                    'base_line_ids', 'cost_policy', 'execution_mode', 'no_action_reason', 'disclosure',
                    'customer_eligible', 'dimension_family', 'uom_id')
    def _check_line(self):
        Family = self.env['sipanel.uom.family']
        for l in self:
            _ = self.env._
            if l.kind == 'product' and not l.product_id:
                raise ValidationError(_("A PRODUCT line needs a product."))
            if l.kind == 'estimate_only' and l.product_id:
                raise ValidationError(_("An ESTIMATE_ONLY line must not carry a product; resolve it at quote time."))
            if l.basis in PERCENT_BASES:
                if l.percent <= 0:
                    raise ValidationError(_("Percent must be > 0."))
                if l in l.base_line_ids:
                    raise ValidationError(_("A percent line cannot reference itself."))
                if any(b.version_id != l.version_id for b in l.base_line_ids):
                    raise ValidationError(_("Percent bases must belong to the same version."))
                if any(b.basis in PERCENT_BASES for b in l.base_line_ids):
                    raise ValidationError(_("Percent-on-percent is forbidden."))
                if l.basis == 'percent_of_quantity':
                    fams = set(l.base_line_ids.mapped('dimension_family'))
                    if len(fams) > 1 or (fams and l.dimension_family not in fams):
                        raise ValidationError(_("PERCENT_OF_QUANTITY bases must share the line's dimension family."))
                if l.basis == 'percent_of_cost' and l.cost_policy != 'derived':
                    raise ValidationError(_("PERCENT_OF_COST lines are always DERIVED cost."))
            elif l.cost_policy == 'derived':
                raise ValidationError(_("Only PERCENT_OF_COST lines may have DERIVED cost."))
            if l.execution_mode == 'no_action' and not l.no_action_reason:
                raise ValidationError(_("NO_ACTION requires a reason."))
            if l.disclosure == 'internal_only' and l.customer_eligible:
                raise ValidationError(_("INTERNAL_ONLY lines cannot be customer-eligible."))
            fam = Family.family_of(l.uom_id)
            if fam and fam != l.dimension_family:
                raise ValidationError(_("Unit %(u)s is tagged %(f)s, not %(d)s.", u=l.uom_id.display_name, f=fam, d=l.dimension_family))
        # acyclic per version
        for version in self.mapped('version_id'):
            edges = {x.id: set(x.base_line_ids.ids) for x in version.recipe_line_ids}
            if find_cycle(edges):
                raise ValidationError(self.env._("Percent bases form a cycle."))

    # ---------------------------------------------------------------- immutability (PT-24)
    def _check_version_draft(self, action):
        frozen = self.filtered(lambda l: l.version_id.state != 'draft')
        if frozen and not self.env.context.get('sipanel_release_transaction'):
            raise UserError(self.env._("Cannot %(a)s recipe lines of %(v)s: the version is %(s)s.",
                                       a=action, v=frozen[0].version_id.display_name, s=frozen[0].version_id.state))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_version_draft('create')
        return lines

    def write(self, vals):
        self._check_version_draft('modify')
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        self._check_version_draft('delete')
        for l in self:
            dependents = self.search([('base_line_ids', 'in', l.id)])
            if dependents:
                raise UserError(self.env._("Line %s is a base of a percent line; remove that reference first.", l.display_name))

    def _content_payload(self):
        self.ensure_one()
        return {
            'key': self.occurrence_key, 'seq': self.sequence, 'kind': self.kind,
            'product': self.product_id.id, 'desc': self.internal_description,
            'label_fa': self.customer_label_fa, 'label_en': self.customer_label_en,
            'eligible': self.customer_eligible, 'spec': self.spec_json,
            'uom': self.uom_id.id, 'family': self.dimension_family, 'basis': self.basis,
            'rate': self.rate, 'fixed': self.fixed_qty, 'manual': self.manual_qty_default, 'percent': self.percent,
            'bases': sorted(self.base_line_ids.mapped('occurrence_key')),
            'round': [self.rounding_increment, self.rounding_mode],
            'activity': self.activity_id.id, 'mode': self.execution_mode, 'no_action': self.no_action_reason,
            'cost_policy': self.cost_policy, 'manual_cost': self.manual_cost_default,
            'axes': [self.responsibility, self.placement, self.certainty, self.disclosure],
            'resolution': [self.resolution_owner_id.id, self.resolution_note],
        }
