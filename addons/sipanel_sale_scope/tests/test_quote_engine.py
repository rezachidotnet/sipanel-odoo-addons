# -*- coding: utf-8 -*-
"""PT-01, PT-02, PT-03, PT-04, PT-05, PT-06, PT-07, PT-08, PT-09, PT-11, PT-25, PT-26, PT-27, PT-28, PT-31."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import SipanelSaleCase


@tagged('post_install', '-at_install', 'sipanel')
class TestQuoteEngine(SipanelSaleCase):

    def test_pt01_add_scope_snapshot_and_cost(self):
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id.sudo()
        self.assertEqual(rev.state, 'working')
        self.assertEqual(rev.scope_qty, 85.0)
        self.assertEqual(len(rev.component_ids), 8)
        q = {c.product_id: c.final_qty for c in rev.component_ids.filtered(lambda c: c.basis != 'percent_of_cost' and c.basis != 'percent_of_quantity')}
        self.assertEqual(q[self.p_gutter], 85.0)
        self.assertEqual(q[self.p_bracket], 170.0)
        self.assertEqual(q[self.p_screw], 340.0)
        self.assertEqual(q[self.p_sealant], 10.0)
        self.assertEqual(q[self.p_labour], 8.0)
        self.assertEqual(q[self.p_crane], 1.0)
        allow = rev.component_ids.filtered(lambda c: c.basis == 'percent_of_quantity')
        self.assertEqual(allow.final_qty, 17.0)
        cont = rev.component_ids.filtered(lambda c: c.basis == 'percent_of_cost')
        self.assertEqual(cont.final_qty, 0.0)
        self.assertEqual(cont.qty_kind, 'none')
        self.assertAlmostEqual(cont.cost_amount, 187.0, places=4)
        self.assertAlmostEqual(rev.direct_cost_total, 10547.0, places=4)
        self.assertAlmostEqual(rev.derived_cost_total, 187.0, places=4)
        self.assertAlmostEqual(rev.eligible_cost_total, 10734.0, places=4)
        self.assertTrue(scope.anchor_line_id.sipanel_is_anchor)
        self.assertEqual(scope.anchor_line_id.product_id, self.p_anchor)
        self.assertEqual(scope.anchor_line_id.product_uom_qty, 85.0)
        self.assertFalse(scope.anchor_line_id.display_type)
        self.assertTrue(rev.final_note)
        self.assertIn('Gutter', rev.final_note)
        self.assertNotIn('Screw allowance', rev.final_note)
        # no execution records exist (module 3 may or may not be installed)
        if 'sipanel.execution.demand' in self.env:
            self.assertFalse(self.env['sipanel.execution.demand'].search([('component_id', 'in', rev.component_ids.ids)]))
        # a second scope cannot claim the same anchor
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['sipanel.quote.scope'].create({'order_id': order.id, 'anchor_line_id': scope.anchor_line_id.id})

    def test_pt02_version_isolation(self):
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id.sudo()
        before = [c._snapshot_payload() for c in rev.component_ids.sorted('id')]
        # publish V2 with an added outlet + change product cost and labels
        v2 = self.env['sipanel.scope.version'].browse(self.v1.action_new_version()['res_id'])
        self.env['sipanel.scope.recipe.line'].create({'version_id': v2.id, 'product_id': self.p_bracket.id, 'uom_id': self.uom_unit.id,
                                                      'dimension_family': 'count', 'basis': 'fixed', 'fixed_qty': 1, 'activity_id': self.act_ins.id,
                                                      'execution_mode': 'stock_issue', 'customer_label': 'Outlet', 'customer_eligible': True})
        v2.write({'customer_label': 'Gutter accessories V2'})
        v2.action_release()
        self.p_gutter.write({'standard_price': 999.0})
        rev.invalidate_recordset()
        after = [c._snapshot_payload() for c in rev.component_ids.sorted('id')]
        self.assertEqual(before, after)
        self.assertEqual(rev.label_en, 'Gutter accessories')  # frozen snapshot, not the renamed master
        self.assertAlmostEqual(rev.eligible_cost_total, 10734.0, places=4)
        self.assertEqual(scope.source_version_id, self.v1)

    def test_pt03_dimensional_quantity(self):
        order_cm, scope_cm = self._make_order(8500.0, uom=self.uom_cm)
        order_m, scope_m = self._make_order(85.0, uom=self.uom_m)
        self.assertAlmostEqual(scope_cm.current_revision_id.scope_qty, 85.0, places=6)
        self.assertAlmostEqual(scope_cm.current_revision_id.sudo().eligible_cost_total, scope_m.current_revision_id.sudo().eligible_cost_total, places=4)
        with self.assertRaises(ValidationError):
            self._make_order(85.0, uom=self.uom_hour)
        # incompatible family is refused even when a factor chain exists only in theory
        with self.assertRaises(ValidationError):
            self._make_order(1.0, uom=self.uom_unit)

    def test_pt04_override_retained_and_stale(self):
        order, scope = self._make_order(85.0)
        bracket = self._comp(scope, self.p_bracket)
        self.assertEqual(bracket.final_qty, 170.0)
        with self.assertRaises(ValidationError):
            bracket.write({'qty_override': True, 'override_qty': 180.0})
        bracket.write({'qty_override': True, 'override_qty': 180.0, 'override_reason': 'site survey'})
        self.assertEqual(bracket.final_qty, 180.0)
        self.assertFalse(bracket.override_stale)
        self.assertEqual(bracket.override_before_qty, 170.0)
        scope.anchor_line_id.write({'product_uom_qty': 90.0})
        self.assertEqual(scope.current_revision_id.scope_qty, 90.0)
        self.assertEqual(bracket.final_qty, 180.0, "override value is retained")
        self.assertEqual(bracket.calc_rounded_qty, 180.0)
        self.assertTrue(bracket.override_stale, "driver change flags the override")
        issues = {i['code'] for i in scope._readiness_issues() if i['level'] == 'block'}
        self.assertIn('OVERRIDE_STALE', issues)
        with self.assertRaises(UserError):
            order.action_quotation_sent()
        bracket.action_confirm_override()
        self.assertFalse(bracket.override_stale)
        self.assertEqual(bracket.final_qty, 180.0)
        audit = self.env['sipanel.scope.audit.event'].search([('res_model', '=', bracket._name), ('res_id', '=', bracket.id)])
        self.assertEqual(set(audit.mapped('action')) >= {'override_qty', 'override_confirmed'}, True)

    def test_pt05_percent_validation(self):
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id
        screw = self._comp(scope, self.p_screw, 'per_scope_qty')
        allow = self._comp(scope, basis='percent_of_quantity')
        gutter = self._comp(scope, self.p_gutter, 'per_scope_qty')
        with self.assertRaises(ValidationError):
            allow.write({'base_component_ids': [(6, 0, [allow.id])]})
        new = self.env['sipanel.quote.scope.component'].create({'revision_id': rev.id, 'product_id': self.p_screw.id, 'uom_id': self.uom_unit.id,
                                                                'dimension_family': 'count', 'basis': 'percent_of_quantity', 'percent': 10,
                                                                'base_component_ids': [(6, 0, [screw.id])], 'activity_id': self.act_ins.id})
        with self.assertRaises(ValidationError):
            new.write({'base_component_ids': [(6, 0, [allow.id])]})  # percent on percent
        with self.assertRaises(ValidationError):
            new.write({'base_component_ids': [(6, 0, [screw.id, gutter.id])]})  # mixed unit
        order2, scope2 = self._make_order(10.0)
        other = self._comp(scope2, self.p_screw, 'per_scope_qty')
        with self.assertRaises(ValidationError):
            new.write({'base_component_ids': [(6, 0, [other.id])]})  # cross scope
        # cycle through two percent lines is impossible (percent-on-percent) — assert derived cost has no demand qty
        cont = self._comp(scope, basis='percent_of_cost')
        self.assertEqual(cont.final_qty, 0.0)
        self.assertEqual(cont.qty_kind, 'none')

    def test_pt06_split_with_dependent(self):
        order, scope = self._make_order(85.0)
        screw = self._comp(scope, self.p_screw, 'per_scope_qty')
        wiz = self.env['sipanel.wizard.split.move'].with_context(default_source_scope_id=scope.id).create({
            'source_scope_id': scope.id, 'destination_mode': 'new', 'new_label': 'Screws', 'dependent_policy': 'move_dependents'})
        wiz.line_ids.filtered(lambda l: l.component_id == screw).write({'move_all': True})
        res = wiz.action_split()
        dest = self.env['sipanel.quote.scope'].browse(res['res_id'])
        src_rev = scope.current_revision_id.sudo()
        dst_rev = dest.current_revision_id.sudo()
        self.assertAlmostEqual(src_rev.eligible_cost_total, 10377.0, places=4)
        self.assertAlmostEqual(dst_rev.eligible_cost_total, 357.0, places=4)
        self.assertAlmostEqual(src_rev.eligible_cost_total + dst_rev.eligible_cost_total, 10734.0, places=4)
        moved = dst_rev.component_ids
        self.assertEqual(len(moved), 2)
        self.assertTrue(all(m.moved_from_id for m in moved))
        self.assertEqual(screw.active_state, 'tombstone')
        self.assertEqual(screw.origin, 'transferred')
        self.assertEqual(screw.moved_to_id.revision_id, dst_rev)
        self.assertNotEqual(screw.moved_to_id.occurrence_uid, screw.occurrence_uid)
        self.assertEqual(len(src_rev.component_ids.filtered(lambda c: c.active_state == 'active')), 6)
        self.assertNotEqual(dest.anchor_line_id, scope.anchor_line_id)
        self.assertTrue(src_rev.note_stale or not src_rev.note_reviewed)

    def test_pt07_split_alone_blocked(self):
        order, scope = self._make_order(85.0)
        screw = self._comp(scope, self.p_screw, 'per_scope_qty')
        wiz = self.env['sipanel.wizard.split.move'].with_context(default_source_scope_id=scope.id).create({
            'source_scope_id': scope.id, 'destination_mode': 'new', 'dependent_policy': 'block'})
        wiz.line_ids.filtered(lambda l: l.component_id == screw).write({'move_all': True})
        with self.assertRaises(UserError) as cm:
            wiz.action_split()
        self.assertIn('depend', str(cm.exception))
        self.assertEqual(screw.active_state, 'active')
        self.assertEqual(len(order.sipanel_quote_scope_ids), 1)

    def test_pt08_note_stale(self):
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id
        rev.write({'final_note': 'Manually edited customer note'})
        self.assertTrue(rev.note_manually_edited)
        self.assertEqual(scope.anchor_line_id.name, 'Manually edited customer note')
        self.assertFalse(rev.note_stale)
        bracket = self._comp(scope, self.p_bracket)
        # snapshot component: the note is built from the resolved snapshot label
        bracket.write({'customer_label_resolved': 'Heavy bracket'})
        self.assertTrue(rev.note_stale)
        self.assertEqual(rev.final_note, 'Manually edited customer note')
        rev.write({'note_reviewed': False}) if rev.note_reviewed else None
        self.assertIn('NOTE_STALE', {i['code'] for i in scope._readiness_issues() if i['level'] == 'block'})
        with self.assertRaises(UserError):
            order.action_quotation_sent()
        rev.action_mark_note_reviewed()
        self.assertFalse(rev.note_stale)
        # editing the anchor line name in the native form writes back into the working revision
        scope.anchor_line_id.write({'name': 'Edited on the line'})
        self.assertEqual(rev.final_note, 'Edited on the line')

    def test_pt09_duplicate_independent(self):
        order, scope = self._make_order(85.0)
        order.action_quotation_sent()
        rev = scope.current_revision_id
        self.assertEqual(rev.state, 'sent_sealed')
        self.assertTrue(rev.artifact_ids)
        new_order = order.copy()
        self.assertEqual(len(new_order.sipanel_quote_scope_ids), 1)
        ns = new_order.sipanel_quote_scope_ids
        nrev = ns.current_revision_id
        self.assertEqual(nrev.state, 'working')
        self.assertEqual(nrev.revision, 1)
        self.assertFalse(nrev.artifact_ids)
        self.assertFalse(nrev.sealed_hash)
        self.assertFalse(ns.accepted_revision_id)
        self.assertEqual(ns.source_version_id, self.v1)
        self.assertEqual(len(nrev.component_ids), 8)
        self.assertFalse(set(nrev.component_ids.mapped('occurrence_uid')) & set(rev.component_ids.mapped('occurrence_uid')))
        self._comp(ns, self.p_bracket).write({'rate': 3.0})
        self.assertEqual(self._comp(scope, self.p_bracket).rate, 2.0)
        self.assertEqual(rev.state, 'sent_sealed')

    def test_pt11_customer_scope_and_internal_only(self):
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id.sudo()
        sealant = self._comp(scope, self.p_sealant)
        wiz = self.env['sipanel.wizard.treatment.transition'].create({'kind': 'axes', 'component_id': sealant.id, 'responsibility': 'customer', 'reason': 'customer supplies sealant'})
        wiz.action_apply()
        self.assertEqual(sealant.cost_status, 'not_applicable')
        self.assertEqual(sealant.treatment_preset, 'customer_scope')
        self.assertEqual(sealant.execution_mode, 'no_action')
        self.assertFalse(sealant.eligible_for_rollup)
        self.assertAlmostEqual(rev.eligible_cost_total, 10734.0 - 200.0, places=4)
        # internal-only allowance: cost included but not in customer payload
        allow = self._comp(scope, basis='percent_of_quantity')
        self.assertEqual(allow.disclosure, 'internal_only')
        self.assertTrue(allow.eligible_for_rollup)
        self.assertIsNone(allow._customer_payload('en_US'))
        rev.action_generate_note(accept=True)
        self.assertNotIn('allowance', (rev.final_note or '').lower())

    def test_pt25_foreign_currency_blocked(self):
        eur = self.env.ref('base.EUR')
        if eur == self.company.currency_id:
            eur = self.env.ref('base.USD')
        eur.active = True
        pricelist = self.env['product.pricelist'].create({'name': 'SIPANEL-PT FX', 'currency_id': eur.id})
        order = self.env['sale.order'].create({'partner_id': self.partner.id, 'pricelist_id': pricelist.id})
        with self.assertRaises(UserError):
            self.env['sipanel.quote.scope']._create_from_version(order, self.v1, 85.0, self.uom_m)
        order2, scope = self._make_order(85.0)
        with self.assertRaises(UserError):
            order2.write({'pricelist_id': pricelist.id})
        self.assertEqual(scope.current_revision_id.fx_rate, 1.0)
        self.assertEqual(scope.current_revision_id.fx_source, 'company_currency')

    def test_pt26_cost_unit_conversion(self):
        dozen = self.env['uom.uom'].create({'name': 'SIPANEL-PT Dozen', 'relative_factor': 12.0, 'relative_uom_id': self.uom_unit.id})
        self.env['sipanel.uom.family'].create({'uom_id': dozen.id, 'family': 'count'})
        p_dozen = self.env['product.product'].create({'name': 'SIPANEL-PT Dozen product', 'type': 'consu', 'uom_id': dozen.id, 'standard_price': 24.0})
        order, scope = self._make_order(85.0)
        c = self.env['sipanel.quote.scope.component'].sudo().create(dict(
            revision_id=scope.current_revision_id.id, product_id=p_dozen.id, uom_id=self.uom_unit.id, dimension_family='count',
            basis='fixed', fixed_qty=6.0, activity_id=self.act_ins.id,
            **self.env['sipanel.quote.scope.component']._product_cost_snapshot_vals(p_dozen, self.company, self.uom_unit)))
        self.assertAlmostEqual(c.cost_uom_factor, 1.0 / 12.0, places=6)
        self.assertAlmostEqual(c.cost_amount, 6 * 24.0 / 12.0, places=4)
        # incompatible cost unit is refused, not silently accepted
        with self.assertRaises(ValidationError):
            self.env['sipanel.quote.scope.component']._product_cost_snapshot_vals(p_dozen, self.company, self.uom_m)

    def test_pt27_pricing_and_margin(self):
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id.sudo()
        line = scope.anchor_line_id
        line.write({'price_unit': 12000.0 / 85.0, 'discount': 10.0, 'tax_ids': [(5, 0, 0)]})
        self.assertAlmostEqual(rev.net_revenue_projection, 10800.0, delta=0.5)  # price_unit is rounded to Product Price precision
        self.assertAlmostEqual(rev.margin_amount, 66.0, delta=0.5)
        self.assertFalse(rev.margin_percent_na)
        line.write({'price_unit': 0.0})
        self.assertTrue(rev.margin_percent_na)
        self.assertEqual(rev.margin_percent, 0.0)
        # Apply price by target margin
        wiz = self.env['sipanel.wizard.apply.price'].create({'quote_scope_id': scope.id, 'mode': 'margin', 'value': 10.55})
        self.assertAlmostEqual(wiz.sudo().suggested_revenue, 10734.0 / (1 - 0.1055), places=2)
        wiz.action_apply()
        self.assertAlmostEqual(line.price_subtotal, 10734.0 / (1 - 0.1055) * 0.9, delta=0.5)
        # Cost refresh never changes price
        before = line.price_unit
        self.p_bracket.write({'standard_price': 6.0})
        w = self.env['sipanel.wizard.refresh.cost'].with_context(default_revision_id=rev.id).create({'revision_id': rev.id})
        w.action_apply()
        self.assertEqual(line.price_unit, before)
        self.assertAlmostEqual(self._comp(scope, self.p_bracket).sudo().unit_cost, 6.0)
        # negative margin => waiver required for send
        line.write({'price_unit': 1.0, 'discount': 0.0})
        self.assertIn('NEGATIVE_MARGIN', {i['code'] for i in scope._readiness_issues()})
        with self.assertRaises(UserError):
            order.action_quotation_sent()
        waiver = self.env['sipanel.quote.waiver'].create({'revision_id': rev.id, 'waiver_type': 'negative_margin', 'reason': 'strategic'})
        self.assertEqual(waiver.state, 'pending')
        with self.assertRaises(UserError):
            waiver.write({'sales_approver_id': self.sales_mgr.id})
        with self.assertRaises(Exception):
            waiver.with_user(self.sales).action_approve_sales()
        waiver.with_user(self.sales_mgr).action_approve_sales()
        self.assertEqual(waiver.state, 'pending')
        waiver.with_user(self.finance).action_approve_finance()
        self.assertEqual(waiver.state, 'approved')
        order.action_quotation_sent()
        self.assertEqual(rev.state, 'sent_sealed')

    def test_pt28_known_zero_vs_missing(self):
        zero_p = self.env['product.product'].create({'name': 'SIPANEL-PT free item', 'type': 'consu', 'uom_id': self.uom_unit.id, 'standard_price': 0.0})
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id
        Comp = self.env['sipanel.quote.scope.component'].sudo()
        c = Comp.create(dict(revision_id=rev.id, product_id=zero_p.id, uom_id=self.uom_unit.id, dimension_family='count', basis='fixed', fixed_qty=1,
                             activity_id=self.act_ins.id, **Comp._product_cost_snapshot_vals(zero_p, self.company, self.uom_unit)))
        self.assertEqual(c.cost_status, 'missing')
        self.assertEqual(rev.sudo().missing_cost_count, 1)
        self.assertIn('MISSING_COST', {i['code'] for i in scope._readiness_issues() if i['level'] == 'block'})
        c.write({'known_zero_reason': 'free of charge sample'})
        self.assertEqual(c.cost_status, 'known_zero')
        self.assertEqual(rev.sudo().missing_cost_count, 0)
        self.assertNotIn('MISSING_COST', {i['code'] for i in scope._readiness_issues()})
        # estimate_only without product is always missing
        e = Comp.create({'revision_id': rev.id, 'kind': 'estimate_only', 'description': 'unknown flashing', 'uom_id': self.uom_m.id,
                         'dimension_family': 'length', 'basis': 'fixed', 'fixed_qty': 2, 'resolution_state': 'open', 'resolution_owner_id': self.estimator.id})
        self.assertEqual(e.cost_status, 'missing')

    def test_pt31_ordinary_sales_untouched(self):
        order = self.env['sale.order'].create({'partner_id': self.partner.id, 'origin': 'SIPANEL-PT-ORDINARY'})
        line = self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.p_bracket.id, 'product_uom_qty': 3})
        section = self.env['sale.order.line'].create({'order_id': order.id, 'display_type': 'line_section', 'name': 'S', 'is_optional': True})
        self.assertFalse(order.sipanel_has_scopes)
        self.assertFalse(line.sipanel_is_anchor)
        line.write({'product_uom_qty': 5, 'price_unit': 7})
        section.write({'sequence': 1})
        section.unlink()
        order.action_quotation_sent()
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertFalse(order.sipanel_current_seal_hash)
        copy = order.copy()
        self.assertFalse(copy.sipanel_quote_scope_ids)
