# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # owner review 2026-10-12: «طالقانی» on fa_IR quotations while the user stays "Taleghani" everywhere else
    sipanel_quotation_name_fa = fields.Char(
        string='نام فروشنده در پیش‌فاکتور فارسی',
        help="Printed as the salesperson on fa_IR quotations (header box and signature). Empty = the user name. "
             "The user name itself is not changed.")
