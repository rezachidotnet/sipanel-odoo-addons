# -*- coding: utf-8 -*-
"""Scope identity (GAP-A01, C1-D01, C1-D07, C1-D08)."""
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError
from .sipanel_tools import guard, guard_ctx


class SipanelScope(models.Model):
    _name = 'sipanel.scope'
    _description = 'SIPANEL Commercial Scope identity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code'
    _check_company_auto = True

    code = fields.Char(required=True, index=True, tracking=True, copy=False,
                       help="Non-semantic identity code. Never a product default_code.")
    name = fields.Char(required=True, tracking=True, help="Internal name; never a customer-facing fallback.")
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='restrict',
                                 default=lambda self: self.env.company)
    owner_user_id = fields.Many2one('res.users', string='Steward', tracking=True)
    uid_key = fields.Char(required=True, readonly=True, copy=False, default=lambda self: str(uuid.uuid4()))
    current_version_id = fields.Many2one('sipanel.scope.version', readonly=True, copy=False, ondelete='restrict',
                                         help="RELEASED version; written only by the release transaction.")
    version_ids = fields.One2many('sipanel.scope.version', 'scope_id')
    version_count = fields.Integer(compute='_compute_version_count')
    active = fields.Boolean(default=True, tracking=True)
    duplicated_from_id = fields.Many2one('sipanel.scope', readonly=True, copy=False, ondelete='restrict')
    usage_count = fields.Integer(compute='_compute_usage_count',
                                 help="Quote scopes referencing this identity that are visible to you (ACL-scoped).")
    is_favorite = fields.Boolean(compute='_compute_is_favorite', inverse='_inverse_is_favorite')

    _code_company_unique = models.Constraint('UNIQUE(company_id, code)', 'Scope code must be unique per company.')
    _uid_key_unique = models.Constraint('UNIQUE(uid_key)', 'Scope key must be unique.')

    @api.depends('version_ids')
    def _compute_version_count(self):
        for scope in self:
            scope.version_count = len(scope.version_ids)

    def _compute_usage_count(self):
        QuoteScope = self.env['sipanel.quote.scope'] if 'sipanel.quote.scope' in self.env else None
        for scope in self:
            if QuoteScope is None:
                scope.usage_count = 0
            else:
                # ACL-scoped on purpose (C1-D08): never reveals unauthorized documents.
                scope.usage_count = QuoteScope.search_count([('source_scope_id', '=', scope.id)])

    def _compute_is_favorite(self):
        favs = self.env['sipanel.scope.favorite'].search([('user_id', '=', self.env.uid), ('scope_id', 'in', self.ids)])
        fav_ids = set(favs.mapped('scope_id').ids)
        for scope in self:
            scope.is_favorite = scope.id in fav_ids

    def _inverse_is_favorite(self):
        Fav = self.env['sipanel.scope.favorite']
        for scope in self:
            existing = Fav.search([('user_id', '=', self.env.uid), ('scope_id', '=', scope.id)])
            if scope.is_favorite and not existing:
                Fav.create({'user_id': self.env.uid, 'scope_id': scope.id})
            elif not scope.is_favorite and existing:
                existing.unlink()

    @api.ondelete(at_uninstall=False)
    def _unlink_except_used(self):
        for scope in self:
            if scope.version_ids.filtered(lambda v: v.state != 'draft'):
                raise UserError(self.env._("Scope %s has released history and cannot be deleted; archive it instead.", scope.code))
            if scope.usage_count:
                raise UserError(self.env._("Scope %s is referenced by quotations and cannot be deleted; archive it instead.", scope.code))

    def copy(self, default=None):
        raise UserError(self.env._("Use 'Duplicate as new Scope' or 'New version' (C1-D07)."))

    def action_new_version(self):
        self.ensure_one()
        source = self.current_version_id or self.version_ids.sorted('revision')[-1:]
        if not source:
            return self.env['sipanel.scope.version'].create({'scope_id': self.id})._action_open()
        return source.action_new_version()

    def action_duplicate_as_new_scope(self, code=None, name=None):
        self.ensure_one()
        new = self.with_context(**guard_ctx('sipanel_allow_copy')).env['sipanel.scope'].create({
            'code': code or self.env._("%s-COPY", self.code),
            'name': name or self.name,
            'company_id': self.company_id.id,
            'owner_user_id': self.owner_user_id.id,
            'duplicated_from_id': self.id,
        })
        source = self.current_version_id or self.version_ids.sorted('revision')[-1:]
        if source:
            source._copy_content_to(new)
        self.env['sipanel.scope.audit.event'].log(new, 'duplicate_scope', after={'from_scope_id': self.id})
        return new._action_open()

    def _action_open(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'current',
        }

    def action_open_versions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.env._('Versions'),
            'res_model': 'sipanel.scope.version', 'view_mode': 'list,form',
            'domain': [('scope_id', '=', self.id)], 'context': {'default_scope_id': self.id},
        }
