# -*- coding: utf-8 -*-
"""Sealed customer artifact (GAP-B16, C7-D04). Append-only."""
from odoo import fields, models
from odoo.exceptions import UserError


class SipanelQuoteScopeArtifact(models.Model):
    _name = 'sipanel.quote.scope.artifact'
    _description = 'SIPANEL sealed customer artifact'
    _order = 'sent_date desc, id desc'

    revision_id = fields.Many2one('sipanel.quote.scope.revision', required=True, readonly=True, ondelete='restrict', index=True)
    quote_scope_id = fields.Many2one(related='revision_id.quote_scope_id', store=True)
    order_id = fields.Many2one(related='revision_id.order_id', store=True)
    company_id = fields.Many2one(related='revision_id.company_id', store=True)
    kind = fields.Selection([('pdf', 'PDF'), ('portal_html', 'Portal HTML'), ('text', 'Text')], required=True, readonly=True)
    language = fields.Char(required=True, readonly=True)
    attachment_id = fields.Many2one('ir.attachment', readonly=True, ondelete='restrict')
    content_text = fields.Text(readonly=True)
    content_hash = fields.Char(required=True, readonly=True)
    amount_untaxed = fields.Monetary(currency_field='currency_id', readonly=True)
    amount_total = fields.Monetary(currency_field='currency_id', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    sent_date = fields.Datetime(required=True, readonly=True)
    sent_by_id = fields.Many2one('res.users', readonly=True)
    acceptance_reference = fields.Char(readonly=True)

    def write(self, vals):
        if set(vals) - {'acceptance_reference'}:
            raise UserError(self.env._("Sealed artifacts are append-only."))
        return super().write(vals)

    def unlink(self):
        raise UserError(self.env._("Sealed artifacts cannot be deleted."))
