# -*- coding: utf-8 -*-
"""Configuration parameters (all numeric thresholds TBE; nothing hard-coded)."""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sipanel_system_plan_id = fields.Many2one('account.analytic.plan', string='SIPANEL System plan',
                                             config_parameter='sipanel_scope.system_plan_id')
    sipanel_activity_plan_id = fields.Many2one('account.analytic.plan', string='SIPANEL Activity plan',
                                               config_parameter='sipanel_scope.activity_plan_id')
    sipanel_release_retry_count = fields.Integer(string='Release retry count (LockError)',
                                                 config_parameter='sipanel_scope.release_retry_count')
    sipanel_cost_stale_days = fields.Integer(string='Cost stale after (days, blank = disabled)',
                                             config_parameter='sipanel_scope.cost_stale_days')
    sipanel_min_margin_pct = fields.Float(string='Minimum margin % (TBE; blank = disabled)',
                                          config_parameter='sipanel_scope.min_margin_pct')
    sipanel_company_currency_only = fields.Boolean(string='Company-currency-only quotations (BQ-09)',
                                                   config_parameter='sipanel_scope.company_currency_only')


class SipanelConfig(models.AbstractModel):
    """Typed accessors for the configuration keys."""
    _name = 'sipanel.config'
    _description = 'SIPANEL configuration accessors'

    def _param(self, key, default=None):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    def system_plan(self):
        pid = self._param('sipanel_scope.system_plan_id')
        return self.env['account.analytic.plan'].browse(int(pid)) if pid and str(pid).isdigit() else self.env['account.analytic.plan']

    def activity_plan(self):
        pid = self._param('sipanel_scope.activity_plan_id')
        return self.env['account.analytic.plan'].browse(int(pid)) if pid and str(pid).isdigit() else self.env['account.analytic.plan']

    def release_retry_count(self):
        val = self._param('sipanel_scope.release_retry_count')
        try:
            return max(int(val), 1)
        except (TypeError, ValueError):
            return 1

    def cost_stale_days(self):
        val = self._param('sipanel_scope.cost_stale_days')
        try:
            return int(val) or 0
        except (TypeError, ValueError):
            return 0

    def min_margin_pct(self):
        val = self._param('sipanel_scope.min_margin_pct')
        try:
            return float(val) if val not in (None, False, '') else None
        except (TypeError, ValueError):
            return None

    def company_currency_only(self):
        val = self._param('sipanel_scope.company_currency_only', 'True')
        return str(val).lower() not in ('false', '0', '')
