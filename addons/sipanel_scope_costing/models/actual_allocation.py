# -*- coding: utf-8 -*-
"""Allocation of an event to demand/occurrence; the remainder is visible UNALLOCATED (GAP-E08, BQ-06=A)."""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class SipanelActualAllocation(models.Model):
    _name = 'sipanel.actual.allocation'
    _description = 'SIPANEL actual cost allocation'

    event_id = fields.Many2one('sipanel.actual.cost.event', required=True, readonly=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='event_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    demand_id = fields.Many2one('sipanel.execution.demand', readonly=True, ondelete='restrict', index=True)
    component_id = fields.Many2one('sipanel.quote.scope.component', readonly=True, ondelete='restrict', index=True)
    quote_scope_id = fields.Many2one('sipanel.quote.scope', readonly=True, ondelete='restrict', index=True)
    allocation_basis = fields.Selection([('target_link', 'Target link'), ('dimension_match', 'Dimension match'), ('manual', 'Manual'), ('unallocated', 'Unallocated')],
                                        required=True, readonly=True)
    amount = fields.Monetary(currency_field='currency_id', required=True, readonly=True)
    reviewer_id = fields.Many2one('res.users', readonly=True)
    reason = fields.Text(readonly=True)

    @api.constrains('amount', 'event_id')
    def _check_sum(self):
        for ev in self.mapped('event_id'):
            total = sum(ev.allocation_ids.mapped('amount'))
            if abs(total) - abs(ev.amount) > 1e-4:
                raise ValidationError(self.env._("Allocations exceed the event amount (%s).", ev.display_name))

    @api.model
    def allocate_manually(self, event, quote_scope, component, amount, reason):
        if not self.env.user.has_group('sipanel_scope_costing.group_scope_finance'):
            raise UserError(self.env._("Only SIPANEL Finance may allocate manually."))
        if not reason:
            raise UserError(self.env._("A reason is required for manual allocation."))
        alloc = self.with_context(sipanel_projection=True).create({
            'event_id': event.id, 'quote_scope_id': quote_scope.id, 'component_id': component.id if component else False,
            'allocation_basis': 'manual', 'amount': amount, 'reviewer_id': self.env.uid, 'reason': reason})
        self.env['sipanel.scope.audit.event'].log(event, 'manual_allocation', after={'amount': amount, 'quote_scope_id': quote_scope.id}, reason=reason)
        return alloc
