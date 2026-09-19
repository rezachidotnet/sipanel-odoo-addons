# -*- coding: utf-8 -*-
"""Read-only projection of selected recognised events (GAP-E02, E03, E07; C8-D04)."""
from odoo import api, fields, models
from odoo.exceptions import UserError

COST_GROUP = 'sipanel_commercial_scope_core.group_scope_cost_viewer'


class SipanelActualCostEvent(models.Model):
    _name = 'sipanel.actual.cost.event'
    _description = 'SIPANEL actual cost event (projection)'
    _order = 'event_date desc, id desc'

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    policy_id = fields.Many2one('sipanel.cost.recognition.policy', readonly=True, ondelete='restrict')
    route = fields.Selection(related='policy_id.route', store=True)
    source_model = fields.Char(required=True, readonly=True, index=True)
    source_res_id = fields.Integer(required=True, readonly=True, index=True)
    component_type = fields.Selection([('material', 'Material'), ('labour', 'Labour'), ('service', 'Service'), ('equipment', 'Equipment'),
                                       ('adjustment', 'Adjustment'), ('revenue', 'Revenue')], required=True, readonly=True)
    source_key = fields.Char(required=True, readonly=True, index=True)
    layer = fields.Selection([('commitment', 'Commitment'), ('operational', 'Operational quantity'), ('wip', 'WIP'), ('recognized', 'Recognised')],
                             required=True, readonly=True, default='recognized')
    inclusion = fields.Selection([('included', 'Included'), ('excluded_duplicate', 'Excluded (duplicate layer)'), ('policy_missing', 'Policy missing')],
                                 required=True, readonly=True, default='included')
    amount = fields.Monetary(currency_field='currency_id', required=True, readonly=True)
    event_date = fields.Date(required=True, readonly=True)
    project_id = fields.Many2one('project.project', readonly=True, ondelete='restrict', index=True)
    system_id = fields.Many2one('account.analytic.account', readonly=True, ondelete='restrict')
    activity_id = fields.Many2one('account.analytic.account', readonly=True, ondelete='restrict')
    qty = fields.Float(digits=(16, 6), readonly=True)
    uom_id = fields.Many2one('uom.uom', readonly=True, ondelete='restrict')
    qty_kind = fields.Selection([('consumed', 'Consumed'), ('produced', 'Produced'), ('received', 'Received'), ('returned', 'Returned'),
                                 ('hours', 'Hours'), ('none', 'None')], readonly=True, default='none')
    reversal_of_id = fields.Many2one('sipanel.actual.cost.event', readonly=True, ondelete='restrict')
    allocation_ids = fields.One2many('sipanel.actual.allocation', 'event_id')
    allocated_amount = fields.Monetary(currency_field='currency_id', compute='_compute_allocation', store=True)
    unallocated_amount = fields.Monetary(currency_field='currency_id', compute='_compute_allocation', store=True)
    allocation_state = fields.Selection([('allocated', 'Allocated'), ('partial', 'Partial'), ('unallocated', 'UNALLOCATED'), ('unpolicied', 'UNPOLICIED')],
                                        compute='_compute_allocation', store=True)
    inclusion_policy_version = fields.Integer(readonly=True)
    cost_source_zero = fields.Boolean(readonly=True, help="Terminal event exists but carries zero amount (e.g. zero hourly cost).")
    source_display = fields.Char(compute='_compute_source_display')

    _source_key_unique = models.Constraint('UNIQUE(source_key)', 'One inclusion per monetary source (C8-D04).')

    @api.depends('allocation_ids.amount', 'amount', 'inclusion', 'policy_id')
    def _compute_allocation(self):
        for e in self:
            alloc = sum(e.allocation_ids.filtered(lambda a: a.allocation_basis != 'unallocated').mapped('amount'))
            e.allocated_amount = alloc
            e.unallocated_amount = e.amount - alloc
            if e.inclusion == 'policy_missing':
                e.allocation_state = 'unpolicied'
            elif abs(e.unallocated_amount) < 1e-6:
                e.allocation_state = 'allocated'
            elif abs(alloc) < 1e-6:
                e.allocation_state = 'unallocated'
            else:
                e.allocation_state = 'partial'

    def _compute_source_display(self):
        for e in self:
            rec = self.env[e.source_model].sudo().browse(e.source_res_id).exists() if e.source_model in self.env else None
            e.source_display = rec.display_name if rec else f"{e.source_model}/{e.source_res_id}"

    @api.model
    def make_key(self, model, res_id, component_type, company):
        return f"{model}:{res_id}:{component_type}:{company.id}"

    def write(self, vals):
        if not self.env.context.get('sipanel_projection'):
            raise UserError(self.env._("Actual cost events are a projection; refresh them instead of editing."))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('sipanel_projection'):
            raise UserError(self.env._("Actual cost events are a projection; refresh them instead of deleting."))
        return super().unlink()
