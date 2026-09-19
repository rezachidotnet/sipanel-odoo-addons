# -*- coding: utf-8 -*-
"""Apply Price: target margin or markup -> explicit write of price_unit on the anchor (GAP-B10, C5-D03)."""
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx

COST_GROUP = 'sipanel_commercial_scope_core.group_scope_cost_viewer'


class SipanelWizardApplyPrice(models.TransientModel):
    _name = 'sipanel.wizard.apply.price'
    _description = 'Apply price from target margin / markup'

    quote_scope_id = fields.Many2one('sipanel.quote.scope', required=True)
    mode = fields.Selection([('margin', 'Target margin % (of revenue)'), ('markup', 'Markup % (on cost)'), ('amount', 'Net revenue amount')], required=True, default='margin')
    value = fields.Float(digits=(16, 4))
    cost_total = fields.Float(compute='_compute_preview', groups=COST_GROUP)
    suggested_revenue = fields.Float(compute='_compute_preview', groups=COST_GROUP)
    suggested_price_unit = fields.Float(compute='_compute_preview', groups=COST_GROUP)
    reason = fields.Text()

    @api.depends('quote_scope_id', 'mode', 'value')
    def _compute_preview(self):
        for w in self:
            rev = w.quote_scope_id.current_revision_id.sudo()
            C = rev.eligible_cost_total or 0.0
            if w.mode == 'margin':
                m = w.value / 100.0
                R = C / (1 - m) if m < 1 else 0.0
            elif w.mode == 'markup':
                R = C * (1 + w.value / 100.0)
            else:
                R = w.value
            qty = w.quote_scope_id.anchor_line_id.product_uom_qty or rev.scope_qty or 0.0
            w.cost_total = C
            w.suggested_revenue = R
            w.suggested_price_unit = R / qty if qty else 0.0

    def action_apply(self):
        self.ensure_one()
        scope = self.quote_scope_id
        rev = scope.current_revision_id
        rev._check_working('apply a price to')
        line = scope.anchor_line_id
        qty = line.product_uom_qty or rev.scope_qty
        if not qty:
            raise UserError(self.env._("Anchor quantity is zero; set the quantity before pricing."))
        before = line.price_unit
        new_price = self.sudo().suggested_revenue / qty
        line.with_context(**guard_ctx('sipanel_apply_price')).write({'price_unit': new_price})
        self.env['sipanel.scope.audit.event'].log(scope, 'apply_price', before={'price_unit': before}, after={'price_unit': new_price, 'mode': self.mode, 'value': self.value},
                                                  reason=self.reason, revision_ref=rev.display_name)
        return {'type': 'ir.actions.act_window_close'}
