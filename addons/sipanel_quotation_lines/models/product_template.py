# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    sipanel_installation_base = fields.Boolean(
        string='Installation base', default=False, tracking=True,
        help="Lines of this product are part of the base of the quotation's Installation / Execution "
             "percentage. Crane, transport, rental and other services stay out unless flagged here.")

    # AM-07 / R-DC1 (owner decision 2026-10-06): installation WORK, explicitly - not every labour component
    # (site survey, engineering, supervision are labour but not installation).
    sipanel_installation_work = fields.Boolean(
        string='Installation work', default=False, tracking=True,
        help="This product IS installation / execution work. A Scope whose anchor is in the installation base "
             "cannot be released with a SIPANEL component of this product, and a quotation carrying such a "
             "Scope refuses the Installation / Execution percentage (it would charge installation twice). "
             "The installation products mapped on SIPANEL Systems count as installation work automatically.")


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _sipanel_installation_work_products(self):
        """Installation work = products flagged `sipanel_installation_work` + every System-mapped installation
        product (e.g. SIP-000075), archived ones included."""
        flagged = self.sudo().with_context(active_test=False).search([('sipanel_installation_work', '=', True)])
        mapped = self.env['account.analytic.account'].sudo().with_context(active_test=False).search(
            [('sipanel_installation_product_id', '!=', False)]).mapped('sipanel_installation_product_id')
        return flagged | mapped
