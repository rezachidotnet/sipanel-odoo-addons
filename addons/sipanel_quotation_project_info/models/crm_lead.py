# -*- coding: utf-8 -*-
"""CRM Opportunity: the customer's initially requested technical System (not the final proposed
Commercial Scope architecture, and never derived from Quote Scopes)."""
from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    sipanel_system_plan_id = fields.Many2one(
        'account.analytic.plan', compute='_compute_sipanel_system_plan_id',
        help="Technical: the resolved SIPANEL System plan, used by the Requested System domain.")
    sipanel_requested_system_id = fields.Many2one(
        'account.analytic.account', string='Requested System',
        index='btree_not_null', ondelete='restrict', tracking=True, check_company=True,
        domain="[('plan_id', '=', sipanel_system_plan_id), ('company_id', 'in', [company_id, False])]",
        help="The technical system the customer initially asked for (e.g. Standing Seam, Sandwich Panel). "
             "Copied once to new quotations of this opportunity.")

    def _compute_sipanel_system_plan_id(self):
        plan = self.env['sipanel.config'].system_plan_or_empty()
        for lead in self:
            lead.sipanel_system_plan_id = plan

    @api.constrains('sipanel_requested_system_id')
    def _check_sipanel_requested_system(self):
        self.env['sipanel.config'].check_requested_system(self)
