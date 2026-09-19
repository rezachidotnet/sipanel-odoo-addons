# -*- coding: utf-8 -*-
"""PT-12, PT-13, PT-14, PT-15, PT-19 (planned cancel), PT-22 (qty deltas)."""
from unittest.mock import patch

from odoo.exceptions import LockError, UserError
from odoo.tests import tagged

from .common import SipanelExecutionCase


@tagged('post_install', '-at_install', 'sipanel')
class TestRelease(SipanelExecutionCase):

    def test_release_creates_one_demand_per_component(self):
        order, scope = self._confirmed_order()
        with self.assertRaises(UserError):
            order.with_user(self.sales).action_sipanel_release_execution()
        res = order.with_user(self.exec_owner).action_sipanel_release_execution()
        batch = self.env['sipanel.execution.batch'].browse(res['res_id'])
        self.assertEqual(batch.state, 'released')
        demands = batch.demand_ids
        # 7 physical components (contingency has no demand); NO_ACTION lines produce none
        self.assertEqual(len(demands), 7)
        modes = dict(demands.mapped(lambda d: (d.component_id.product_id.name.split()[-1], d.execution_mode)))
        by_mode = {}
        for d in demands:
            by_mode.setdefault(d.execution_mode, []).append(d)
        self.assertEqual(len(by_mode['manufacture']), 1)
        mo = by_mode['manufacture'][0].target_ids.filtered(lambda t: t.target_model == 'mrp.production').target_record()
        self.assertEqual(mo.state, 'draft')
        self.assertEqual(mo.product_qty, 85.0)
        self.assertEqual(mo.project_id, self.project)
        self.assertEqual(len(by_mode['stock_issue']), 4)  # bracket, screw, sealant, allowance
        for d in by_mode['stock_issue']:
            mv = d.target_ids.filtered(lambda t: t.target_model == 'stock.move').target_record()
            self.assertEqual(mv.state, 'draft')
            self.assertEqual(mv.product_uom_qty, d.normalized_qty)
            self.assertTrue(d.target_ids.mapped('stock_reference_id'))
        self.assertTrue(order.stock_reference_ids)
        eq = by_mode['equipment_service'][0]
        pol = eq.target_ids.target_record()
        self.assertEqual(pol.order_id.state, 'draft')
        self.assertEqual(pol.product_qty, 1.0)
        self.assertTrue(pol.analytic_distribution)
        lab = by_mode['labour'][0]
        self.assertEqual(lab.state, 'linked')
        self.assertFalse(self.env['account.analytic.line'].search([('project_id', '=', self.project.id)]), 'no synthetic timesheets')
        # no ESTIMATE/derived demand
        self.assertFalse(demands.filtered(lambda d: d.component_id.basis == 'percent_of_cost'))
        self.assertTrue(all(d.demand_key for d in demands))
        self.assertEqual(len(set(demands.mapped('demand_key'))), 7)

    def test_pt14_release_twice_and_concurrent(self):
        order, scope = self._confirmed_order()
        b1 = self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order)
        b2 = self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order)
        self.assertEqual(b1, b2, 'second click returns the same batch')
        self.assertEqual(self.env['sipanel.execution.demand'].search_count([('order_id', '=', order.id)]), 7)
        # concurrent: another cursor holds the order lock => LockError path, bounded retry, then UserError
        self.env['ir.config_parameter'].sudo().set_param('sipanel_scope.release_backoff_ms', '0')
        order2, scope2 = self._confirmed_order()
        with patch.object(type(order2), 'lock_for_update', side_effect=LockError('locked by another transaction')):
            with self.assertRaises(UserError) as cm:
                self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order2)
            self.assertIn('retry exhausted', str(cm.exception))
        self.assertFalse(self.env['sipanel.execution.batch'].search([('order_id', '=', order2.id), ('state', '=', 'released')]))
        # after the lock is released the release succeeds once
        b = self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order2)
        self.assertEqual(b.state, 'released')

    def test_pt15_adapter_failure_rolls_back(self):
        order, scope = self._confirmed_order()
        self.env['product.supplierinfo'].search([('product_tmpl_id', '=', self.p_crane.product_tmpl_id.id)]).unlink()
        n_po = self.env['purchase.order'].search_count([])
        n_mo = self.env['mrp.production'].search_count([])
        n_pick = self.env['stock.picking'].search_count([])
        with self.assertRaises(UserError):
            self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order)
        self.assertEqual(self.env['purchase.order'].search_count([]), n_po)
        self.assertEqual(self.env['mrp.production'].search_count([]), n_mo)
        self.assertEqual(self.env['stock.picking'].search_count([]), n_pick)
        batch = self.env['sipanel.execution.batch'].search([('order_id', '=', order.id)])
        self.assertEqual(batch.state, 'failed')
        self.assertFalse(self.env['sipanel.execution.target'].search([('demand_id.order_id', '=', order.id)]))

    def test_pt12_estimate_only_blocks(self):
        order, scope = self._make_order(85.0)
        scope.write({'project_id': self.project.id, 'system_id': self.system_a.id})
        self.env['sipanel.quote.scope.component'].sudo().create({
            'revision_id': scope.current_revision_id.id, 'kind': 'estimate_only', 'description': 'unknown flashing', 'uom_id': self.uom_m.id,
            'dimension_family': 'length', 'basis': 'fixed', 'fixed_qty': 2, 'resolution_state': 'open', 'resolution_owner_id': self.estimator.id,
            'execution_mode': 'buy_direct', 'activity_id': self.act_ins.id, 'cost_source': 'manual_estimate', 'unit_cost': 5, 'manual_cost_reason': 'guess'})
        scope.anchor_line_id.write({'price_unit': 200})
        order.action_quotation_sent()
        order.action_confirm()
        with self.assertRaises(UserError) as cm:
            self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order)
        self.assertIn('ESTIMATE_ONLY', str(cm.exception))
        # approved allowance (NO_ACTION with reason) stays no-action: contingency yields no demand
        self.assertFalse(self.env['sipanel.execution.demand'].search([('order_id', '=', order.id)]))

    def test_pt13_native_owner_links_not_creates(self):
        # anchor product with task-creating tracking => NATIVE_LINE_OWNER resolves; version release must declare it
        self.p_anchor.write({'service_tracking': 'task_global_project', 'project_id': self.project.id})
        self.assertEqual(self.env['sipanel.execution.owner.rule'].resolve(self.p_anchor, self.company), 'native_line_owner')
        v2 = self.env['sipanel.scope.version'].browse(self.v1.action_new_version()['res_id'])
        with self.assertRaises(Exception):
            v2.action_release()  # R4: declared bridge owner conflicts with registry
        v2.write({'anchor_owner_mode': 'native_line_owner'})
        for l in v2.recipe_line_ids.filtered(lambda l: l.execution_mode != 'no_action'):
            l.write({'execution_mode': 'native_anchor_covered'})
        v2.action_release()
        order = self.env['sale.order'].create({'partner_id': self.partner.id})
        scope = self.env['sipanel.quote.scope']._create_from_version(order, v2, 85.0, self.uom_m)
        scope.write({'project_id': self.project.id, 'system_id': self.system_a.id})
        scope.anchor_line_id.write({'price_unit': 100})
        order.action_quotation_sent()
        order.action_confirm()
        task = scope.anchor_line_id.task_id
        self.assertTrue(task, 'native confirm created the task once')
        n_tasks = self.env['project.task'].search_count([('sale_line_id', '=', scope.anchor_line_id.id)])
        batch = self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order)
        self.assertEqual(batch.state, 'released')
        self.assertEqual(self.env['project.task'].search_count([('sale_line_id', '=', scope.anchor_line_id.id)]), n_tasks, 'bridge never re-creates')
        for d in batch.demand_ids:
            self.assertEqual(d.owner, 'native_line_owner')
            self.assertTrue(all(t.link_kind == 'native_anchor_covered' for t in d.target_ids))
        self.assertFalse(self.env['mrp.production'].search([('origin', '=', order.name)]))
        self.assertFalse(self.env['stock.picking'].search([('origin', '=', order.name), ('picking_type_id', '=', self.picking_type.id)]))
        self.p_anchor.write({'service_tracking': 'no'})

    def test_pt22_qty_delta_and_pt19_cancel_lineage(self):
        order, scope = self._confirmed_order()
        b = self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order)
        # amendment increasing bracket by 10 units
        new = scope.current_revision_id.action_amend()
        bracket = new.component_ids.filtered(lambda c: c.product_id == self.p_bracket)
        bracket.write({'qty_override': True, 'override_qty': 180.0, 'override_reason': 'site survey'})
        scope.action_accept_change_order('CO-2')
        created = order.with_user(self.exec_owner).action_sipanel_release_amendment_delta()
        self.assertEqual(len(created), 1)
        self.assertEqual(created.signed_qty, 10.0)
        self.assertEqual(created.component_id, bracket)
        self.assertEqual(created.target_ids.filtered(lambda t: t.target_model == 'stock.move').target_record().product_uom_qty, 10.0)
        # price-only amendment: no demand
        new2 = scope.current_revision_id.action_amend()
        scope.anchor_line_id.with_context(sipanel_apply_price=True).write({'price_unit': 150})
        scope.action_accept_change_order('CO-3')
        self.assertFalse(order.with_user(self.exec_owner).action_sipanel_release_amendment_delta())
        # decrease: planned draft moves are cancelled, nothing deleted, lineage recorded
        new3 = scope.current_revision_id.action_amend()
        br3 = new3.component_ids.filtered(lambda c: c.product_id == self.p_bracket)
        br3.write({'qty_override': True, 'override_qty': 170.0, 'override_reason': 'back to plan'})
        scope.action_accept_change_order('CO-4')
        neg = order.with_user(self.exec_owner).action_sipanel_release_amendment_delta()
        self.assertEqual(neg.signed_qty, -10.0)
        self.assertEqual(neg.reversal_of_id, created, 'latest positive delta is reduced, not the original demand')
        self.assertEqual(neg.reversal_of_id.state, 'cancelled')
        mv = neg.reversal_of_id.target_ids.filtered(lambda t: t.target_model == 'stock.move').target_record()
        self.assertTrue(mv.exists(), 'never deleted')
        self.assertEqual(mv.state, 'cancel')
        self.assertEqual(b.demand_ids.filtered(lambda d: d.component_id.product_id == self.p_bracket).state, 'created')
        # order cancel refuses when a target is done
        first_move = b.demand_ids.filtered(lambda d: d.execution_mode == 'stock_issue')[0].target_ids.filtered(lambda t: t.target_model == 'stock.move').target_record()
        first_move.picking_id.action_confirm()
        first_move.write({'quantity': first_move.product_uom_qty, 'picked': True})
        first_move.picking_id.button_validate()
        self.assertEqual(first_move.state, 'done')
        order.action_unlock() if order.locked else None
        with self.assertRaises(UserError):
            order.action_cancel()
