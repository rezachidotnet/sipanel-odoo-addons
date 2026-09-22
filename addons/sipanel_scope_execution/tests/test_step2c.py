# -*- coding: utf-8 -*-
"""STEP 2C: Execution Batch release against separately-billable generated Sale Lines.

Principal invariant: one component -> one operational demand owner -> one
actual-cost source. A generated (separately billable) Sale Line is a customer
revenue projection and must never become a second demand owner.

Regression coverage for the defects found by the live pilot:
  CD-2C-01  failed demands blocked the retry (released batch with no demand);
  CD-2C-02  NATIVE_LINE_OWNER demand of an own-line component linked the anchor's
            documents instead of its own line's native demand;
  CD-2C-03  (sipanel_sale_scope) amendment after confirmation was refused by the
            native unlink rule - covered here through the amendment-delta lineage.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import SipanelExecutionCase


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_step2c')
class TestStep2CDemandOwnership(SipanelExecutionCase):

    # fixtures (_bridge_order_with_own_line, _native_order_with_own_line, _generated_line, _release, _docs) live in common.py

    # ------------------------------------------------------------------ Scenario A: bridge owner
    def test_bridge_owner_generated_line_yields_one_demand_and_zero_native_demand(self):
        order, scope, bracket = self._bridge_order_with_own_line()
        line = self._generated_line(bracket)
        self.assertEqual(len(line), 1, 'quotation projection creates exactly one generated Sale Line')
        self.assertEqual(bracket.execution_owner, 'component_bridge_owner')
        self.assertFalse(line.move_ids, 'confirmation must not launch a native stock demand from a bridge-owned generated line')
        self.assertFalse(line.purchase_line_ids)
        Demand = self.env['sipanel.execution.demand']
        batch = self._release(order)
        self.assertEqual(batch.state, 'released')
        demands = Demand.search([('component_id', '=', bracket.id)])
        self.assertEqual(len(demands), 1, 'exactly one SIPANEL execution demand per component')
        rev = scope.accepted_revision_id
        expected_key = Demand._make_key(bracket.occurrence_uid, rev.acceptance_reference or f"rev:{rev.id}", 'stock_issue', 'component_bridge_owner')
        self.assertEqual(demands.demand_key, expected_key, 'source key is derived from the Scope revision/component, not from the batch')
        self.assertTrue(Demand._fields['demand_key'].readonly, 'the key is declared immutable; no user write path exists')
        self.assertEqual(demands.delta_uid, rev.acceptance_reference or f"rev:{rev.id}")
        targets = demands.target_ids
        self.assertEqual(sorted(targets.mapped('target_model')), ['stock.move', 'stock.picking'], 'the stock adapter creates one picking with one move')
        move = targets.filtered(lambda t: t.target_model == 'stock.move').target_record()
        self.assertEqual(move.product_id, self.p_bracket)
        self.assertEqual(move.product_uom_qty, bracket.final_qty)
        self.assertEqual(move.state, 'draft')
        self.assertEqual(self.env['stock.move'].search_count([('product_id', '=', self.p_bracket.id), ('origin', '=', order.name)]), 1)
        self.assertFalse(line.move_ids, 'the generated line still owns no native move after release')
        docs = self._docs(order)
        # release again, retry after completion, and the explicit action: nothing additional
        self.assertEqual(self._release(order), batch)
        self.assertEqual(self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order), batch)
        self.assertEqual(self._release(order), batch)
        self.assertEqual(self._docs(order), docs, 'repeat release creates nothing additional')
        self.assertEqual(Demand.search_count([('order_id', '=', order.id)]), 7)
        keys = Demand.search([('order_id', '=', order.id)]).mapped('demand_key')
        self.assertEqual(len(keys), len(set(keys)), 'unique source keys')

    # ------------------------------------------------------------------ Scenario B: native line owner
    def test_native_owner_own_line_links_its_own_native_demand_and_creates_none(self):
        order, scope, bracket = self._native_order_with_own_line()
        line = self._generated_line(bracket)
        self.assertEqual(len(line), 1)
        self.assertEqual(bracket.execution_owner, 'native_line_owner')
        self.assertEqual(len(line.move_ids), 1, 'the native Sale line creates the normal Odoo delivery demand once')
        native_move = line.move_ids
        task = scope.anchor_line_id.task_id
        self.assertTrue(task, 'the anchor created its task natively')
        docs_before = self._docs(order)
        batch = self._release(order)
        self.assertEqual(batch.state, 'released')
        d = self.env['sipanel.execution.demand'].search([('component_id', '=', bracket.id)])
        self.assertEqual(len(d), 1)
        self.assertEqual(d.owner, 'native_line_owner')
        self.assertEqual(d.state, 'linked')
        links = {(t.target_model, t.target_res_id, t.link_kind) for t in d.target_ids}
        self.assertIn(('stock.move', native_move.id, 'native_anchor_covered'), links,
                      'CD-2C-02: the demand links the native demand of ITS OWN generated line')
        self.assertNotIn(('project.task', task.id, 'native_anchor_covered'), links,
                         "an own-line component is not covered by the anchor's task")
        # components without an own line stay covered by the anchor
        labour = self.env['sipanel.execution.demand'].search([('order_id', '=', order.id), ('component_id.product_id', '=', self.p_labour.id)])
        self.assertEqual({(t.target_model, t.target_res_id) for t in labour.target_ids}, {('project.task', task.id)})
        # SIPANEL created no second operational demand anywhere
        docs_after = self._docs(order)
        for k in ('pickings', 'moves', 'po_lines', 'mos', 'tasks'):
            self.assertEqual(docs_after[k], docs_before[k], f'no additional {k} from the bridge')
        self.assertEqual(len(line.move_ids), 1)
        self.assertFalse(self.env['stock.picking'].search([('origin', '=', order.name), ('picking_type_id', '=', self.picking_type.id)]))
        self.assertEqual(self._release(order), batch)
        self.assertEqual(self._docs(order), docs_after)
        # provenance: Scope, revision, component, Sale Line, operational document
        self.assertEqual(line.sipanel_source_quote_scope_id, scope)
        self.assertEqual(line.sipanel_source_revision_id, scope.accepted_revision_id)
        self.assertEqual(d.quote_scope_id, scope)
        self.assertEqual(d.component_id.revision_id, scope.accepted_revision_id)
        self.assertEqual(native_move.sale_line_id, line)
        self.p_anchor.write({'service_tracking': 'no'})

    # ------------------------------------------------------------------ C3 partial failure and retry
    def test_retry_after_failure_creates_the_full_demand_set_exactly_once(self):
        order, scope, bracket = self._bridge_order_with_own_line()
        Demand = self.env['sipanel.execution.demand']
        self.env['product.supplierinfo'].search([('product_tmpl_id', '=', self.p_crane.product_tmpl_id.id)]).unlink()
        failed = self._release(order)
        self.assertEqual(failed.state, 'failed')
        self.assertIn('vendor', failed.error_summary)
        self.assertTrue(failed.demand_ids and all(d.state == 'failed' for d in failed.demand_ids))
        self.assertEqual(self._docs(order)['targets'], 0)
        self.assertEqual(self._docs(order)['pickings'], 0)
        # retrying without fixing the cause fails again - it must not "succeed" with nothing
        failed2 = self._release(order)
        self.assertEqual(failed2.state, 'failed', 'CD-2C-01: a retry with the cause still present is a failed batch, not an empty release')
        self.assertNotEqual(failed2, failed)
        self.assertTrue(failed2.demand_ids, 'the retry re-demands every component')
        self.assertEqual(self._docs(order)['targets'], 0)
        # fix the cause and retry: the whole demand set is created exactly once
        self.env['product.supplierinfo'].create({'partner_id': self.vendor.id, 'product_tmpl_id': self.p_crane.product_tmpl_id.id, 'price': 400.0, 'min_qty': 0})
        ok = self._release(order)
        self.assertEqual(ok.state, 'released')
        self.assertEqual(len(ok.demand_ids), 7, 'the retry creates the full demand set')
        self.assertTrue(all(d.target_ids for d in ok.demand_ids), 'every demand of the successful batch has its operational record')
        docs = self._docs(order)
        self.assertEqual(docs['po_lines'], 1)
        self.assertEqual(docs['mos'], 1)
        self.assertEqual(docs['pickings'], 4)
        # exactly one LIVE demand per key; failed demands are retained as evidence but never hold the key
        for key in set(Demand.search([('order_id', '=', order.id)]).mapped('demand_key')):
            self.assertEqual(Demand.search_count([('demand_key', '=', key), ('state', '!=', 'failed')]), 1, key)
        self.assertEqual(Demand.search_count([('order_id', '=', order.id), ('state', '=', 'failed')]), 14)
        self.assertEqual(self._release(order), ok)
        self.assertEqual(self._docs(order), docs, 'retry after completion creates nothing additional')

    # ------------------------------------------------------------------ C5 propagation
    def test_project_system_activity_propagate_to_every_execution_record(self):
        order, scope, bracket = self._bridge_order_with_own_line()
        batch = self._release(order)
        for d in batch.demand_ids:
            self.assertEqual(d.project_id, self.project)
            self.assertEqual(d.system_id, self.system_a)
            self.assertEqual(d.activity_id, d.component_id.activity_id)
            self.assertEqual(d.quote_scope_id, scope)
            self.assertEqual(d.component_id.revision_id, scope.accepted_revision_id)
            self.assertEqual(d.batch_id, batch)
            self.assertTrue(d.demand_key)
        pol = batch.demand_ids.filtered(lambda d: d.execution_mode == 'equipment_service').target_ids.target_record()
        dist_ids = {int(i) for k in pol.analytic_distribution for i in k.split(',')}
        self.assertIn(self.system_a.id, dist_ids)
        self.assertIn(self.act_eqp.id, dist_ids)
        if self.project.account_id:
            self.assertIn(self.project.account_id.id, dist_ids)
        mo = batch.demand_ids.filtered(lambda d: d.execution_mode == 'manufacture').target_ids.target_record()
        self.assertEqual(mo.project_id, self.project)
        for d in batch.demand_ids.filtered(lambda d: d.execution_mode == 'stock_issue'):
            picking = d.target_ids.filtered(lambda t: t.target_model == 'stock.picking').target_record()
            self.assertEqual(picking.origin, order.name)
            self.assertTrue(d.target_ids.mapped('stock_reference_id'))

    # ------------------------------------------------------------------ C6 one actual-cost source, no duplicate project cost
    def test_actual_cost_projection_is_idempotent_and_never_double_allocates(self):
        order, scope, bracket = self._bridge_order_with_own_line()
        self._release(order)
        Proj = self.env['sipanel.actual.projection']
        first = Proj.refresh_order(order)
        second = Proj.refresh_order(order)
        self.assertEqual(set(first.ids), set(second.ids), 'refreshing twice creates no new event')
        keys = first.mapped('source_key')
        self.assertEqual(len(keys), len(set(keys)), 'one event per source document')
        for ev in first:
            per_demand = {}
            for a in ev.allocation_ids:
                per_demand[a.demand_id.id] = per_demand.get(a.demand_id.id, 0) + 1
            self.assertTrue(all(n == 1 for n in per_demand.values()), 'no event is allocated twice to the same demand')
        # a generated line contributes no cost source of its own: the bracket has exactly one operational target
        d = self.env['sipanel.execution.demand'].search([('component_id', '=', bracket.id)])
        self.assertEqual(len(d.target_ids.filtered(lambda t: t.target_model == 'stock.move')), 1)

    # ------------------------------------------------------------------ C4 amendment and cancellation lineage
    def test_amendment_after_release_with_generated_lines_keeps_lineage_and_adds_one_delta(self):
        order, scope, bracket = self._bridge_order_with_own_line()
        b = self._release(order)
        line_v1 = self._generated_line(bracket)
        qty_v1 = bracket.final_qty
        new_rev = scope.current_revision_id.action_amend()      # CD-2C-03: allowed on a confirmed order
        bracket2 = new_rev.component_ids.filtered(lambda c: c.product_id == self.p_bracket)
        bracket2.write({'qty_override': True, 'override_qty': qty_v1 + 10.0, 'override_reason': 'site survey'})
        scope.action_accept_change_order('CO-2C')
        line_v2 = self._generated_line(bracket2)
        self.assertTrue(line_v1.exists(), 'the superseded generated line is neutralised, never deleted')
        self.assertEqual(line_v1.product_uom_qty, 0.0)
        self.assertEqual(line_v2.product_uom_qty, qty_v1 + 10.0)
        live = self.env['sale.order.line'].search([('order_id', '=', order.id), ('sipanel_is_generated', '=', True), ('product_uom_qty', '>', 0)])
        self.assertEqual(live, line_v2, 'exactly one live generated line per component')
        self.assertFalse(line_v1.move_ids | line_v2.move_ids, 'no generated line owns a native demand under the bridge owner')
        created = order.with_user(self.exec_owner).action_sipanel_release_amendment_delta()
        self.assertEqual(len(created), 1)
        self.assertEqual(created.signed_qty, 10.0)
        self.assertEqual(created.component_id, bracket2)
        Demand = self.env['sipanel.execution.demand']
        for_occurrence = Demand.search([('component_id.occurrence_uid', '=', bracket.occurrence_uid), ('state', 'not in', ('cancelled', 'failed'))])
        self.assertEqual(sum(for_occurrence.mapped('signed_qty')), qty_v1 + 10.0, 'demand follows the accepted baseline exactly once')
        self.assertEqual(len(for_occurrence), 2, 'original demand + one delta, no re-demand of the superseded revision')
        self.assertFalse(order.with_user(self.exec_owner).action_sipanel_release_amendment_delta(), 'the delta is idempotent')
        self.assertEqual(self.env['stock.move'].search_count([('product_id', '=', self.p_bracket.id), ('origin', '=', order.name)]), 2)
        # cancellation: lineage retained, planned documents cancelled, nothing deleted
        moves = self.env['stock.move'].search([('origin', '=', order.name)])
        mo = self.env['mrp.production'].search([('origin', '=', order.name)])
        pol = self.env['purchase.order.line'].search([('order_id.origin', '=', order.name)])
        # the order recordset carries the estimator's environment; cancelling released
        # execution is an Execution Owner action (demand write access)
        order = order.with_user(self.exec_owner)
        order.action_unlock() if order.locked else None
        order.action_cancel()
        self.assertEqual(order.state, 'cancel')
        self.assertTrue(all(m.exists() for m in moves))
        self.assertTrue(all(m.state == 'cancel' for m in moves))
        self.assertEqual(mo.state, 'cancel')
        self.assertEqual(pol.product_qty, 0.0)
        self.assertTrue(all(bt.state == 'cancelled' for bt in order.sipanel_execution_batch_ids))
        self.assertTrue(all(d.state == 'cancelled' for d in Demand.search([('order_id', '=', order.id)])))
        self.assertEqual(self.env['sipanel.execution.target'].search_count([('demand_id.order_id', '=', order.id)]), len(b.demand_ids.mapped('target_ids')) + len(created.target_ids))
        self.assertEqual(scope.accepted_revision_id, new_rev)
        self.assertEqual(new_rev.prior_revision_id, b.accepted_revision_ids)
