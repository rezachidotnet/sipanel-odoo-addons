# -*- coding: utf-8 -*-
"""Finance route policy: exactly one terminal recognised event per economic cost (GAP-E01, BQ-04, AM-03-R1)."""
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

ROUTES = [('shared_stock', 'Shared-stock material'), ('direct_purchase', 'Direct project purchase / dropship'),
          ('mfg_material', 'Manufacturing (finished issue)'), ('mfg_labour', 'Manufacturing labour'), ('site_labour', 'Site labour'),
          ('equipment_service', 'Third-party equipment / service'), ('company_equipment', 'Company-owned equipment'),
          ('freight_landed', 'Freight / landed cost'), ('return_credit', 'Returns / credits')]
TERMINAL = [('stock.move', 'stock.move (field value)'), ('account.move.line', 'account.move.line (posted bill)'),
            ('account.analytic.line', 'account.analytic.line (timesheet / analytic)'), ('hr.expense', 'hr.expense'),
            ('mrp.workorder', 'mrp.workorder'), ('none', 'NONE (deferred)')]


class SipanelCostRecognitionPolicy(models.Model):
    _name = 'sipanel.cost.recognition.policy'
    _description = 'SIPANEL cost recognition policy (route matrix)'
    _order = 'route, version desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    route = fields.Selection(ROUTES, required=True)
    version = fields.Integer(required=True, default=1)
    terminal_event_model = fields.Selection(TERMINAL, required=True)
    terminal_event_filter_json = fields.Json(help="Declarative filter fragment (documentation + projection hints).")
    commitment_model = fields.Selection([('purchase.order.line', 'purchase.order.line'), ('none', 'NONE')], default='none')
    operational_qty_model = fields.Selection([('stock.move', 'stock.move'), ('mrp.production', 'mrp.production'), ('account.analytic.line', 'account.analytic.line'), ('none', 'NONE')], default='none')
    excluded_models_json = fields.Json(help="Explicit duplicate exclusions.")
    wip_reporting = fields.Selection([('terminal_only', 'Terminal only'), ('wip_separate', 'WIP reported separately')], required=True, default='wip_separate')
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('superseded', 'Superseded')], required=True, default='draft', readonly=True)
    approved_by_id = fields.Many2one('res.users', readonly=True)
    approved_date = fields.Date(readonly=True)
    approval_source = fields.Char(readonly=True, help="Signed document / authorization reference.")
    effective_from = fields.Date()
    note = fields.Text()

    _route_version_unique = models.Constraint('UNIQUE(company_id, route, version)', 'Policy version must be unique per route.')

    @api.depends('route', 'version')
    def _compute_name(self):
        for p in self:
            p.name = f"{dict(ROUTES).get(p.route, p.route)} v{p.version}"

    def action_approve(self, source=None):
        if not self.env.user.has_group('sipanel_scope_costing.group_scope_finance'):
            raise AccessError(self.env._("Only SIPANEL Finance may approve recognition policies."))
        for p in self:
            prev = self.search([('company_id', '=', p.company_id.id), ('route', '=', p.route), ('state', '=', 'approved'), ('id', '!=', p.id)])
            prev.with_context(sipanel_policy_action=True).write({'state': 'superseded'})
            p.with_context(sipanel_policy_action=True).write({'state': 'approved', 'approved_by_id': self.env.uid, 'approved_date': fields.Date.today(),
                                                               'approval_source': source or p.approval_source})
            self.env['sipanel.scope.audit.event'].log(p, 'policy_approve', after={'route': p.route, 'version': p.version, 'source': p.approval_source})
        return True

    def write(self, vals):
        if not self.env.context.get('sipanel_policy_action'):
            if 'state' in vals or 'approved_by_id' in vals or 'approved_date' in vals:
                raise UserError(self.env._("Policy approval is only possible through the approval action."))
            if any(p.state != 'draft' for p in self) and set(vals) - {'note'}:
                raise UserError(self.env._("Approved/superseded policies are immutable; create a new version."))
        return super().write(vals)

    @api.model
    def approved_for(self, route, company):
        return self.search([('company_id', '=', company.id), ('route', '=', route), ('state', '=', 'approved')], order='version desc', limit=1)
