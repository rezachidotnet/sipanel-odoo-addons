# -*- coding: utf-8 -*-
"""Append-only application audit (GAP-A13, C4-D04, GAP-S05)."""
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError


class SipanelScopeAuditEvent(models.Model):
    _name = 'sipanel.scope.audit.event'
    _description = 'SIPANEL audit event (append-only)'
    _order = 'event_date desc, id desc'

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True,
                                 default=lambda self: self.env.company)
    res_model = fields.Char(required=True, readonly=True, index=True)
    res_id = fields.Integer(required=True, readonly=True, index=True)
    action = fields.Char(required=True, readonly=True, index=True)
    actor_user_id = fields.Many2one('res.users', required=True, readonly=True, default=lambda self: self.env.user)
    event_date = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)
    before_json = fields.Json(readonly=True, groups='sipanel_commercial_scope_core.group_scope_cost_viewer,sipanel_commercial_scope_core.group_scope_auditor')
    after_json = fields.Json(readonly=True, groups='sipanel_commercial_scope_core.group_scope_cost_viewer,sipanel_commercial_scope_core.group_scope_auditor')
    reason = fields.Text(readonly=True)
    revision_ref = fields.Char(readonly=True)
    correlation_uid = fields.Char(required=True, readonly=True, default=lambda self: str(uuid.uuid4()), index=True)
    summary = fields.Char(readonly=True)

    @api.model
    def log(self, record, action, before=None, after=None, reason=None, revision_ref=None,
            correlation_uid=None, summary=None):
        """Write one audit row as sudo (the acting user is recorded in actor_user_id)."""
        company = record.company_id if 'company_id' in record._fields and record.company_id else self.env.company
        vals = {
            'company_id': company.id,
            'res_model': record._name,
            'res_id': record.id,
            'action': action,
            'actor_user_id': self.env.uid,
            'before_json': before,
            'after_json': after,
            'reason': reason,
            'revision_ref': revision_ref,
            'summary': summary,
        }
        if correlation_uid:
            vals['correlation_uid'] = correlation_uid
        return self.sudo().create(vals)

    def write(self, vals):
        raise UserError(self.env._("Audit events are append-only and cannot be modified."))

    def unlink(self):
        raise UserError(self.env._("Audit events are append-only and cannot be deleted."))
