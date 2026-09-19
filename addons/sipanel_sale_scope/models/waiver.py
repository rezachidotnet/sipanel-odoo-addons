# -*- coding: utf-8 -*-
"""Joint Finance + Sales commercial waiver (GAP-B11, BQ-02=B)."""
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class SipanelQuoteWaiver(models.Model):
    _name = 'sipanel.quote.waiver'
    _description = 'SIPANEL commercial waiver (joint approval)'
    _inherit = ['mail.thread']

    revision_id = fields.Many2one('sipanel.quote.scope.revision', required=True, readonly=True, ondelete='restrict', index=True)
    order_id = fields.Many2one(related='revision_id.order_id', store=True)
    company_id = fields.Many2one(related='revision_id.company_id', store=True)
    waiver_type = fields.Selection([('negative_margin', 'Negative margin'), ('missing_estimate', 'Missing estimate'),
                                    ('below_min_margin', 'Below minimum margin')], required=True)
    reason = fields.Text(required=True, groups='sipanel_commercial_scope_core.group_scope_estimator,sipanel_commercial_scope_core.group_scope_auditor,sipanel_sale_scope.group_scope_sales,sipanel_sale_scope.group_scope_waiver_sales,sipanel_sale_scope.group_scope_waiver_finance,sipanel_commercial_scope_core.group_scope_cost_viewer')
    sales_approver_id = fields.Many2one('res.users', readonly=True)
    sales_approved_date = fields.Datetime(readonly=True)
    finance_approver_id = fields.Many2one('res.users', readonly=True)
    finance_approved_date = fields.Datetime(readonly=True)
    rejected_by_id = fields.Many2one('res.users', readonly=True)
    state = fields.Selection([('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
                             compute='_compute_state', store=True, tracking=True)

    @api.depends('sales_approver_id', 'finance_approver_id', 'rejected_by_id')
    def _compute_state(self):
        for w in self:
            if w.rejected_by_id:
                w.state = 'rejected'
            elif w.sales_approver_id and w.finance_approver_id:
                w.state = 'approved'
            else:
                w.state = 'pending'

    def action_approve_sales(self):
        if not self.env.user.has_group('sipanel_sale_scope.group_scope_waiver_sales'):
            raise AccessError(self.env._("Only the Sales waiver approver may approve this half."))
        for w in self:
            w.with_context(sipanel_waiver_action=True).write({'sales_approver_id': self.env.uid, 'sales_approved_date': fields.Datetime.now()})
            self.env['sipanel.scope.audit.event'].log(w, 'waiver_sales_approve', reason=w.sudo().reason, revision_ref=w.revision_id.display_name)
        return True

    def action_approve_finance(self):
        if not self.env.user.has_group('sipanel_sale_scope.group_scope_waiver_finance'):
            raise AccessError(self.env._("Only the Finance waiver approver may approve this half."))
        for w in self:
            w.with_context(sipanel_waiver_action=True).write({'finance_approver_id': self.env.uid, 'finance_approved_date': fields.Datetime.now()})
            self.env['sipanel.scope.audit.event'].log(w, 'waiver_finance_approve', reason=w.sudo().reason, revision_ref=w.revision_id.display_name)
        return True

    def action_reject(self):
        if not (self.env.user.has_group('sipanel_sale_scope.group_scope_waiver_sales') or self.env.user.has_group('sipanel_sale_scope.group_scope_waiver_finance')):
            raise AccessError(self.env._("Only a waiver approver may reject."))
        for w in self:
            w.with_context(sipanel_waiver_action=True).write({'rejected_by_id': self.env.uid})
            self.env['sipanel.scope.audit.event'].log(w, 'waiver_reject', reason=w.sudo().reason, revision_ref=w.revision_id.display_name)
        return True

    def write(self, vals):
        protected = {'sales_approver_id', 'sales_approved_date', 'finance_approver_id', 'finance_approved_date', 'rejected_by_id'}
        if protected & set(vals) and not self.env.context.get('sipanel_waiver_action'):
            raise UserError(self.env._("Approver fields are set only through the approval actions."))
        return super().write(vals)
