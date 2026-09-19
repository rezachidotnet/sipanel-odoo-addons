# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sipanel_actual_event_count = fields.Integer(compute='_compute_sipanel_actual_count')

    def _compute_sipanel_actual_count(self):
        Alloc = self.env['sipanel.actual.allocation'].sudo()
        for o in self:
            o.sipanel_actual_event_count = Alloc.search_count([('quote_scope_id.order_id', '=', o.id)])

    def action_sipanel_refresh_actuals(self):
        self.ensure_one()
        self.env['sipanel.actual.projection'].refresh_order(self)
        return {'type': 'ir.actions.act_window', 'name': self.env._('Scope variance'), 'res_model': 'sipanel.scope.variance',
                'view_mode': 'list', 'domain': [('order_id', '=', self.id)]}
