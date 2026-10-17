# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    sipanel_installation_pct_default = fields.Float(
        string='Default installation %', digits=(16, 4),
        help="Installation / Execution percentage proposed on new quotations. Empty or 0 = no installation line.")
    sipanel_shop_drawing_pct_default = fields.Float(
        string='Default shop drawings %', digits=(16, 4),
        help="Shop drawings percentage proposed on new quotations. Empty or 0 = no shop drawings line.")
    sipanel_shop_drawing_discount_default = fields.Float(
        string='Default shop drawings discount %', digits=(16, 4),
        help="Discount proposed on the shop drawings line of new quotations (100 = shown at net 0).")
