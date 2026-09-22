# -*- coding: utf-8 -*-
"""STEP 2C-HARDENING: behavioural immutability of execution-demand provenance, the
Native Owner boundary in cancellation/reduction, and governed Sale Order cancellation
without general demand write access."""
import inspect
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard_ctx
try:
    from odoo.addons.sipanel_scope_execution.models.execution_demand import DEMAND_ENGINE_GUARD, DEMAND_IMMUTABLE_FIELDS
except ImportError:  # pre-hardening source: lets the suite show per-test failures instead of an import error
    DEMAND_ENGINE_GUARD = 'sipanel_demand_engine'
    DEMAND_IMMUTABLE_FIELDS = ('batch_id', 'quote_scope_id', 'component_id', 'delta_uid', 'execution_mode', 'owner', 'demand_key',
                               'normalized_qty', 'signed_qty', 'uom_id', 'product_id', 'project_id', 'system_id', 'activity_id',
                               'reversal_of_id', 'cancelled_by_delta_uid')

from .common import SipanelExecutionCase


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_step2c_hardening')
class TestDemandImmutability(SipanelExecutionCase):

    def _released(self):
        order, scope, bracket = self._bridge_order_with_own_line()
        batch = self._release(order)
        self.assertEqual(batch.state, 'released')
        demand = self.env['sipanel.execution.demand'].search([('component_id', '=', bracket.id)])
        self.assertEqual(len(demand), 1)
        return order, scope, batch, demand

    def _value_of(self, demand, field):
        val = demand[field]
        return val.id if hasattr(val, 'id') else val

    def test_direct_demand_key_modification_is_refused_and_value_unchanged(self):
        order, scope, batch, d = self._released()
        key = d.demand_key
        for rs in (d.with_user(self.exec_owner), d.sudo(), d.with_context(**guard_ctx(DEMAND_ENGINE_GUARD))):
            with self.assertRaises(AccessError):
                rs.write({'demand_key': 'tampered'})
        self.env.invalidate_all()
        self.assertEqual(d.demand_key, key)
        self.assertEqual(self.env['sipanel.execution.demand'].search_count([('demand_key', '=', key)]), 1)

    def test_every_provenance_field_is_immutable(self):
        order, scope, batch, d = self._released()
        snapshot = {f: self._value_of(d, f) for f in DEMAND_IMMUTABLE_FIELDS}
        for f in DEMAND_IMMUTABLE_FIELDS:
            # even re-writing the SAME value is refused: the field is closed, not validated
            with self.assertRaises(AccessError, msg=f):
                d.with_user(self.exec_owner).write({f: snapshot[f]})
            with self.assertRaises(AccessError, msg=f):
                d.sudo().with_context(**guard_ctx(DEMAND_ENGINE_GUARD)).write({f: snapshot[f]})
        self.env.invalidate_all()
        self.assertEqual({f: self._value_of(d, f) for f in DEMAND_IMMUTABLE_FIELDS}, snapshot)

    def test_raw_context_flag_does_not_open_the_engine(self):
        order, scope, batch, d = self._released()
        with self.assertRaises(AccessError):
            d.with_user(self.exec_owner).with_context(sipanel_demand_engine=True).write({'state': 'cancelled'})
        self.assertEqual(d.state, 'created')

    def test_guessed_token_does_not_open_the_engine(self):
        order, scope, batch, d = self._released()
        with self.assertRaises(AccessError):
            d.with_user(self.exec_owner).with_context(sipanel_demand_engine=True, sipanel_guard_token='guess').write({'state': 'cancelled'})
        self.assertEqual(d.state, 'created')

    def test_sudo_does_not_open_the_engine(self):
        order, scope, batch, d = self._released()
        with self.assertRaises(AccessError):
            d.sudo().write({'state': 'cancelled'})
        with self.assertRaises(AccessError):
            d.sudo().write({'reversal_required': True})
        self.assertEqual(d.state, 'created')
        self.assertFalse(d.reversal_required)

    def test_import_context_does_not_open_the_engine(self):
        order, scope, batch, d = self._released()
        with self.assertRaises(AccessError):
            d.with_user(self.exec_owner).with_context(import_file=True).write({'state': 'cancelled'})
        with self.assertRaises(AccessError):
            d.sudo().with_context(import_file=True, sipanel_demand_engine=True).write({'state': 'cancelled'})
        self.assertEqual(d.state, 'created')

    def test_forged_demand_creation_is_refused(self):
        order, scope, batch, d = self._released()
        Demand = self.env['sipanel.execution.demand']
        rev = scope.accepted_revision_id
        comp = rev.component_ids.filtered(lambda c: c.product_id == self.p_screw)[:1]
        vals = Demand._prepare_from_component(batch, comp, scope, 'forged:1')
        n = Demand.search_count([])
        for rs in (Demand.with_user(self.exec_owner), Demand.sudo(),
                   Demand.with_user(self.exec_owner).with_context(sipanel_demand_engine=True),
                   Demand.sudo().with_context(sipanel_demand_engine=True, sipanel_guard_token='guess'),
                   Demand.sudo().with_context(import_file=True)):
            with self.assertRaises(AccessError):
                rs.create(dict(vals))
        self.assertEqual(Demand.search_count([]), n)

    def test_demands_are_never_deleted(self):
        order, scope, batch, d = self._released()
        for rs in (d.with_user(self.exec_owner), d.sudo(), d.sudo().with_context(**guard_ctx(DEMAND_ENGINE_GUARD))):
            with self.assertRaises(AccessError):
                rs.unlink()
        self.assertTrue(d.exists())

    def test_genuine_release_failure_retry_and_cancellation_still_work(self):
        order, scope, bracket = self._bridge_order_with_own_line()
        Demand = self.env['sipanel.execution.demand']
        self.env['product.supplierinfo'].search([('product_tmpl_id', '=', self.p_crane.product_tmpl_id.id)]).unlink()
        failed = self._release(order)
        self.assertEqual(failed.state, 'failed')
        self.assertTrue(failed.demand_ids and all(x.state == 'failed' for x in failed.demand_ids), 'genuine failure marks the demands failed')
        self.env['product.supplierinfo'].create({'partner_id': self.vendor.id, 'product_tmpl_id': self.p_crane.product_tmpl_id.id, 'price': 400.0, 'min_qty': 0})
        ok = self._release(order)
        self.assertEqual(ok.state, 'released')
        self.assertEqual(len(ok.demand_ids), 7, 'genuine retry creates the live demand set')
        for key in set(Demand.search([('order_id', '=', order.id)]).mapped('demand_key')):
            self.assertEqual(Demand.search_count([('demand_key', '=', key), ('state', '!=', 'failed')]), 1, 'one live demand per key (partial unique index)')
        self.assertEqual(self._release(order), ok, 'idempotent')
        ok.with_user(self.exec_owner).action_cancel_planned()
        self.assertTrue(all(x.state == 'cancelled' for x in ok.demand_ids), 'governed cancellation transitions the state')
        self.assertEqual(ok.state, 'cancelled')
        ev = self.env['sipanel.scope.audit.event'].sudo().search([('res_model', '=', 'sipanel.execution.batch'), ('res_id', '=', ok.id), ('action', '=', 'execution_cancel')])
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev.actor_user_id, self.exec_owner, 'the initiating user is the actor')


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_step2c_hardening')
class TestNativeOwnerBoundary(SipanelExecutionCase):

    def _bridge_released(self):
        order, scope, bracket = self._bridge_order_with_own_line()
        batch = self._release(order)
        by_mode = {d.execution_mode: d for d in batch.demand_ids if d.execution_mode != 'stock_issue'}
        by_mode['stock_issue'] = batch.demand_ids.filtered(lambda d: d.component_id == bracket)
        return order, scope, batch, by_mode

    def test_bridge_owned_cancel_withdraws_sipanel_documents_and_classifies_reversal(self):
        order, scope, batch, dm = self._bridge_released()
        move = dm['stock_issue'].target_ids.filtered(lambda t: t.target_model == 'stock.move').target_record()
        picking = dm['stock_issue'].target_ids.filtered(lambda t: t.target_model == 'stock.picking').target_record()
        pol = dm['equipment_service'].target_ids.target_record()
        mo = dm['manufacture'].target_ids.target_record()
        order.with_user(self.exec_owner).action_cancel()
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(move.state, 'cancel')
        self.assertEqual(picking.state, 'cancel')
        self.assertEqual(pol.product_qty, 0.0)
        self.assertEqual(mo.state, 'cancel')
        self.assertTrue(all(d.state == 'cancelled' for d in batch.demand_ids))
        # nothing executed: no reversal noise on the picking/move demand, nor on the linked project
        self.assertFalse(dm['stock_issue'].reversal_required)
        self.assertFalse(dm['labour'].reversal_required, 'a linked project has no reversible SIPANEL transaction')
        self.assertFalse(dm['equipment_service'].reversal_required)
        self.assertFalse(dm['manufacture'].reversal_required)
        self.assertTrue(all(t.exists() for t in batch.demand_ids.mapped('target_ids')), 'lineage retained')

    def test_native_owned_cancel_leaves_native_documents_untouched(self):
        order, scope, bracket = self._native_order_with_own_line()
        line = self._generated_line(bracket)
        native_move = line.move_ids
        task = scope.anchor_line_id.task_id
        batch = self._release(order)
        d = self.env['sipanel.execution.demand'].search([('component_id', '=', bracket.id)])
        self.assertEqual(d.owner, 'native_line_owner')
        move_state, move_qty, n_moves = native_move.state, native_move.product_uom_qty, self._docs(order)['moves']
        cancelled_calls = []
        orig = type(self.env['stock.move'])._action_cancel

        def spy(self_, *a, **kw):
            cancelled_calls.append([f.filename for f in inspect.stack()[1:6]])
            return orig(self_, *a, **kw)
        with patch.object(type(self.env['stock.move']), '_action_cancel', spy):
            batch.with_user(self.exec_owner).action_cancel_planned()
            batch.with_user(self.exec_owner).action_cancel_planned()   # repeated: idempotent
        self.assertFalse(cancelled_calls, 'SIPANEL never cancels a native-owned move')
        self.assertEqual(native_move.state, move_state)
        self.assertEqual(native_move.product_uom_qty, move_qty)
        self.assertTrue(task.exists())
        self.assertEqual(task.state, task.state)
        self.assertEqual(self._docs(order)['moves'], n_moves)
        self.assertEqual(d.state, 'cancelled')
        self.assertFalse(d.reversal_required, 'observed native document: nothing for SIPANEL to reverse')
        self.assertEqual(batch.state, 'cancelled')
        self.assertEqual(self.env['sipanel.scope.audit.event'].sudo().search_count(
            [('res_model', '=', 'sipanel.execution.batch'), ('res_id', '=', batch.id), ('action', '=', 'execution_cancel')]), 1,
            'the second cancellation performed nothing')
        # native cancellation stays native: cancelling the order lets Odoo cancel its own delivery
        order.with_user(self.exec_owner).action_cancel()
        self.assertEqual(native_move.state, 'cancel')
        self.p_anchor.write({'service_tracking': 'no'})

    def test_native_amendment_reduction_never_touches_native_documents(self):
        order, scope, bracket = self._native_order_with_own_line()
        batch = self._release(order)
        line_v1 = self._generated_line(bracket)
        qty_v1 = bracket.final_qty
        new_rev = scope.current_revision_id.action_amend()
        b2 = new_rev.component_ids.filtered(lambda c: c.product_id == self.p_bracket)
        b2.write({'qty_override': True, 'override_qty': qty_v1 - 10.0, 'override_reason': 'less'})
        scope.action_accept_change_order('CO-NATIVE-DOWN')
        line_v2 = self._generated_line(b2)
        # Odoo (the native owner) already re-shaped the delivery: old line 0 (move cancelled), new line qty - 10
        self.assertEqual(line_v1.product_uom_qty, 0.0)
        self.assertEqual(line_v2.product_uom_qty, qty_v1 - 10.0)
        self.assertEqual(line_v2.move_ids.product_uom_qty, qty_v1 - 10.0)
        calls = []
        orig_cancel = type(self.env['stock.move'])._action_cancel
        orig_write = type(self.env['stock.move']).write

        def spy_cancel(self_, *a, **kw):
            calls.append('cancel'); return orig_cancel(self_, *a, **kw)

        def spy_write(self_, vals):
            if 'product_uom_qty' in vals:
                calls.append('qty')
            return orig_write(self_, vals)
        with patch.object(type(self.env['stock.move']), '_action_cancel', spy_cancel), patch.object(type(self.env['stock.move']), 'write', spy_write):
            created = order.with_user(self.exec_owner).action_sipanel_release_amendment_delta()
        self.assertFalse(calls, 'the SIPANEL delta neither cancels nor reduces a native move')
        self.assertEqual(created.signed_qty, -10.0)
        self.assertEqual(created.reversal_of_id, batch.demand_ids.filtered(lambda d: d.component_id == bracket))
        self.assertFalse(created.target_ids)
        self.assertFalse(created.reversal_required)
        self.assertEqual(line_v2.move_ids.product_uom_qty, qty_v1 - 10.0)
        self.assertEqual(self.env['stock.move'].search_count([('product_id', '=', self.p_bracket.id), ('sale_line_id', 'in', (line_v1 | line_v2).ids), ('state', '!=', 'cancel')]), 1, 'one live native move')
        self.assertFalse(self.env['stock.picking'].search([('origin', '=', order.name), ('picking_type_id', '=', self.picking_type.id)]), 'no bridge document')
        self.p_anchor.write({'service_tracking': 'no'})

    def test_repeated_cancellation_is_idempotent(self):
        order, scope, batch, dm = self._bridge_released()
        batch.with_user(self.exec_owner).action_cancel_planned()
        docs = self._docs(order)
        states = {d.id: (d.state, d.reversal_required) for d in batch.demand_ids}
        calls = []
        orig = type(self.env['stock.move'])._action_cancel

        def spy(self_, *a, **kw):
            # only SIPANEL-originated cancellations count; Odoo's own order cancel legitimately re-visits its pickings
            if any('sipanel_scope_execution/models/adapters.py' in f.filename for f in inspect.stack()[1:8]):
                calls.append(1)
            return orig(self_, *a, **kw)
        with patch.object(type(self.env['stock.move']), '_action_cancel', spy):
            batch.with_user(self.exec_owner).action_cancel_planned()
            order.with_user(self.exec_owner).action_cancel()
        self.assertFalse(calls, 'no second SIPANEL document action')
        self.assertEqual(self._docs(order), docs)
        self.assertEqual({d.id: (d.state, d.reversal_required) for d in batch.demand_ids}, states)
        self.assertEqual(self.env['sipanel.scope.audit.event'].sudo().search_count(
            [('res_model', '=', 'sipanel.execution.batch'), ('res_id', '=', batch.id), ('action', '=', 'execution_cancel')]), 1)

    def test_completed_bridge_target_refuses_plain_cancel_and_requires_reversal(self):
        order, scope, batch, dm = self._bridge_released()
        move = dm['stock_issue'].target_ids.filtered(lambda t: t.target_model == 'stock.move').target_record()
        move.picking_id.action_confirm()
        move.write({'quantity': move.product_uom_qty, 'picked': True})
        move.picking_id.button_validate()
        self.assertEqual(move.state, 'done')
        order.action_unlock() if order.locked else None
        with self.assertRaises(UserError):
            order.with_user(self.exec_owner).action_cancel()
        self.assertEqual(dm['stock_issue'].state, 'created', 'nothing was cancelled')
        # the governed cancellation of the batch classifies the executed target as requiring reversal
        batch.with_user(self.exec_owner).action_cancel_planned()
        self.assertTrue(dm['stock_issue'].reversal_required)
        self.assertEqual(move.state, 'done', 'a done move is never touched')
        self.assertFalse(dm['labour'].reversal_required)
        self.assertFalse(dm['manufacture'].reversal_required)

    def test_zero_duplicate_records_after_cancel_and_recount(self):
        order, scope, batch, dm = self._bridge_released()
        before = self._docs(order)
        order.with_user(self.exec_owner).action_cancel()
        after = self._docs(order)
        for k in ('pickings', 'moves', 'po_lines', 'mos', 'targets'):
            self.assertEqual(after[k], before[k], f'cancellation creates no {k}')
        events = self.env['sipanel.actual.projection'].refresh_order(order)
        self.assertEqual(len(events.mapped('source_key')), len(set(events.mapped('source_key'))))


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_step2c_hardening')
class TestSalesCancellation(SipanelExecutionCase):

    def _sales_order_released(self):
        # The order is the Sales user's own document (user_id); it is prepared and sealed by the
        # estimator because sealing writes cost-viewer fields (net_revenue_projection) that a plain
        # Sales user cannot write - a pre-existing restriction outside this pass (OBS-2CH-01).
        order, scope, bracket = self._bridge_order_with_own_line()
        order.write({'user_id': self.sales.id})
        self.assertEqual(order.user_id, self.sales)
        self.assertTrue(order.with_user(self.sales).has_access('write'), 'the Sales user may cancel their own order natively')
        batch = self._release(order)
        self.assertEqual(batch.state, 'released')
        return order, scope, batch

    def test_authorized_sales_user_cancels_own_order_with_released_execution(self):
        order, scope, batch = self._sales_order_released()
        self.assertFalse(self.sales.has_group('sipanel_scope_execution.group_scope_execution_owner'))
        Demand = self.env['sipanel.execution.demand']
        with self.assertRaises(AccessError):
            batch.demand_ids[0].with_user(self.sales).write({'state': 'cancelled'})
        order.with_user(self.sales).action_cancel()
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(batch.state, 'cancelled')
        self.assertTrue(all(d.state == 'cancelled' for d in batch.demand_ids))
        ev = self.env['sipanel.scope.audit.event'].sudo().search([('res_model', '=', 'sipanel.execution.batch'), ('res_id', '=', batch.id), ('action', '=', 'execution_cancel')])
        self.assertEqual(ev.actor_user_id, self.sales, 'the initiating Sales user is the actor, not the service')
        # no general demand rights were granted
        self.assertFalse(Demand.with_user(self.sales).has_access('write'))
        self.assertFalse(Demand.with_user(self.sales).has_access('create'))
        self.assertFalse(Demand.with_user(self.sales).has_access('unlink'))

    def test_unauthorized_user_cannot_cancel_the_order(self):
        order, scope, batch = self._sales_order_released()
        with self.assertRaises(AccessError):
            order.with_user(self.plain_user).action_cancel()
        self.assertEqual(order.state, 'sale')
        self.assertTrue(all(d.state != 'cancelled' for d in batch.demand_ids))
        self.assertEqual(batch.state, 'released')

    def test_sales_user_cannot_write_a_demand_directly(self):
        order, scope, batch = self._sales_order_released()
        d = batch.demand_ids[0]
        for rs in (d.with_user(self.sales), d.with_user(self.sales).with_context(sipanel_demand_engine=True),
                   d.with_user(self.sales).with_context(sipanel_demand_engine=True, sipanel_guard_token='guess')):
            with self.assertRaises(AccessError):
                rs.write({'state': 'cancelled'})
            with self.assertRaises(AccessError):
                rs.write({'demand_key': 'x'})
        self.assertEqual(d.state, 'created')

    def test_sales_user_cannot_cancel_another_orders_demand(self):
        mine, scope_m, batch_m = self._sales_order_released()
        other, scope_o, bracket_o = self._bridge_order_with_own_line()      # estimator's order
        batch_o = self._release(other)
        for rs in (batch_o.with_user(self.sales), batch_o.with_user(self.sales).with_context(sipanel_demand_engine=True),
                   batch_o.with_user(self.sales).with_context(**guard_ctx(DEMAND_ENGINE_GUARD))):
            with self.assertRaises(AccessError):
                rs.action_cancel_planned()
        with self.assertRaises(AccessError):
            other.with_user(self.sales).action_cancel()
        with self.assertRaises(AccessError):
            other.with_user(self.sales).with_context(**guard_ctx(DEMAND_ENGINE_GUARD)).action_cancel()
        self.assertEqual(batch_o.state, 'released')
        self.assertTrue(all(d.state != 'cancelled' for d in batch_o.demand_ids))
        # the sales user's own order is unaffected by the refused attempts
        self.assertEqual(batch_m.state, 'released')

    def test_execution_owner_cancellation_remains_valid(self):
        order, scope, bracket = self._bridge_order_with_own_line()
        batch = self._release(order)
        batch.with_user(self.exec_owner).action_cancel_planned()
        self.assertEqual(batch.state, 'cancelled')
        order2, scope2, bracket2 = self._bridge_order_with_own_line()
        batch2 = self._release(order2)
        order2.with_user(self.exec_owner).action_cancel()
        self.assertEqual(order2.state, 'cancel')
        self.assertEqual(batch2.state, 'cancelled')
