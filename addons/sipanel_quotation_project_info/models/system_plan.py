# -*- coding: utf-8 -*-
"""Resolution of the SIPANEL System analytic plan (the System master is account.analytic.account
under that plan; there is no sipanel.system model and no second System list).

Never a hard-coded database id: ids differ between Clone and Production.
Order: 1. a stable XML id, if one exists; 2. the exact plan name "SIPANEL System".
More than one match fails closed. The configured plan (sipanel_scope.system_plan_id, the setting
the Commercial Scope core already uses) must agree with the result, otherwise it fails closed too.
account.analytic.plan has no company in Odoo 19 (plans are shared); company separation is applied
on the System records (account.analytic.account.company_id) by the field domains and check_company.
"""
from odoo import models
from odoo.exceptions import UserError, ValidationError

SYSTEM_PLAN_XMLIDS = (
    'sipanel_commercial_scope_core.analytic_plan_sipanel_system',
    'sipanel_quotation_project_info.analytic_plan_sipanel_system',
)
SYSTEM_PLAN_NAME = 'SIPANEL System'


class SipanelConfig(models.AbstractModel):
    _inherit = 'sipanel.config'

    def resolve_system_plan(self):
        """Return the SIPANEL System plan, or raise UserError when it is missing or ambiguous."""
        Plan = self.env['account.analytic.plan'].sudo()
        plan = Plan
        for xmlid in SYSTEM_PLAN_XMLIDS:
            record = self.env.ref(xmlid, raise_if_not_found=False)
            if record and record._name == Plan._name:
                plan = record.sudo()
                break
        if not plan:
            # the plan name is translatable: match the stored source (en_US) value, not the user's language
            matches = Plan.with_context(lang='en_US').search([('name', '=', SYSTEM_PLAN_NAME)])
            if len(matches) > 1:
                raise UserError(self.env._(
                    "SIPANEL System plan is ambiguous: %(n)s analytic plans are named \"%(name)s\". "
                    "Rename or merge the duplicates; no plan is picked automatically.",
                    n=len(matches), name=SYSTEM_PLAN_NAME))
            plan = matches
        if not plan:
            raise UserError(self.env._(
                "SIPANEL System plan not found: no analytic plan is named \"%(name)s\".", name=SYSTEM_PLAN_NAME))
        configured = self.system_plan()
        if configured and configured.exists() and configured != plan:
            raise UserError(self.env._(
                "SIPANEL System plan is ambiguous: the configured plan \"%(c)s\" differs from the plan "
                "\"%(p)s\" resolved by name. Fix the SIPANEL settings first.",
                c=configured.sudo().name, p=plan.name))
        return plan

    def system_plan_or_empty(self):
        """Same as resolve_system_plan() for UI domains: an unresolvable plan offers no System at all."""
        try:
            return self.resolve_system_plan()
        except UserError:
            return self.env['account.analytic.plan']

    def check_requested_system(self, records, fname='sipanel_requested_system_id'):
        """Server-side guard behind the field domains: a Requested System must belong to the resolved
        SIPANEL System plan. Company compatibility is enforced natively by check_company."""
        assigned = records.filtered(fname)
        if not assigned:
            return
        plan = self.resolve_system_plan()
        for record in assigned:
            system = record[fname].sudo()
            if system.plan_id != plan:
                raise ValidationError(self.env._(
                    "\"%(s)s\" is not a SIPANEL System: Requested System must be an analytic account of the "
                    "\"%(p)s\" plan.", s=system.name, p=plan.name))
