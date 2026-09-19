# -*- coding: utf-8 -*-
"""Personal favorites resolving to the current released version (GAP-A12, C4-D03)."""
from odoo import fields, models


class SipanelScopeFavorite(models.Model):
    _name = 'sipanel.scope.favorite'
    _description = 'SIPANEL personal scope favorite'

    user_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.uid, ondelete='cascade', index=True)
    scope_id = fields.Many2one('sipanel.scope', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='scope_id.company_id', store=True)
    current_version_id = fields.Many2one(related='scope_id.current_version_id')

    _user_scope_unique = models.Constraint('UNIQUE(user_id, scope_id)', 'Already a favorite.')
