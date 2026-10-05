# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    sipanel_installation_product_id = fields.Many2one(
        'product.product', string='Installation product', ondelete='restrict', check_company=True,
        domain="[('type', '=', 'service'), ('sale_ok', '=', True)]",
        help="SIPANEL System only: the service product of the quotation's Installation / Execution line.")

    @api.constrains('sipanel_installation_product_id', 'plan_id')
    def _check_sipanel_installation_product(self):
        for account in self.filtered('sipanel_installation_product_id'):
            plan = self.env['sipanel.config'].system_plan()
            if account.plan_id != plan:
                raise ValidationError(self.env._(
                    "An installation product can only be set on a SIPANEL System (analytic account of the "
                    "SIPANEL System plan); \"%s\" is not one.", account.display_name))
