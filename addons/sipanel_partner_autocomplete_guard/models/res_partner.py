from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def autocomplete_by_name(self, query, query_country_id, timeout=15):
        """Return no external suggestions without contacting Odoo IAP."""
        return []
