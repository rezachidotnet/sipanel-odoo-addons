# -*- coding: utf-8 -*-
from odoo import models


class SipanelScopeVersion(models.Model):
    _inherit = 'sipanel.scope.version'

    def _resolve_owner_mode_hook(self):
        self.ensure_one()
        if not self.anchor_product_id:
            return None
        return self.env['sipanel.execution.owner.rule'].resolve(self.anchor_product_id, self.company_id) or None
