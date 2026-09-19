# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SipanelWizardRefreshCost(models.TransientModel):
    _name = 'sipanel.wizard.refresh.cost'
    _description = 'Refresh PRODUCT_COST snapshots with before/after preview'

    revision_id = fields.Many2one('sipanel.quote.scope.revision', required=True)
    line_ids = fields.One2many('sipanel.wizard.refresh.cost.line', 'wizard_id')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        rev_id = res.get('revision_id') or self.env.context.get('default_revision_id')
        if rev_id:
            rev = self.env['sipanel.quote.scope.revision'].browse(rev_id)
            lines = []
            for c in rev.component_ids.filtered(lambda c: c.cost_source == 'product_cost' and c.product_id and c.active_state == 'active'):
                new = c._product_cost_snapshot_vals(c.product_id, c.company_id, c.uom_id)
                lines.append((0, 0, {'component_id': c.id, 'old_unit_cost': c.sudo().unit_cost, 'new_unit_cost': new['unit_cost'],
                                     'selected': abs((c.sudo().unit_cost or 0) - (new['unit_cost'] or 0)) > 1e-9}))
            res['line_ids'] = lines
        return res

    def action_apply(self):
        self.ensure_one()
        self.revision_id._check_working('refresh costs of')
        self.line_ids.filtered('selected').mapped('component_id').action_refresh_product_cost()
        return {'type': 'ir.actions.act_window_close'}


class SipanelWizardRefreshCostLine(models.TransientModel):
    _name = 'sipanel.wizard.refresh.cost.line'
    _description = 'Refresh cost preview line'

    wizard_id = fields.Many2one('sipanel.wizard.refresh.cost', required=True, ondelete='cascade')
    component_id = fields.Many2one('sipanel.quote.scope.component', required=True)
    old_unit_cost = fields.Float(digits=(16, 6))
    new_unit_cost = fields.Float(digits=(16, 6))
    selected = fields.Boolean()
