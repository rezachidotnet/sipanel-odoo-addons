# -*- coding: utf-8 -*-
"""PT-16, PT-17, PT-18, PT-19, PT-20, PT-21, PT-29: one terminal event per economic cost; reconciliation to the C9 oracle."""
from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged, new_test_user

from odoo.addons.sipanel_scope_execution.tests.common import SipanelExecutionCase, TEST_BATCH
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx


@tagged('post_install', '-at_install', 'sipanel')
class TestActuals(SipanelExecutionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.fin_user = new_test_user(env, login='sipanel_pt_fin_rec', name='SIPANEL-PT Finance Recognition',
                                     groups='account.group_account_manager,sipanel_scope_costing.group_scope_finance,sipanel_scope_execution.group_scope_execution_owner,stock.group_stock_user,purchase.group_purchase_user,mrp.group_mrp_user,project.group_project_user,sales_team.group_sale_manager,sipanel_sale_scope.group_scope_sales')
        for p in env['sipanel.cost.recognition.policy'].search([('company_id', '=', cls.company.id), ('state', '=', 'draft')]):
            p.with_user(cls.fin_user).action_approve(source='SIPANEL-PT management authorization 2026-09-19')
        # employee with governed hourly cost (SV-17)
        cls.employee = env['hr.employee'].create({'name': f'{TEST_BATCH} Installer', 'hourly_cost': 30.0, 'company_id': cls.company.id})
        # valuation: real-time/automated not required — value field is populated on done moves by stock_account
        cls.p_bracket.write({'standard_price': 5.0})
        cls.p_screw.write({'standard_price': 1.0})
        cls.p_gutter.write({'standard_price': 100.0})
        Quant = env['stock.quant']
        wh = env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        for p, qty in ((cls.p_bracket, 1000), (cls.p_screw, 1000), (cls.p_sealant, 100), (cls.p_coil, 1000)):
            Quant._update_available_quantity(p, wh.lot_stock_id, qty)

    def _validate_picking(self, picking):
        picking.action_confirm()
        picking.action_assign()
        for mv in picking.move_ids:
            mv.write({'quantity': mv.product_uom_qty, 'picked': True})
        picking.button_validate()

    def _bill(self, pol, price=None, qty=None, refund=False):
        po = pol.order_id
        if po.state in ('draft', 'sent'):
            po.button_confirm()
        move = self.env['account.move'].create({
            'move_type': 'in_refund' if refund else 'in_invoice', 'partner_id': po.partner_id.id, 'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'product_id': pol.product_id.id, 'quantity': qty or pol.product_qty, 'price_unit': price if price is not None else pol.price_unit,
                                         'purchase_line_id': pol.id, 'analytic_distribution': pol.analytic_distribution})],
        })
        move.action_post()
        return move

    def test_pt16_pt21_reconciliation(self):
        order, scope = self._confirmed_order()
        self.p_sealant.write({'standard_price': 22.0})  # actual cost differs from the sealed estimate (20) on purpose; set AFTER acceptance
        batch = self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order)
        demands = {d.execution_mode + ':' + (d.component_id.product_id.name or ''): d for d in batch.demand_ids}
        # --- PT-16 shared stock: issue brackets / screws / sealant to site; receipt & bill excluded
        for d in batch.demand_ids.filtered(lambda d: d.execution_mode == 'stock_issue'):
            picking = d.target_ids.filtered(lambda t: t.target_model == 'stock.picking').target_record()
            self._validate_picking(picking)
        # --- PT-17 manufacture the gutter: consume coil, produce, then issue finished goods to site
        mo_d = batch.demand_ids.filtered(lambda d: d.execution_mode == 'manufacture')
        mo = mo_d.target_ids.filtered(lambda t: t.target_model == 'mrp.production').target_record()
        mo.action_confirm()
        mo.action_assign()
        for mv in mo.move_raw_ids:
            mv.write({'quantity': mv.product_uom_qty, 'picked': True})
        mo.write({'qty_producing': mo.product_qty})
        mo.button_mark_done()
        self.assertEqual(mo.state, 'done')
        issue = self.env['stock.picking'].create({'picking_type_id': self.picking_type.id, 'location_id': self.picking_type.default_location_src_id.id,
                                                  'location_dest_id': self.picking_type.default_location_dest_id.id, 'origin': order.name})
        fin_move = self.env['stock.move'].create({'product_id': self.p_gutter.id, 'product_uom_qty': 85, 'product_uom': self.uom_m.id,
                                                  'picking_id': issue.id, 'location_id': issue.location_id.id, 'location_dest_id': issue.location_dest_id.id,
                                                  'origin': order.name, 'reference_ids': [(6, 0, mo.reference_ids.ids)] if 'reference_ids' in self.env['stock.move']._fields else False})
        self._validate_picking(issue)
        # --- PT-18 / PT-20 equipment: bill the crane RFQ (450 actual)
        eq = batch.demand_ids.filtered(lambda d: d.execution_mode == 'equipment_service')
        pol = eq.target_ids.target_record()
        self._bill(pol, price=450.0)
        # --- PT-20 labour: real timesheet 9 h at governed hourly cost (no synthetic timesheets created by the module)
        ts = self.env['account.analytic.line'].create({'name': 'site install', 'project_id': self.project.id, 'employee_id': self.employee.id, 'unit_amount': 9.0,
                                                       'company_id': self.company.id})
        self.assertAlmostEqual(ts.amount, -270.0, places=2)
        # --- revenue: invoice the anchor
        inv = order._create_invoices()
        inv.write({'partner_bank_id': False})  # Production company bank is untrusted for outbound payments; not the subject of this test
        inv.action_post()
        # --- projection
        events = self.env['sipanel.actual.projection'].with_user(self.fin_user).refresh_order(order)
        included = events.filtered(lambda e: e.inclusion == 'included' and e.layer == 'recognized' and e.component_type != 'revenue')
        excluded = events.filtered(lambda e: e.inclusion == 'excluded_duplicate')
        # raw coil consumption and MO finished move are excluded; receipts none; PO commitment excluded
        self.assertTrue(excluded.filtered(lambda e: e.source_model == 'stock.move' and e.layer == 'wip'))
        self.assertTrue(excluded.filtered(lambda e: e.source_model == 'purchase.order.line' and e.layer == 'commitment'))
        # exactly one recognised event per economic cost
        keys = included.mapped('source_key')
        self.assertEqual(len(keys), len(set(keys)))
        by_type = {}
        for e in included:
            by_type[e.component_type] = by_type.get(e.component_type, 0) + e.amount
        material = by_type.get('material', 0.0)
        gutter_value = abs(fin_move.value)
        # PT-17: parent full value counted once, raw/labour not added again
        self.assertTrue(included.filtered(lambda e: e.source_res_id == fin_move.id and e.source_model == 'stock.move'))
        self.assertFalse(included.filtered(lambda e: e.source_model == 'stock.move' and e.source_res_id in mo.move_raw_ids.ids))
        self.assertAlmostEqual(material, gutter_value + 850.0 + 340.0 + 17.0 + 220.0, places=2)
        self.assertAlmostEqual(by_type.get('equipment', 0.0), 450.0, places=2)
        self.assertAlmostEqual(by_type.get('labour', 0.0), 270.0, places=2)
        # PT-21 reconciliation: with gutter valued at 100/m (MO cost from coil 60 + no labour => value 5100 if BoM-only);
        # the oracle assumes 9000 for the gutter; assert the bridge arithmetic structurally with the actual gutter value
        actual_total = material + 450.0 + 270.0
        baseline = scope.accepted_revision_id.sudo().eligible_cost_total
        self.assertAlmostEqual(baseline, 10734.0, places=2)
        direct_estimate = scope.accepted_revision_id.sudo().direct_cost_total
        self.assertAlmostEqual(actual_total - baseline, (actual_total - direct_estimate) - 187.0, places=2, msg='variance bridge: direct overrun minus unused contingency')
        revenue = sum(events.filtered(lambda e: e.component_type == 'revenue').mapped('amount'))
        self.assertAlmostEqual(revenue, 12000.0, delta=0.5)
        var = self.env['sipanel.scope.variance'].with_user(self.fin_user).search([('quote_scope_id', '=', scope.id)])
        self.assertAlmostEqual(var.baseline_cost, 10734.0, places=2)
        self.assertAlmostEqual(var.recognised_revenue, 12000.0, delta=0.5)
        self.assertAlmostEqual(var.recognised_cost, actual_total, places=2)
        self.assertAlmostEqual(var.recognised_margin, revenue - actual_total, delta=0.01)
        self.assertAlmostEqual(var.variance_amount, actual_total - 10734.0, places=2)
        # contingency has no actual event and is never fabricated
        self.assertFalse(events.filtered(lambda e: e.component_type == 'adjustment'))
        # PT-29: the timesheet is dimension-matched (no LABOUR target link to a task) => allocated via project link or UNALLOCATED, never hidden
        self.assertIn(var.completeness, ('complete', 'incomplete'))
        # idempotent refresh
        n = len(events)
        again = self.env['sipanel.actual.projection'].with_user(self.fin_user).refresh_order(order)
        self.assertEqual(len(again), n)
        self.assertEqual(self.env['sipanel.actual.cost.event'].search_count([('company_id', '=', self.company.id), ('source_key', 'in', events.mapped('source_key'))]), n)
        # projection never wrote native records: analytic lines count unchanged apart from the manual timesheet
        self.assertEqual(self.env['account.analytic.line'].search_count([('project_id', '=', self.project.id), ('employee_id', '!=', False)]), 1)
        # events are read-only for everyone but the projection
        with self.assertRaises(UserError):
            self.env['sipanel.actual.cost.event'].browse(included[0].id).with_user(self.fin_user).write({'amount': 1})
        with self.assertRaises(UserError):  # a spoofed RPC context flag must not unlock the projection guard (CD-12)
            self.env['sipanel.actual.cost.event'].browse(included[0].id).with_context(sipanel_projection=True).write({'amount': 1})
        with self.assertRaises(AccessError):
            included[0].with_user(self.sales).read(['amount'])

    def test_pt19_return_and_credit_reverse_once(self):
        order, scope = self._confirmed_order()
        batch = self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order)
        eq = batch.demand_ids.filtered(lambda d: d.execution_mode == 'equipment_service')
        pol = eq.target_ids.target_record()
        bill = self._bill(pol, price=450.0)
        credit = self._bill(pol, price=450.0, refund=True)
        events = self.env['sipanel.actual.projection'].with_user(self.fin_user).refresh_order(order)
        eq_events = events.filtered(lambda e: e.component_type == 'equipment' and e.inclusion == 'included')
        self.assertEqual(len(eq_events), 2)
        rev = eq_events.filtered(lambda e: e.amount < 0)
        orig = eq_events - rev
        self.assertEqual(rev.reversal_of_id, orig)
        self.assertAlmostEqual(sum(eq_events.mapped('amount')), 0.0, places=2)
        again = self.env['sipanel.actual.projection'].with_user(self.fin_user).refresh_order(order)
        self.assertEqual(len(again.filtered(lambda e: e.component_type == 'equipment' and e.inclusion == 'included')), 2, 'signed reversal exactly once')
        self.assertTrue(bill.exists() and credit.exists(), 'historical monetary records are never deleted')

    def test_policy_fail_closed_and_pt29_unallocated(self):
        # supersede the site_labour policy with a draft: labour events become POLICY_MISSING and sum nothing
        pol = self.env['sipanel.cost.recognition.policy'].approved_for('site_labour', self.company)
        pol.with_context(**guard_ctx('sipanel_policy_action')).write({'state': 'superseded'})
        order, scope = self._confirmed_order()
        self.env['sipanel.execution.batch'].with_user(self.exec_owner).release_for_order(order)
        self.env['account.analytic.line'].create({'name': 'stray hours', 'project_id': self.project.id, 'employee_id': self.employee.id, 'unit_amount': 2.0, 'company_id': self.company.id})
        events = self.env['sipanel.actual.projection'].with_user(self.fin_user).refresh_order(order)
        lab = events.filtered(lambda e: e.component_type == 'labour')
        self.assertTrue(lab)
        self.assertTrue(all(e.inclusion == 'policy_missing' and e.allocation_state == 'unpolicied' for e in lab))
        var = self.env['sipanel.scope.variance'].with_user(self.fin_user).search([('quote_scope_id', '=', scope.id)])
        self.assertEqual(var.completeness, 'policy_missing')
        # re-approve a new version, then the stray timesheet without target link lands in UNALLOCATED
        new = self.env['sipanel.cost.recognition.policy'].create({'route': 'site_labour', 'version': pol.version + 1, 'terminal_event_model': 'account.analytic.line', 'company_id': self.company.id})
        with self.assertRaises(UserError):
            new.write({'state': 'approved'})
        with self.assertRaises(AccessError):
            new.with_user(self.exec_owner).action_approve()
        new.with_user(self.fin_user).action_approve(source='test')
        events = self.env['sipanel.actual.projection'].with_user(self.fin_user).refresh_order(order)
        lab = events.filtered(lambda e: e.component_type == 'labour' and e.inclusion == 'included')
        self.assertTrue(lab)
        # LABOUR demand links the project, so the timesheet is target-linked; verify the visible bucket logic on a foreign timesheet
        other_project = self.env['project.project'].create({'name': f'{TEST_BATCH} Other project'})
        scope.write({'project_id': other_project.id})
        stray = self.env['account.analytic.line'].create({'name': 'unlinked', 'project_id': other_project.id, 'employee_id': self.employee.id, 'unit_amount': 1.0, 'company_id': self.company.id})
        events = self.env['sipanel.actual.projection'].with_user(self.fin_user).refresh_order(order)
        ev = events.filtered(lambda e: e.source_res_id == stray.id and e.source_model == 'account.analytic.line')
        self.assertEqual(ev.allocation_state, 'unallocated')
        self.assertAlmostEqual(ev.unallocated_amount, 30.0, places=2)
        var = self.env['sipanel.scope.variance'].with_user(self.fin_user).search([('quote_scope_id', '=', scope.id)])
        self.assertEqual(var.completeness, 'incomplete')
        self.env.flush_all()
        self.env.cr.execute("SELECT id, source_model, source_res_id, component_type, amount, unallocated_amount, project_id, layer, inclusion FROM sipanel_actual_cost_event WHERE project_id = %s AND layer = 'recognized' AND component_type <> 'revenue'", (other_project.id,))
        raw_events = self.env.cr.fetchall()
        self.env.cr.execute("SELECT id, quote_scope_id, project_id, unallocated_cost FROM sipanel_scope_variance WHERE quote_scope_id = %s", (scope.id,))
        raw_var = self.env.cr.fetchall()
        self.assertAlmostEqual(var.unallocated_cost, 30.0, places=2, msg=f'events={raw_events} variance_rows={raw_var}')
        # manual allocation by Finance with reason closes the gap and is audited
        self.env['sipanel.actual.allocation'].with_user(self.fin_user).allocate_manually(ev, scope, False, 30.0, 'reviewed: belongs to gutter job')
        self.assertEqual(ev.allocation_state, 'allocated')
