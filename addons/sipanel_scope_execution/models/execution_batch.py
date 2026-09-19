# -*- coding: utf-8 -*-
"""Release Execution batch (GAP-D02, D03, D04, D06; C8-D01, C8-D02, SV-07)."""
import time
import uuid

import psycopg2

from odoo import api, fields, models
from odoo.exceptions import LockError, UserError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import sha256_of


class SipanelExecutionBatch(models.Model):
    _name = 'sipanel.execution.batch'
    _description = 'SIPANEL release execution batch'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(compute='_compute_name', store=True)
    order_id = fields.Many2one('sale.order', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='order_id.company_id', store=True, index=True)
    accepted_revision_ids = fields.Many2many('sipanel.quote.scope.revision', 'sipanel_batch_revision_rel', 'batch_id', 'revision_id', readonly=True)
    action_uid = fields.Char(required=True, readonly=True, default=lambda self: str(uuid.uuid4()))
    revision_set_hash = fields.Char(required=True, readonly=True)
    state = fields.Selection([('planned', 'Planned'), ('validated', 'Validated'), ('released', 'Released'), ('failed', 'Failed'), ('cancelled', 'Cancelled')],
                             required=True, default='planned', readonly=True, tracking=True)
    requested_by_id = fields.Many2one('res.users', readonly=True, default=lambda self: self.env.uid)
    requested_date = fields.Datetime(readonly=True, default=fields.Datetime.now)
    released_by_id = fields.Many2one('res.users', readonly=True)
    released_date = fields.Datetime(readonly=True)
    error_summary = fields.Text(readonly=True)
    retry_count = fields.Integer(readonly=True)
    demand_ids = fields.One2many('sipanel.execution.demand', 'batch_id')
    demand_count = fields.Integer(compute='_compute_counts')

    _batch_key_unique = models.Constraint('UNIQUE(order_id, revision_set_hash, action_uid)', 'Batch key must be unique (C8-D02).')

    @api.depends('order_id.name')
    def _compute_name(self):
        for b in self:
            b.name = f"REL/{b.order_id.name or '?'}/{b.id or 0}"

    @api.depends('demand_ids')
    def _compute_counts(self):
        for b in self:
            b.demand_count = len(b.demand_ids)

    # ------------------------------------------------------------- release entry point
    @api.model
    def release_for_order(self, order, delta_uid=None):
        """Bounded, idempotent release. Two concurrent clicks => one batch; the loser returns the winner's links (PT-14)."""
        _ = self.env._
        Config = self.env['sipanel.config']
        max_attempts = Config.release_retry_count()
        backoff = Config.release_backoff_ms() / 1000.0
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                order.lock_for_update()
            except LockError as e:
                last_error = e
                existing = self._find_existing(order)
                if existing:
                    return existing
                if attempt < max_attempts and backoff:
                    time.sleep(backoff * attempt)
                continue
            existing = self._find_existing(order)
            if existing:
                existing.write({'retry_count': existing.retry_count + (attempt - 1)})
                return existing
            try:
                return self._release_locked(order, delta_uid=delta_uid)
            except psycopg2.IntegrityError as e:  # unique demand/batch key won by a concurrent transaction
                last_error = e
                self.env.invalidate_all()
                existing = self._find_existing(order)
                if existing:
                    return existing
                if attempt < max_attempts and backoff:
                    time.sleep(backoff * attempt)
        raise UserError(_("Release still in progress; retry exhausted after %(n)s attempt(s). (%(e)s)", n=max_attempts, e=last_error or ''))

    def _find_existing(self, order):
        revs = order.sipanel_quote_scope_ids.filtered('active').mapped('accepted_revision_id')
        h = sha256_of(sorted(revs.ids))
        return self.search([('order_id', '=', order.id), ('revision_set_hash', '=', h), ('state', 'in', ('released', 'planned', 'validated'))], limit=1)

    def _release_locked(self, order, delta_uid=None):
        _ = self.env._
        if order.state != 'sale':
            raise UserError(_("Order %s must be confirmed before Release Execution.", order.name))
        scopes = order.sipanel_quote_scope_ids.filtered('active')
        revs = scopes.mapped('accepted_revision_id')
        if not revs or any(not s.accepted_revision_id for s in scopes):
            raise UserError(_("Every Scope needs an ACCEPTED_SEALED revision before release."))
        batch = self.create({'order_id': order.id, 'accepted_revision_ids': [(6, 0, revs.ids)], 'revision_set_hash': sha256_of(sorted(revs.ids))})
        Demand = self.env['sipanel.execution.demand']
        issues = []
        demands = Demand
        with self.env.cr.savepoint():
            for scope in scopes:
                rev = scope.accepted_revision_id
                for c in rev.component_ids.filtered(lambda c: c.eligible_for_rollup and c.qty_kind == 'physical'):
                    issues += Demand._preflight_component(c, scope)
                    if c.execution_mode in ('no_action',):
                        continue
                    d_uid = delta_uid or rev.acceptance_reference or f"rev:{rev.id}"
                    vals = Demand._prepare_from_component(batch, c, scope, d_uid)
                    if Demand.search([('demand_key', '=', vals['demand_key'])], limit=1):
                        continue  # already demanded (idempotent by key)
                    demands |= Demand.create(vals)
            self.env.flush_all()  # unique keys are checked here (IntegrityError => caller retries / returns existing)
        if issues:
            batch.write({'state': 'failed', 'error_summary': '\n'.join(issues)})
            raise UserError(_("Release preflight failed:\n%s", '\n'.join('- ' + i for i in issues)))
        batch.write({'state': 'validated'})
        # adapters run inside one savepoint: any failure rolls back everything created by this batch (PT-15)
        try:
            with self.env.cr.savepoint():
                for d in demands:
                    self.env['sipanel.execution.adapter'].create_or_link(d)
                batch.write({'state': 'released', 'released_by_id': self.env.uid, 'released_date': fields.Datetime.now()})
        except UserError as e:
            demands.sudo().write({'state': 'failed'})
            batch.write({'state': 'failed', 'error_summary': self._redact(str(e))})
            raise UserError(_("Release failed and was rolled back: %s", self._redact(str(e))))
        self.env['sipanel.scope.audit.event'].log(batch, 'release_execution', after={'demands': len(demands), 'revision_set_hash': batch.revision_set_hash},
                                                  correlation_uid=batch.action_uid)
        return batch

    @api.model
    def _redact(self, text):
        """No vendor/contact data in error summaries (C8-D02)."""
        import re
        text = re.sub(r'[\w.+-]+@[\w-]+\.[\w.]+', '<email>', text)
        text = re.sub(r'\+?\d[\d\s-]{6,}\d', '<number>', text)
        return text[:2000]

    def action_cancel_planned(self):
        for b in self:
            for d in b.demand_ids:
                self.env['sipanel.execution.adapter'].cancel_delta(d)
            b.write({'state': 'cancelled'})
        return True
