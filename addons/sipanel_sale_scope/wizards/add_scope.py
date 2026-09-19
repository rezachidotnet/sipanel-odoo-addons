# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class SipanelWizardAddScope(models.TransientModel):
    _name = 'sipanel.wizard.add.scope'
    _description = 'Add a released Scope to a quotation'

    order_id = fields.Many2one('sale.order', required=True)
    scope_id = fields.Many2one('sipanel.scope', required=True, domain="[('current_version_id', '!=', False), ('company_id', '=', company_id)]")
    company_id = fields.Many2one(related='order_id.company_id')
    version_id = fields.Many2one('sipanel.scope.version', compute='_compute_version', readonly=True)
    scope_qty = fields.Float(digits=(16, 6), required=True, default=1.0)
    quote_uom_id = fields.Many2one('uom.uom', string='Quantity unit')
    optional = fields.Boolean(string='Offer as optional (OFFERED)')
    section_line_id = fields.Many2one('sale.order.line', domain="[('order_id', '=', order_id), ('display_type', '=', 'line_section')]")
    create_section = fields.Boolean(default=True, string='Create an optional section if none selected')
    system_id = fields.Many2one('account.analytic.account')

    @api.depends('scope_id')
    def _compute_version(self):
        for w in self:
            w.version_id = w.scope_id.current_version_id
            if not w.quote_uom_id:
                w.quote_uom_id = w.version_id.base_uom_id

    def action_add(self):
        self.ensure_one()
        section = self.section_line_id
        if self.optional and not section and self.create_section:
            section = self.env['sale.order.line'].create({
                'order_id': self.order_id.id, 'display_type': 'line_section', 'name': self.env._('Options'),
                'is_optional': True, 'sequence': (max(self.order_id.order_line.mapped('sequence') or [0]) + 10),
            })
        if self.optional and section and not section.is_optional:
            raise UserError(self.env._("The selected section is not optional."))
        scope = self.env['sipanel.quote.scope']._create_from_version(
            self.order_id, self.version_id, self.scope_qty, self.quote_uom_id or self.version_id.base_uom_id,
            optional=self.optional, section_line=section if self.optional else None, system=self.system_id)
        return {'type': 'ir.actions.act_window', 'res_model': 'sipanel.quote.scope', 'res_id': scope.id, 'view_mode': 'form'}
