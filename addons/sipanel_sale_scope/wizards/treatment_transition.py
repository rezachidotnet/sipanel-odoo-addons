# -*- coding: utf-8 -*-
"""Operator acceptance transition and component preset (axis) change, both audited (GAP-C03, C05)."""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import ACCEPTANCE, CERTAINTY, DISCLOSURE, PLACEMENT, RESPONSIBILITY


class SipanelWizardTreatmentTransition(models.TransientModel):
    _name = 'sipanel.wizard.treatment.transition'
    _description = 'Governed treatment / acceptance transition'

    quote_scope_id = fields.Many2one('sipanel.quote.scope')
    component_id = fields.Many2one('sipanel.quote.scope.component')
    kind = fields.Selection([('acceptance', 'Scope acceptance (OFFERED/ACCEPTED/DECLINED)'), ('axes', 'Component treatment axes')], required=True, default='acceptance')
    new_acceptance = fields.Selection(ACCEPTANCE)
    responsibility = fields.Selection(RESPONSIBILITY)
    placement = fields.Selection(PLACEMENT)
    certainty = fields.Selection(CERTAINTY)
    provisional_basis = fields.Text()
    disclosure = fields.Selection(DISCLOSURE)
    reason = fields.Text(required=True)

    def action_apply(self):
        self.ensure_one()
        if self.kind == 'acceptance':
            if not self.quote_scope_id or not self.new_acceptance:
                raise UserError(self.env._("Choose the scope and the new acceptance state."))
            self.quote_scope_id._transition_acceptance(self.new_acceptance, actor='operator', reason=self.reason)
        else:
            c = self.component_id
            if not c:
                raise UserError(self.env._("Choose a component."))
            before = {'responsibility': c.responsibility, 'placement': c.placement, 'certainty': c.certainty, 'disclosure': c.disclosure, 'preset': c.treatment_preset}
            vals = {k: getattr(self, k) for k in ('responsibility', 'placement', 'certainty', 'disclosure') if getattr(self, k)}
            if vals.get('certainty') == 'provisional' or (c.certainty == 'provisional' and 'certainty' not in vals):
                vals['provisional_basis'] = self.provisional_basis or c.provisional_basis
            if vals.get('responsibility') == 'customer':
                vals.update({'cost_source': 'not_applicable', 'execution_mode': 'no_action', 'no_action_reason': 'customer_responsibility'})
            if vals.get('disclosure') == 'internal_only':
                # keep the frozen label; an internal-only line is simply not published
                vals['customer_label_fa'] = c.customer_label_fa
            c.write(vals)
            self.env['sipanel.scope.audit.event'].log(c, 'preset_change', before=before,
                                                      after={'responsibility': c.responsibility, 'placement': c.placement, 'certainty': c.certainty,
                                                             'disclosure': c.disclosure, 'preset': c.treatment_preset},
                                                      reason=self.reason, revision_ref=c.revision_id.display_name)
        return {'type': 'ir.actions.act_window_close'}
