# -*- coding: utf-8 -*-
"""A Scope-generated (separately billable) line carries the native multiline sale description (A).

The projection names the line with the frozen customer label only, bypassing the product's
description_sale that Odoo appends to every manually selected product. The label stays the first line
(the item title); description_sale follows on the next lines, read in the quotation's snapshot language.
The text is refreshed only while the revision is WORKING - a sealed projection is frozen by
sipanel_sale_scope and is never rewritten. The anchor line keeps the governed Scope note (label,
version customer description, bullets): that note is sealed content and is not touched here.
"""
from odoo import models


class SipanelQuoteScopeRevision(models.Model):
    _inherit = 'sipanel.quote.scope.revision'

    def _projected_line_vals(self, component, key):
        vals = super()._projected_line_vals(component, key)
        lang = self.resolved_language or self.language or 'en_US'
        description = component.product_id.product_tmpl_id.with_context(lang=lang).description_sale
        if description and description.strip():
            vals['name'] = f"{vals.get('name') or ''}\n{description.strip()}".lstrip('\n')
        return vals
