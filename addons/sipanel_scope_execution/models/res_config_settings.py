# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sipanel_stock_issue_picking_type_id = fields.Many2one('stock.picking.type', string='Stock issue operation type',
                                                          config_parameter='sipanel_scope.stock_issue_picking_type_id')
    sipanel_default_project_id = fields.Many2one('project.project', string='Default execution project',
                                                 config_parameter='sipanel_scope.default_project_id')
    sipanel_release_backoff_ms = fields.Integer(string='Release retry backoff (ms)', config_parameter='sipanel_scope.release_backoff_ms')


class SipanelConfig(models.AbstractModel):
    _inherit = 'sipanel.config'

    def stock_issue_picking_type(self):
        pid = self._param('sipanel_scope.stock_issue_picking_type_id')
        PT = self.env['stock.picking.type']
        return PT.browse(int(pid)) if pid and str(pid).isdigit() else PT

    def default_project(self):
        pid = self._param('sipanel_scope.default_project_id')
        P = self.env['project.project']
        return P.browse(int(pid)) if pid and str(pid).isdigit() else P

    def release_backoff_ms(self):
        val = self._param('sipanel_scope.release_backoff_ms')
        try:
            return max(int(val), 0)
        except (TypeError, ValueError):
            return 0
