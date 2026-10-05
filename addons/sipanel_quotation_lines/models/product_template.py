# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    sipanel_installation_base = fields.Boolean(
        string='Installation base', default=False, tracking=True,
        help="Lines of this product are part of the base of the quotation's Installation / Execution "
             "percentage. Crane, transport, rental and other services stay out unless flagged here.")
