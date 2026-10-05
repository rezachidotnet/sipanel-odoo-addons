# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    sipanel_installation_pct_default = fields.Float(
        string='Default installation %', digits=(16, 4),
        help="Installation / Execution percentage proposed on new quotations. Empty or 0 = no installation line.")
