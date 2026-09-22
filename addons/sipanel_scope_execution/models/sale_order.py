# -*- coding: utf-8 -*-
"""Explicit Release Execution action and amendment/cancel lineage (GAP-D02, D07)."""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard_ctx

from .execution_demand import DEMAND_ENGINE_GUARD


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sipanel_execution_batch_ids = fields.One2many('sipanel.execution.batch', 'order_id')
    sipanel_batch_count = fields.Integer(compute='_compute_sipanel_batch_count')

    @api.depends('sipanel_execution_batch_ids')
    def _compute_sipanel_batch_count(self):
        for o in self:
            o.sipanel_batch_count = len(o.sipanel_execution_batch_ids)

    def action_sipanel_release_execution(self):
        self.ensure_one()
        if not self.env.user.has_group('sipanel_scope_execution.group_scope_execution_owner'):
            raise UserError(self.env._("Only Execution Owners may release execution."))
        batch = self.env['sipanel.execution.batch'].release_for_order(self)
        return {'type': 'ir.actions.act_window', 'res_model': 'sipanel.execution.batch', 'res_id': batch.id, 'view_mode': 'form'}

    def action_sipanel_release_amendment_delta(self):
        """Compute per-occurrence deltas between the last released quantities and the new accepted revision (PT-22)."""
        self.ensure_one()
        eng = self.with_context(**guard_ctx(DEMAND_ENGINE_GUARD))
        Demand = eng.env['sipanel.execution.demand']
        Batch = eng.env['sipanel.execution.batch']
        created = Demand
        for scope in self.sipanel_quote_scope_ids.filtered('active'):
            rev = scope.accepted_revision_id
            if not rev:
                continue
            for c in rev.component_ids.filtered(lambda c: c.eligible_for_rollup and c.qty_kind == 'physical' and c.execution_mode != 'no_action'):
                released = sum(Demand.search([('component_id.occurrence_uid', '=', c.occurrence_uid), ('quote_scope_id', '=', scope.id),
                                              ('execution_mode', '=', c.execution_mode), ('state', 'not in', ('cancelled', 'failed'))]).mapped('signed_qty'))
                delta = c.final_qty - released
                if abs(delta) < 1e-6:
                    continue
                d_uid = f"amend:{rev.id}"
                batch = Batch.search([('order_id', '=', self.id), ('revision_set_hash', '=', d_uid)], limit=1) or Batch.create({
                    'order_id': self.id, 'accepted_revision_ids': [(6, 0, rev.ids)], 'revision_set_hash': d_uid, 'state': 'validated'})
                vals = Demand._prepare_from_component(batch, c, scope, d_uid, qty=delta)
                if Demand._live_by_key(vals['demand_key']):
                    continue
                prior = Demand
                if delta < 0:
                    prior = Demand.search([('component_id.occurrence_uid', '=', c.occurrence_uid), ('quote_scope_id', '=', scope.id), ('signed_qty', '>', 0),
                                           ('state', 'not in', ('cancelled', 'failed'))], order='id desc', limit=1)
                    # lineage is provenance: fixed at creation, never written afterwards
                    vals.update({'reversal_of_id': prior.id or False, 'cancelled_by_delta_uid': d_uid})
                d = Demand.create(vals)
                if delta > 0:
                    eng.env['sipanel.execution.adapter'].create_or_link(d)
                elif prior:
                    eng.env['sipanel.execution.adapter'].reduce_planned(prior, -delta)
                created |= d
                batch.write({'state': 'released', 'released_by_id': self.env.uid, 'released_date': fields.Datetime.now()})
        return created

    def _action_cancel(self):
        """Governed order cancellation (STEP 2C-HARDENING finding 4).

        The user must hold the native permission to cancel this order (ACL and
        record rules on sale.order, checked here before anything else). Only
        then does the internal service transition the demands of exactly this
        order, as sudo with the engine token; the initiating user stays the
        actor of the audit event because sudo() keeps env.uid. Sales users get
        no general access to execution demands.
        """
        Adapter = self.env['sipanel.execution.adapter']
        for o in self:
            o.check_access('write')
            targets = self.env['sipanel.execution.target'].sudo().search([('demand_id.order_id', '=', o.id)])
            # executed documents SIPANEL created itself block a plain order cancel; native-owned
            # documents are the native line's responsibility and are only observed
            done = targets.filtered(lambda t: t.link_kind == 'created' and t.target_record().exists()
                                    and Adapter._target_executed(t, t.target_record()))
            if done:
                raise UserError(self.env._("Order %s has executed (done) targets; cancel through native returns/reversals, not order cancel.", o.name))
            batches = o.sipanel_execution_batch_ids.filtered(lambda b: b.state in ('released', 'validated', 'planned'))
            if batches:
                batches.sudo().action_cancel_planned()
        return super()._action_cancel()
