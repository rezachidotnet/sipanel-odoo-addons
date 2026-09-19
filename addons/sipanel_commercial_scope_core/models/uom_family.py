# -*- coding: utf-8 -*-
"""Dimensional UoM family contract (GAP-A07, C1-D04, SV-10).

The installed uom.uom has no category; conversion is only a factor chain. The
engine therefore tags each UoM used by Scope/Recipe with a dimensional family
and refuses conversions across families, before calling the native
`_compute_quantity`.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .sipanel_tools import DIMENSION_FAMILY


class SipanelUomFamily(models.Model):
    _name = 'sipanel.uom.family'
    _description = 'SIPANEL dimensional family of a unit of measure'
    _rec_name = 'uom_id'

    uom_id = fields.Many2one('uom.uom', required=True, ondelete='restrict', index=True)
    family = fields.Selection(DIMENSION_FAMILY, required=True)
    note = fields.Char()

    _uom_unique = models.Constraint('UNIQUE(uom_id)', 'A unit of measure has exactly one dimensional family.')

    @api.model
    def family_of(self, uom):
        """Return the family tag of a uom or False. Walks the relative_uom_id chain."""
        if not uom:
            return False
        seen = set()
        current = uom
        while current and current.id not in seen:
            seen.add(current.id)
            row = self.search([('uom_id', '=', current.id)], limit=1)
            if row:
                return row.family
            current = current.relative_uom_id if 'relative_uom_id' in current._fields else False
        return False

    @api.model
    def check_compatible(self, uom_from, uom_to, raise_if_failure=True):
        """Same family and convertible by factor chain. Returns bool or raises."""
        if uom_from == uom_to:
            return True
        fam_a = self.family_of(uom_from)
        fam_b = self.family_of(uom_to)
        ok = bool(fam_a) and fam_a == fam_b
        if ok and hasattr(uom_from, '_has_common_reference'):
            ok = uom_from._has_common_reference(uom_to)
        if not ok and raise_if_failure:
            raise ValidationError(self.env._(
                "Units %(a)s and %(b)s are not dimensionally compatible (families %(fa)s / %(fb)s).",
                a=uom_from.display_name, b=uom_to.display_name, fa=fam_a or '?', fb=fam_b or '?'))
        return ok

    @api.model
    def convert(self, qty, uom_from, uom_to):
        """Family-checked conversion. No global rounding is applied (per-line rounding rules)."""
        if uom_from == uom_to or not uom_from or not uom_to:
            return qty
        self.check_compatible(uom_from, uom_to)
        return uom_from._compute_quantity(qty, uom_to, round=False, raise_if_failure=True)
