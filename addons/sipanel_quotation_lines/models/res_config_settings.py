# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sipanel_installation_pct_default = fields.Float(
        related='company_id.sipanel_installation_pct_default', readonly=False)
