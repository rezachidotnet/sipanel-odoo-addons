# -*- coding: utf-8 -*-
"""Scope Version release rules for the installation line (AM-07 / R-DC1, owner decision 2026-10-06).

QL1 (block) - the anchor product is in the installation base AND the recipe has a SIPANEL component of
              installation work (System-mapped installation product or `sipanel_installation_work`), in any
              placement: installation would be priced inside the anchor and again by the percentage line.
QL2 (warn)  - the anchor is in the installation base and the customer label / description mentions
              installation (English or Persian keywords). Text only, so a warning, never a refusal; the
              Standing Seam v3 master script keeps its own refusal.
The quotation-time refusal (sale.order._sipanel_check_installation_not_in_scope) stays the second guard.
"""
import re

from odoo import models

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import stored_translations

INSTALLATION_WORDING = re.compile(r'install|erection|mounting|نصب|اجرا|مونتاژ', re.IGNORECASE)


class SipanelScopeVersion(models.Model):
    _inherit = 'sipanel.scope.version'

    def _release_validations(self):
        issues = super()._release_validations()
        anchor = self.anchor_product_id
        if not (anchor and anchor.product_tmpl_id.sipanel_installation_base):
            return issues
        _ = self.env._
        work = self.env['product.product']._sipanel_installation_work_products()
        for line in self.recipe_line_ids.filtered(lambda l: l.responsibility == 'sipanel' and l.product_id in work):
            issues.append({'rule': 'QL1', 'level': 'block', 'msg': _(
                "Anchor %(a)s is in the installation base and recipe line %(l)s is installation work "
                "(%(p)s, placement %(pl)s): installation would be charged twice. Remove the line from the recipe "
                "(installation is quoted on the Installation / Execution line) or set it to customer "
                "responsibility.", a=anchor.display_name, l=line.display_name, p=line.product_id.display_name,
                pl=line.placement)})
        for field_name in ('customer_label', 'customer_description'):
            for lang, term in sorted(stored_translations(self, field_name).items()):
                hit = INSTALLATION_WORDING.search(term or '')
                if hit:
                    issues.append({'rule': 'QL2', 'level': 'warn', 'msg': _(
                        "Anchor %(a)s is in the installation base but the %(f)s (%(lang)s) mentions installation "
                        "(\"%(w)s\"). Check that the text does not promise installation inside this price.",
                        a=anchor.display_name, f=field_name.replace('_', ' '), lang=lang, w=hit.group(0))})
        return issues
