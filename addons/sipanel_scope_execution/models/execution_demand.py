# -*- coding: utf-8 -*-
"""Execution demand (GAP-D03, D07, D08; C8-D02, C8-D04)."""
from odoo import api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import EXECUTION_MODE, guard, sha256_of

# Process-local guard opened only by the genuine execution engine (release,
# amendment delta, governed cancellation). A raw context flag, a guessed token,
# sudo() or an import context never opens it (STEP 2C-HARDENING, finding 1).
DEMAND_ENGINE_GUARD = 'sipanel_demand_engine'

# Provenance and ownership: fixed at creation, never writable afterwards - not
# even by the engine. A change of any of these is a new demand (a delta).
DEMAND_IMMUTABLE_FIELDS = (
    'batch_id', 'quote_scope_id', 'component_id', 'delta_uid', 'execution_mode', 'owner', 'demand_key',
    'normalized_qty', 'signed_qty', 'uom_id', 'product_id', 'project_id', 'system_id', 'activity_id',
    'reversal_of_id', 'cancelled_by_delta_uid',
)


class SipanelExecutionDemand(models.Model):
    _name = 'sipanel.execution.demand'
    _description = 'SIPANEL execution demand'
    _order = 'id'

    name = fields.Char(compute='_compute_name', store=True)
    batch_id = fields.Many2one('sipanel.execution.batch', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='batch_id.company_id', store=True, index=True)
    order_id = fields.Many2one(related='batch_id.order_id', store=True)
    quote_scope_id = fields.Many2one('sipanel.quote.scope', readonly=True, ondelete='restrict', index=True)
    component_id = fields.Many2one('sipanel.quote.scope.component', required=True, readonly=True, ondelete='restrict', index=True)
    delta_uid = fields.Char(required=True, readonly=True)
    execution_mode = fields.Selection(EXECUTION_MODE, required=True, readonly=True)
    owner = fields.Selection([('native_line_owner', 'NATIVE_LINE_OWNER'), ('component_bridge_owner', 'COMPONENT_BRIDGE_OWNER')], required=True, readonly=True)
    demand_key = fields.Char(required=True, readonly=True, index=True)
    normalized_qty = fields.Float(digits=(16, 6), required=True, readonly=True)
    uom_id = fields.Many2one('uom.uom', required=True, readonly=True, ondelete='restrict')
    product_id = fields.Many2one('product.product', readonly=True, ondelete='restrict')
    project_id = fields.Many2one('project.project', readonly=True, ondelete='restrict')
    system_id = fields.Many2one('account.analytic.account', readonly=True, ondelete='restrict')
    activity_id = fields.Many2one('account.analytic.account', readonly=True, ondelete='restrict')
    requested_date = fields.Date()
    state = fields.Selection([('planned', 'Planned'), ('linked', 'Linked'), ('created', 'Created'), ('in_progress', 'In progress'),
                              ('fulfilled', 'Fulfilled'), ('cancelled', 'Cancelled'), ('failed', 'Failed')], required=True, default='planned', readonly=True)
    reversal_required = fields.Boolean(readonly=True)
    cancelled_by_delta_uid = fields.Char(readonly=True)
    reversal_of_id = fields.Many2one('sipanel.execution.demand', readonly=True, ondelete='restrict')
    target_ids = fields.One2many('sipanel.execution.target', 'demand_id')
    target_count = fields.Integer(compute='_compute_target_count')
    signed_qty = fields.Float(digits=(16, 6), readonly=True, help="Negative for cancel deltas.")

    # One LIVE demand per (occurrence, delta, mode, owner) (C8-D02). A demand that
    # belongs to a FAILED batch is retained as evidence but must not occupy the key:
    # otherwise the retry after the cause is fixed skips every component as "already
    # demanded" and produces a released batch with no demand and no document
    # (STEP 2C defect CD-2C-01).
    _demand_key_live_unique = models.UniqueIndex("(demand_key) WHERE state <> 'failed'")

    @api.model
    def _live_by_key(self, demand_key):
        """The live demand holding this key, if any (failed demands never count)."""
        return self.search([('demand_key', '=', demand_key), ('state', '!=', 'failed')], limit=1)

    @api.depends('component_id.name', 'execution_mode')
    def _compute_name(self):
        for d in self:
            d.name = f"{d.component_id.name or '?'} [{d.execution_mode}]"

    @api.depends('target_ids')
    def _compute_target_count(self):
        for d in self:
            d.target_count = len(d.target_ids)

    # ------------------------------------------------------------- behavioural immutability
    def _sipanel_engine_guarded(self):
        return guard(self.env, DEMAND_ENGINE_GUARD)

    @api.model_create_multi
    def create(self, vals_list):
        if not self._sipanel_engine_guarded():
            raise AccessError(self.env._(
                "Execution demands are created only by Release Execution or an amendment delta; "
                "direct creation (including sudo, import or a context flag) is refused."))
        return super().create(vals_list)

    def write(self, vals):
        frozen = sorted(f for f in vals if f in DEMAND_IMMUTABLE_FIELDS)
        if frozen:
            raise AccessError(self.env._(
                "Execution demand provenance is immutable after creation (%s). A change of scope, "
                "quantity or owner is a new delta demand.", ', '.join(frozen)))
        if not self._sipanel_engine_guarded():
            raise AccessError(self.env._(
                "Execution demand state changes only through governed execution actions "
                "(release, failure, cancellation, amendment); direct writes are refused."))
        return super().write(vals)

    def unlink(self):
        raise AccessError(self.env._("Execution demands are lineage evidence and are never deleted."))

    @api.model
    def _make_key(self, occurrence_uid, delta_uid, mode, owner):
        return sha256_of([occurrence_uid, delta_uid, mode, owner])

    @api.model
    def _prepare_from_component(self, batch, comp, scope, delta_uid, qty=None):
        owner = comp.execution_owner if comp.execution_owner in ('native_line_owner', 'component_bridge_owner') else 'component_bridge_owner'
        q = comp.final_qty if qty is None else qty
        return {
            'batch_id': batch.id, 'quote_scope_id': scope.id, 'component_id': comp.id, 'delta_uid': delta_uid,
            'execution_mode': comp.execution_mode, 'owner': owner,
            'demand_key': self._make_key(comp.occurrence_uid, delta_uid, comp.execution_mode, owner),
            'normalized_qty': abs(q), 'signed_qty': q, 'uom_id': comp.uom_id.id, 'product_id': comp.product_id.id,
            'project_id': (scope.project_id or self.env['sipanel.config'].default_project()).id or False,
            'system_id': (comp.system_id or scope.system_id).id or False, 'activity_id': comp.activity_id.id or False,
        }

    @api.model
    def _preflight_component(self, comp, scope):
        """Master C8 preflight. Returns list of issue strings (empty = OK)."""
        _ = self.env._
        issues = []
        if comp.kind == 'estimate_only' or comp.resolution_state == 'open':
            issues.append(_("%s: ESTIMATE_ONLY / unresolved component cannot be released (PT-12).", comp.display_name))
        if comp.execution_mode == 'no_action':
            if not comp.no_action_reason:
                issues.append(_("%s: NO_ACTION without reason.", comp.display_name))
            return issues
        if not comp.product_id:
            issues.append(_("%s: product missing.", comp.display_name))
        if comp.final_qty <= 0:
            issues.append(_("%s: quantity must be > 0 to execute.", comp.display_name))
        if not comp.activity_id:
            issues.append(_("%s: Activity missing.", comp.display_name))
        if not (comp.system_id or scope.system_id):
            issues.append(_("%s: System missing.", comp.display_name))
        if not (scope.project_id or self.env['sipanel.config'].default_project()):
            issues.append(_("%s: Project missing (scope project or default).", comp.display_name))
        if comp.product_id and comp.product_id.company_id and comp.product_id.company_id != scope.company_id:
            issues.append(_("%s: product company mismatch.", comp.display_name))
        open_targets = self.env['sipanel.execution.target'].search_count([
            ('demand_id.component_id.occurrence_uid', '=', comp.occurrence_uid), ('demand_id.state', 'not in', ('cancelled', 'failed')),
            ('demand_id.execution_mode', '=', comp.execution_mode), ('demand_id.delta_uid', '=', scope.accepted_revision_id.acceptance_reference or f"rev:{scope.accepted_revision_id.id}")])
        if open_targets:
            issues.append(_("%s: already linked to an open target (no duplicate demand, PT-13).", comp.display_name))
        return issues
