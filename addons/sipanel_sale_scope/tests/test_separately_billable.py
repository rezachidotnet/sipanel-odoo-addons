# -*- coding: utf-8 -*-
"""STEP 2B: separately-billable Sale Lines and Invoice Lines.

`placement == 'own_line'` is the installed representation of "billed
separately". These tests exercise it through the orthogonal axes, never through
a product category and never through a new enum.
"""
import uuid
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard_ctx
from odoo.addons.sipanel_commercial_scope_core.tests.common import set_translation

from .common import SipanelSaleCase


class SeparatelyBillableCase(SipanelSaleCase):
    """A master carrying one component of every treatment shape."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['res.lang'].sudo()._activate_lang('fa_IR')
        for product in (cls.p_gutter, cls.p_bracket, cls.p_crane, cls.p_labour):
            product.write({'list_price': 100.0, 'invoice_policy': 'order'})
        cls.sb_scope, cls.sb_v1 = cls._make_sb_master()

    @classmethod
    def _make_sb_master(cls):
        env = cls.env
        scope = env['sipanel.scope'].create({
            'code': f'SIPANEL-PT-SB-{uuid.uuid4().hex[:8]}',
            'name': 'SIPANEL-PT separately billable master',
            'owner_user_id': cls.steward.id})
        version = env['sipanel.scope.version'].create({
            'scope_id': scope.id, 'customer_label': 'Gutter accessories',
            'base_uom_id': cls.uom_m.id, 'dimension_family': 'length',
            'anchor_product_id': cls.p_anchor.id,
            'anchor_owner_mode': 'component_bridge_owner', 'all_systems': True})
        L = env['sipanel.scope.recipe.line']
        base = {'version_id': version.id, 'customer_eligible': True}

        # 1. INCLUDED - paid for through the anchor price
        cls.l_included = L.create(dict(
            base, sequence=10, product_id=cls.p_gutter.id, uom_id=cls.uom_m.id,
            dimension_family='length', basis='per_scope_qty', rate=1.0,
            activity_id=cls.act_ins.id, execution_mode='stock_issue',
            placement='included_parent', customer_label='Galvanised gutter'))
        # 2. SEPARATELY BILLABLE, product-backed
        cls.l_sep = L.create(dict(
            base, sequence=20, product_id=cls.p_bracket.id, uom_id=cls.uom_unit.id,
            dimension_family='count', basis='per_scope_qty', rate=2.0,
            activity_id=cls.act_ins.id, execution_mode='stock_issue',
            placement='own_line', customer_label='Wall bracket'))
        # 3. PROVISIONAL + own line
        cls.l_prov = L.create(dict(
            base, sequence=30, product_id=cls.p_crane.id, uom_id=cls.uom_unit.id,
            dimension_family='count', basis='fixed', fixed_qty=1.0,
            activity_id=cls.act_eqp.id, execution_mode='equipment_service',
            placement='own_line', customer_label='Crane'))
        # 4. CUSTOMER SCOPE - customer supplies it, never our revenue
        cls.l_cust = L.create(dict(
            base, sequence=40, product_id=cls.p_sealant.id, uom_id=cls.uom_unit.id,
            dimension_family='count', basis='fixed', fixed_qty=5.0,
            execution_mode='no_action', no_action_reason='customer_responsibility',
            responsibility='customer', placement='own_line', customer_label='Customer sealant'))
        # 5. INTERNAL ONLY - never shown, never billed
        cls.l_int = L.create(dict(
            base, sequence=50, product_id=cls.p_screw.id, uom_id=cls.uom_unit.id,
            dimension_family='count', basis='fixed', fixed_qty=10.0,
            activity_id=cls.act_ins.id, execution_mode='stock_issue',
            customer_eligible=False, disclosure='internal_only', placement='own_line',
            customer_label='Internal screws'))
        for line, fa in ((cls.l_included, 'ناودان گالوانیزه'), (cls.l_sep, 'بست دیواری'),
                         (cls.l_prov, 'جرثقیل'), (cls.l_cust, 'درزگیر کارفرما'),
                         (cls.l_int, 'پیچ داخلی')):
            set_translation(line, 'customer_label', en=line.customer_label, fa=fa)
        set_translation(version, 'customer_label', en='Gutter accessories', fa='متعلقات آبرو')
        version.action_release()
        return scope, version

    # ------------------------------------------------------------------ helpers
    def _order(self, lang='en_US'):
        partner = self.env['res.partner'].create({
            'name': f'SIPANEL-PT-SB customer {lang} {uuid.uuid4().hex[:6]}',
            'lang': lang, 'email': False})
        return self.env['sale.order'].with_user(self.estimator).create({
            'partner_id': partner.id, 'origin': 'SIPANEL-PT-SB'})

    def _add_scope(self, order=None, optional=False, qty=12.0, section=None):
        order = order or self._order()
        if optional and section is None:
            section = self.env['sale.order.line'].create({
                'order_id': order.id, 'display_type': 'line_section',
                'name': 'Options', 'is_optional': True, 'sequence': 100})
        scope = self.env['sipanel.quote.scope'].with_user(self.estimator)._create_from_version(
            order, self.sb_v1, qty, self.uom_m, optional=optional, section_line=section)
        # The master recipe line carries no provisional_basis field, so PROVISIONAL is
        # expressed on the component - the same way STEP 1C/1D did it.
        self._comp_of(scope.current_revision_id, self.l_prov).write({
            'certainty': 'provisional',
            'provisional_basis': 'Initial allowance; confirmed after the site survey'})
        # mutating a component correctly marks the note stale; the fixture is not
        # testing staleness, so bring the note back in step
        scope.current_revision_id.action_generate_note(accept=True)
        return scope

    @staticmethod
    def _comp_of(rev, recipe_line):
        return rev.component_ids.filtered(lambda c: c.source_line_id == recipe_line)

    def _lines_of(self, rev):
        return self.env['sale.order.line'].search([
            ('sipanel_source_revision_id', '=', rev.id), ('sipanel_is_generated', '=', True)])

    def _make_sendable(self, rev):
        """Clear the blockers that are not the subject of the test."""
        prov = self._comp_of(rev, self.l_prov)
        prov.action_set_manual_sell_price(250.0)
        rev.action_generate_note(accept=True)
        return rev


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill')
class TestProjection(SeparatelyBillableCase):
    """(1)-(7) which components become a line, and exactly once."""

    def test_eligible_own_line_component_creates_exactly_one_sale_line(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_sep)
        lines = self._lines_of(rev).filtered(lambda l: l.sipanel_source_component_id == comp)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.product_id, self.p_bracket)
        self.assertEqual(lines.product_uom_qty, comp.final_qty)
        self.assertTrue(lines.sipanel_origin_key)

    def test_repeated_synchronisation_creates_no_duplicate(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        before = self._lines_of(rev).ids
        for _i in range(4):
            rev._sync_separately_billable_lines()
        scope.order_id.action_sipanel_sync_scope_lines()
        self.assertEqual(self._lines_of(rev).ids, before)

    def test_database_constraint_refuses_a_second_line_for_one_component(self):
        """Belt and braces: the upsert is idempotent, and the database says so too."""
        from psycopg2 import IntegrityError
        scope = self._add_scope()
        rev = scope.current_revision_id
        line = self._lines_of(rev)[:1]
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['sale.order.line'].with_context(**guard_ctx('sipanel_projection')).create({
                    'order_id': scope.order_id.id, 'product_id': self.p_bracket.id,
                    'product_uom_qty': 1.0, 'sipanel_is_generated': True,
                    'sipanel_origin_key': line.sipanel_origin_key,
                })

    def test_included_component_creates_no_separate_line(self):
        rev = self._add_scope().current_revision_id
        comp = self._comp_of(rev, self.l_included)
        self.assertFalse(comp.separately_billable)
        self.assertFalse(self._lines_of(rev).filtered(
            lambda l: l.sipanel_source_component_id == comp))

    def test_internal_only_creates_no_separate_line(self):
        rev = self._add_scope().current_revision_id
        comp = self._comp_of(rev, self.l_int)
        self.assertEqual(comp.disclosure, 'internal_only')
        self.assertFalse(comp.separately_billable,
                         'internal-only must never be customer revenue, whatever its placement')
        self.assertFalse(self._lines_of(rev).filtered(
            lambda l: l.sipanel_source_component_id == comp))

    def test_customer_scope_creates_no_separate_line(self):
        rev = self._add_scope().current_revision_id
        comp = self._comp_of(rev, self.l_cust)
        self.assertEqual(comp.responsibility, 'customer')
        self.assertFalse(comp.separately_billable)
        self.assertFalse(self._lines_of(rev).filtered(
            lambda l: l.sipanel_source_component_id == comp))

    def test_deactivated_component_line_is_retired(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_sep)
        self.assertTrue(self._lines_of(rev).filtered(lambda l: l.sipanel_source_component_id == comp))
        comp.action_tombstone()
        self.assertFalse(
            self._lines_of(rev).filtered(lambda l: l.sipanel_source_component_id == comp),
            'a tombstoned component must not keep a live revenue line')

    def test_product_backed_mapping_uses_the_component_product(self):
        rev = self._add_scope().current_revision_id
        line = self._lines_of(rev).filtered(
            lambda l: l.sipanel_source_component_id == self._comp_of(rev, self.l_sep))
        self.assertEqual(line.product_id, self._comp_of(rev, self.l_sep).product_id)
        self.assertEqual(line.product_uom_id, self._comp_of(rev, self.l_sep).uom_id)


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill')
class TestPricingReadiness(SeparatelyBillableCase):
    """(8)(9)(10) product and price readiness."""

    def test_estimate_only_without_product_blocks_readiness(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_sep)
        comp.write({'kind': 'estimate_only', 'product_id': False,
                    'resolution_owner_id': self.steward.id, 'description': 'to resolve'})
        codes = {c for c, _m in rev._projection_blocking_issues()}
        self.assertIn('SB_ESTIMATE_PRODUCT', codes)
        blocking = {i['code'] for i in scope._readiness_issues() if i['level'] == 'block'}
        self.assertIn('SB_ESTIMATE_PRODUCT', blocking)
        self.assertFalse(
            self._lines_of(rev).filtered(lambda l: l.sipanel_source_component_id == comp),
            'an estimate with no product must not silently become a generic invoice line')

    def test_missing_selling_price_blocks_seal(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_sep)
        comp.write({'sell_price_source': 'manual', 'sell_price_unit': 0.0,
                    'sell_known_zero_reason': False})
        self.assertEqual(comp.sell_price_status, 'missing')
        blocking = {i['code'] for i in scope._readiness_issues() if i['level'] == 'block'}
        self.assertIn('SB_PRICE_MISSING', blocking)
        with self.assertRaises(UserError):
            scope.order_id._sipanel_check_readiness()

    def test_known_zero_selling_price_is_distinguishable_and_allowed(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_sep)
        comp.action_set_manual_sell_price(0.0, reason='Included free of charge per contract')
        self.assertEqual(comp.sell_price_status, 'known_zero')
        codes = {c for c, _m in rev._projection_blocking_issues()}
        self.assertNotIn('SB_PRICE_MISSING', codes)
        line = self._lines_of(rev).filtered(lambda l: l.sipanel_source_component_id == comp)
        self.assertEqual(line.price_unit, 0.0)

    def test_price_status_is_not_applicable_for_an_included_component(self):
        rev = self._add_scope().current_revision_id
        comp = self._comp_of(rev, self.l_included)
        self.assertEqual(comp.sell_price_status, 'not_applicable',
                         'an included component is paid through the anchor, not priced on its own')

    def test_governed_manual_price_wins_over_the_pricelist(self):
        rev = self._add_scope().current_revision_id
        comp = self._comp_of(rev, self.l_sep)
        comp.action_set_manual_sell_price(777.0)
        line = self._lines_of(rev).filtered(lambda l: l.sipanel_source_component_id == comp)
        self.assertEqual(line.price_unit, 777.0)
        self.assertEqual(line.sipanel_price_provenance, 'manual:known')


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill')
class TestAmountsAndReconciliation(SeparatelyBillableCase):
    """(11)(12)(13) money."""

    def test_native_taxes_apply_to_the_generated_line(self):
        tax = self.env['account.tax'].create({
            'name': 'SIPANEL-PT-SB VAT', 'amount_type': 'percent', 'amount': 9.0,
            'type_tax_use': 'sale'})
        self.p_bracket.write({'taxes_id': [(6, 0, [tax.id])]})
        rev = self._add_scope().current_revision_id
        line = self._lines_of(rev).filtered(
            lambda l: l.sipanel_source_component_id == self._comp_of(rev, self.l_sep))
        self.assertIn(tax, line.tax_ids,
                      'taxes must come from the product and the fiscal position, never hardcoded')

    def test_anchor_total_excludes_the_separate_line_amount(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        anchor = scope.anchor_line_id
        anchor.write({'price_unit': 1000.0})
        line = self._lines_of(rev).filtered(
            lambda l: l.sipanel_source_component_id == self._comp_of(rev, self.l_sep))
        self.assertEqual(rev.anchor_amount, anchor.price_subtotal)
        self.assertNotIn(line.id, [anchor.id])
        self.assertAlmostEqual(rev.separate_amount, sum(self._lines_of(rev).mapped('price_subtotal')), 2)
        # the order total is the anchor plus the separate lines, nothing counted twice
        self.assertAlmostEqual(
            scope.order_id.amount_untaxed,
            anchor.price_subtotal + sum(self._lines_of(rev).mapped('price_subtotal')), 2)

    def test_reconciliation_reports_no_double_billing(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        recon = rev.reconciliation_json
        self.assertTrue(rev.reconciliation_ok, recon.get('problems'))
        self.assertEqual(recon['problems'], [])
        # every separately billable component appears exactly once
        keys = [r['component'] for r in recon['rows']]
        self.assertEqual(len(keys), len(set(keys)))
        billable = rev.component_ids.filtered('separately_billable')
        self.assertEqual(recon['separately_billable_components'], len(billable))

    def test_a_component_is_never_both_included_and_separate(self):
        rev = self._add_scope().current_revision_id
        for comp in rev.component_ids:
            self.assertFalse(comp.placement == 'included_parent' and comp.separately_billable)

    def test_included_component_stays_out_of_the_customer_note_bullets(self):
        """The note must not repeat a component that now has its own line."""
        rev = self._add_scope(order=self._order('fa_IR')).current_revision_id
        note = rev.final_note or ''
        self.assertIn('ناودان گالوانیزه', note, 'an included component is still described in the note')
        self.assertNotIn('بست دیواری', note,
                         'a separately billable component is a real line, not a note bullet too')


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill')
class TestOptionalAndProvisional(SeparatelyBillableCase):
    """(14)(15)(16) orthogonal combinations."""

    def test_optional_unaccepted_line_is_quantity_zero(self):
        scope = self._add_scope(optional=True)
        rev = scope.current_revision_id
        self.assertEqual(scope.acceptance_state, 'offered')
        line = self._lines_of(rev).filtered(
            lambda l: l.sipanel_source_component_id == self._comp_of(rev, self.l_sep))
        self.assertTrue(line, 'an option is an ordinary line at quantity zero')
        self.assertEqual(line.product_uom_qty, 0.0)
        self.assertEqual(line.qty_to_invoice, 0.0)

    def test_optional_acceptance_gives_the_line_its_governed_quantity(self):
        scope = self._add_scope(optional=True)
        rev = self._make_sendable(scope.current_revision_id)
        scope.order_id._sipanel_seal_current_revisions(actor='test')
        rev = scope.current_revision_id
        scope._transition_acceptance('accepted', actor='test')
        line = self._lines_of(rev).filtered(
            lambda l: l.sipanel_source_component_id == self._comp_of(rev, self.l_sep))
        self.assertGreater(line.product_uom_qty, 0.0)

    def test_optional_acceptance_is_idempotent(self):
        scope = self._add_scope(optional=True)
        rev = self._make_sendable(scope.current_revision_id)
        scope.order_id._sipanel_seal_current_revisions(actor='test')
        rev = scope.current_revision_id
        scope._transition_acceptance('accepted', actor='test')
        lines_before = self._lines_of(rev)
        qty_before = lines_before.mapped('product_uom_qty')
        scope._transition_acceptance('accepted', actor='test')
        scope._transition_acceptance('accepted', actor='test')
        self.assertEqual(self._lines_of(rev).ids, lines_before.ids)
        self.assertEqual(self._lines_of(rev).mapped('product_uom_qty'), qty_before)

    def test_provisional_line_is_gated_from_invoicing(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_prov)
        comp.action_set_manual_sell_price(250.0)
        line = self._lines_of(rev).filtered(lambda l: l.sipanel_source_component_id == comp)
        self.assertEqual(line.sipanel_invoice_gate, 'provisional')
        self.assertNotIn(line, scope.order_id._get_invoiceable_lines(),
                         'a provisional component must not invoice before it is resolved')

    def test_resolving_a_provisional_component_lifts_the_gate(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_prov)
        comp.action_set_manual_sell_price(250.0)
        comp.write({'certainty': 'firm'})
        line = self._lines_of(rev).filtered(lambda l: l.sipanel_source_component_id == comp)
        self.assertFalse(line.sipanel_invoice_gate)


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill')
class TestSecurityAndLifecycle(SeparatelyBillableCase):
    """(22)(23)(27) provenance cannot be forged, sealed lines cannot be edited."""

    def test_provenance_cannot_be_supplied_on_create(self):
        order = self._order()
        for payload in (
            {'sipanel_is_generated': True},
            {'sipanel_origin_key': 'forged'},
            {'sipanel_source_component_id': 1},
        ):
            with self.assertRaises(UserError):
                self.env['sale.order.line'].create(dict(
                    {'order_id': order.id, 'product_id': self.p_bracket.id,
                     'product_uom_qty': 1.0}, **payload))

    def test_provenance_cannot_be_written_by_sudo_import_or_rpc_context(self):
        rev = self._add_scope().current_revision_id
        line = self._lines_of(rev)[:1]
        for env_ in (line, line.sudo(),
                     line.with_context(sipanel_projection=True),        # bare context flag
                     line.with_context(import_file=True)):
            with self.assertRaises(UserError):
                env_.write({'sipanel_origin_key': 'forged'})
        self.assertNotEqual(line.sipanel_origin_key, 'forged')

    def test_sealed_generated_line_cannot_be_edited_directly(self):
        scope = self._add_scope()
        rev = self._make_sendable(scope.current_revision_id)
        scope.order_id._sipanel_seal_current_revisions(actor='test')
        line = self._lines_of(scope.current_revision_id)[:1]
        for vals in ({'price_unit': 1.0}, {'product_uom_qty': 99.0}, {'name': 'hand edited'}):
            with self.assertRaises(UserError):
                line.write(vals)

    def test_duplicate_quotation_gets_independent_projected_lines(self):
        scope = self._add_scope()
        rev = scope.current_revision_id
        original = self._lines_of(rev)
        self.assertTrue(original)
        copy_order = scope.order_id.copy()
        new_scope = copy_order.sipanel_quote_scope_ids
        new_rev = new_scope.current_revision_id
        new_lines = self._lines_of(new_rev)
        self.assertTrue(new_lines, 'the duplicate gets its own projection')
        self.assertFalse(set(new_lines.ids) & set(original.ids))
        self.assertFalse(set(new_lines.mapped('sipanel_origin_key'))
                         & set(original.mapped('sipanel_origin_key')),
                         'origin keys must be distinct so the unique index holds')
        self.assertEqual(new_lines.mapped('name'), original.mapped('name'),
                         'the duplicate keeps the frozen snapshot text')

    def test_cost_and_margin_stay_restricted_on_the_generated_line(self):
        rev = self._add_scope().current_revision_id
        line = self._lines_of(rev)[:1]
        text = ' '.join(str(line.read()[0].get(f) or '') for f in ('name', 'sipanel_price_provenance'))
        for forbidden in ('unit_cost', 'cost_amount', 'margin', 'standard_price'):
            self.assertNotIn(forbidden, text)


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill')
class TestSealDrift(SeparatelyBillableCase):
    """(24)(25)(26) P3: the three drift gates, proven not assumed."""

    def _sealed(self):
        scope = self._add_scope()
        self._make_sendable(scope.current_revision_id)
        scope.order_id._sipanel_seal_current_revisions(actor='test')
        return scope, scope.current_revision_id

    def test_seal_drift_blocks_acceptance(self):
        scope, rev = self._sealed()
        self.assertEqual(rev.state, 'sent_sealed')
        # a commercial change after sealing
        scope.anchor_line_id.with_context(**guard_ctx('sipanel_apply_price')).write({'price_unit': 4321.0})
        self.assertNotEqual(rev._current_seal_hash(), rev.sealed_hash)
        with self.assertRaises(UserError):
            rev.action_accept(reference='test')
        self.assertEqual(rev.state, 'sent_sealed', 'a refused acceptance must not change state')

    def test_seal_drift_blocks_confirmation(self):
        scope, rev = self._sealed()
        scope.anchor_line_id.with_context(**guard_ctx('sipanel_apply_price')).write({'price_unit': 4321.0})
        order = scope.order_id
        with self.assertRaises(UserError):
            order.with_context(**guard_ctx('sipanel_no_reseal')).action_confirm()

    def test_seal_drift_blocks_invoice_creation(self):
        scope, rev = self._sealed()
        scope.order_id.action_confirm()
        rev = scope.current_revision_id
        self.assertEqual(rev.state, 'accepted_sealed')
        scope.anchor_line_id.with_context(
            **guard_ctx('sipanel_governed_transition')).write({'price_unit': 9999.0})
        self.assertNotEqual(rev._current_seal_hash(), rev.sealed_hash)
        with self.assertRaises(UserError):
            scope.order_id._create_invoices()

    def test_commercial_change_after_sealing_requires_a_new_revision_and_reseal(self):
        scope, rev = self._sealed()
        comp = self._comp_of(rev, self.l_sep)
        with self.assertRaises(UserError):
            comp.action_set_manual_sell_price(10.0)
        new_rev = rev.action_amend()
        self.assertNotEqual(new_rev.id, rev.id)
        self.assertEqual(new_rev.state, 'working')
        self._comp_of(new_rev, self.l_sep).action_set_manual_sell_price(10.0)
        new_rev.action_generate_note(accept=True)
        new_rev.action_seal(actor='test')
        self.assertEqual(new_rev.state, 'sent_sealed')
        # prior artifacts and hashes are retained for audit
        self.assertTrue(rev.sealed_hash)
        self.assertTrue(rev.artifact_ids)

    def test_amendment_does_not_double_bill_the_same_component(self):
        """Found during the live pilot: an amendment creates a fresh projection,
        so the superseded revision's lines have to go or the same component is
        billed twice on one order."""
        scope, rev = self._sealed()
        order = scope.order_id
        comp = self._comp_of(rev, self.l_sep)
        before_total = order.amount_untaxed
        before_lines = self.env['sale.order.line'].search_count([
            ('order_id', '=', order.id), ('sipanel_is_generated', '=', True)])
        new_rev = rev.action_amend()
        after_lines = self.env['sale.order.line'].search_count([
            ('order_id', '=', order.id), ('sipanel_is_generated', '=', True)])
        self.assertEqual(after_lines, before_lines,
                         'an amendment must replace the projection, not add a second one')
        self.assertAlmostEqual(order.amount_untaxed, before_total, 2,
                               'an amendment alone must not change the commercial total')
        # exactly one live line per component, and it belongs to the new revision
        keys = self.env['sale.order.line'].search([
            ('order_id', '=', order.id), ('sipanel_is_generated', '=', True)])
        self.assertEqual(len(keys), len(set(keys.mapped('sipanel_origin_key'))))
        self.assertEqual(set(keys.mapped('sipanel_source_revision_id').ids), {new_rev.id})

    def test_prior_artifacts_are_retained_after_amendment(self):
        scope, rev = self._sealed()
        before = sorted(rev.artifact_ids.mapped('content_hash'))
        rev.action_amend()
        self.assertEqual(sorted(rev.artifact_ids.mapped('content_hash')), before)


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill')
class TestInvoiceFlow(SeparatelyBillableCase):
    """(17)(18)(19)(28)(29) quotation -> confirmation -> draft invoice."""

    def _confirmed(self, lang='en_US'):
        scope = self._add_scope(order=self._order(lang))
        rev = self._make_sendable(scope.current_revision_id)
        scope.anchor_line_id.write({'price_unit': 1000.0})
        scope.order_id._sipanel_seal_current_revisions(actor='test')
        scope.order_id.action_confirm()
        return scope, scope.current_revision_id

    def test_confirmed_order_produces_the_expected_invoice_line(self):
        scope, rev = self._confirmed()
        invoice = scope.order_id._create_invoices()
        comp = self._comp_of(rev, self.l_sep)
        sep_lines = invoice.invoice_line_ids.filtered(
            lambda l: l.sipanel_source_component_id == comp)
        self.assertEqual(len(sep_lines), 1)
        self.assertEqual(sep_lines.product_id, self.p_bracket)
        self.assertEqual(invoice.state, 'draft')

    def test_included_component_creates_no_invoice_line(self):
        scope, rev = self._confirmed()
        invoice = scope.order_id._create_invoices()
        included = self._comp_of(rev, self.l_included)
        self.assertFalse(invoice.invoice_line_ids.filtered(
            lambda l: l.sipanel_source_component_id == included))

    def test_customer_scope_and_internal_only_create_no_invoice_line(self):
        scope, rev = self._confirmed()
        invoice = scope.order_id._create_invoices()
        for recipe_line in (self.l_cust, self.l_int):
            comp = self._comp_of(rev, recipe_line)
            self.assertFalse(invoice.invoice_line_ids.filtered(
                lambda l: l.sipanel_source_component_id == comp))

    def test_provisional_component_creates_no_invoice_line(self):
        scope, rev = self._confirmed()
        invoice = scope.order_id._create_invoices()
        prov = self._comp_of(rev, self.l_prov)
        self.assertFalse(invoice.invoice_line_ids.filtered(
            lambda l: l.sipanel_source_component_id == prov),
            'a provisional component is held back from invoicing')

    def test_invoice_line_carries_source_provenance(self):
        scope, rev = self._confirmed()
        invoice = scope.order_id._create_invoices()
        comp = self._comp_of(rev, self.l_sep)
        line = invoice.invoice_line_ids.filtered(lambda l: l.sipanel_source_component_id == comp)
        self.assertEqual(line.sipanel_source_revision_id, rev)
        self.assertEqual(line.sipanel_source_quote_scope_id, scope)
        self.assertEqual(line.sipanel_source_scope_id, scope.source_scope_id)
        self.assertTrue(line.sipanel_origin_key)
        self.assertTrue(line.sipanel_source_line_id.sipanel_is_generated)

    def test_invoice_description_uses_the_frozen_resolved_translation(self):
        scope, rev = self._confirmed('fa_IR')
        invoice = scope.order_id._create_invoices()
        comp = self._comp_of(rev, self.l_sep)
        line = invoice.invoice_line_ids.filtered(lambda l: l.sipanel_source_component_id == comp)
        self.assertIn('بست دیواری', line.name)
        self.assertNotIn('Wall bracket', line.name)

    def test_english_quotation_invoices_in_english(self):
        scope, rev = self._confirmed('en_US')
        invoice = scope.order_id._create_invoices()
        comp = self._comp_of(rev, self.l_sep)
        line = invoice.invoice_line_ids.filtered(lambda l: l.sipanel_source_component_id == comp)
        self.assertIn('Wall bracket', line.name)
        self.assertNotIn('بست دیواری', line.name)

    def test_invoice_provenance_cannot_be_forged_on_a_manual_invoice(self):
        move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id})
        with self.assertRaises(UserError):
            self.env['account.move.line'].create({
                'move_id': move.id, 'name': 'forged', 'quantity': 1.0,
                'sipanel_origin_key': 'forged'})

    def test_generated_line_appears_in_the_customer_pdf_without_internal_data(self):
        import re
        scope, rev = self._confirmed('fa_IR')
        report = self.env.ref('sale.action_report_saleorder')
        html = report._render_qweb_html(report.report_name, scope.order_id.ids)[0]
        raw = html.decode() if isinstance(html, bytes) else html
        # compare against the VISIBLE text: the raw document carries the report
        # stylesheet, where "margin" is a CSS property and means nothing here
        body = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw, flags=re.S | re.I)
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', body))
        self.assertIn('بست دیواری', text, 'the separate customer line must be visible')
        internal = self._comp_of(rev, self.l_int)
        for forbidden in ('Internal screws', 'پیچ داخلی', 'unit_cost', 'cost_amount',
                          'eligible_cost', 'Margin', 'Cost'):
            self.assertNotIn(forbidden, text, f'{forbidden!r} leaked into the customer document')
        # and no internal cost figure appears anywhere in the document
        internal_cost = internal.sudo().unit_cost
        if internal_cost:
            self.assertNotIn(f'{internal_cost:.2f}', text)


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill')
class TestOperationalOwnership(SeparatelyBillableCase):
    """(20)(21) exactly one demand owner, no double booking."""

    def test_generated_line_does_not_add_a_second_procurement_owner(self):
        scope, rev = self._add_scope(), None
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_sep)
        self.assertEqual(comp.execution_owner, 'component_bridge_owner',
                         'the frozen ownership architecture decides this, not the new line')
        line = self._lines_of(rev).filtered(lambda l: l.sipanel_source_component_id == comp)
        # the native stock rule must skip a bridge-owned generated line
        self.assertTrue(line._action_launch_stock_rule(),
                        'the override returns cleanly and launches nothing for a bridge-owned line')

    def test_one_component_yields_one_execution_demand(self):
        scope = self._add_scope()
        rev = self._make_sendable(scope.current_revision_id)
        scope.anchor_line_id.write({'price_unit': 1000.0})
        scope.order_id._sipanel_seal_current_revisions(actor='test')
        scope.order_id.action_confirm()
        comp = self._comp_of(scope.current_revision_id, self.l_sep)
        demands = self.env['sipanel.execution.demand'].search([('component_id', '=', comp.id)])
        self.assertLessEqual(len(demands), 1,
                             'a component must never raise two operational demands')
        moves = self.env['stock.move'].search([
            ('sale_line_id', 'in', self._lines_of(scope.current_revision_id).ids)])
        self.assertFalse(moves, 'a bridge-owned generated line must not create its own stock move')


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill', 'sipanel_hardening')
class TestInvoiceProvenanceAuthorization(SeparatelyBillableCase):
    """STEP 2B-HARDENING: Scope provenance on an invoice line is writable only by
    the genuine Sale -> Invoice execution path.

    The previous implementation trusted a plain `sipanel_from_sale_invoice`
    context key and additionally exempted any payload carrying `sale_line_ids`.
    A context key can simply be sent by an RPC client, and `sale_line_ids` is
    ordinary user-writable data, so either was enough to forge provenance.
    """

    def setUp(self):
        super().setUp()
        self.move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id})

    def _line_vals(self, **extra):
        vals = {'move_id': self.move.id, 'name': 'forged', 'quantity': 1.0,
                'price_unit': 1.0, 'sipanel_origin_key': 'forged-key'}
        vals.update(extra)
        return vals

    def test_plain_create_with_provenance_is_refused(self):
        with self.assertRaises(UserError):
            self.env['account.move.line'].create(self._line_vals())

    def test_raw_sipanel_invoice_trace_context_is_refused(self):
        """A bare context flag, without the process-local token, proves nothing."""
        with self.assertRaises(UserError):
            self.env['account.move.line'].with_context(
                sipanel_invoice_trace=True).create(self._line_vals())

    def test_raw_sipanel_from_sale_invoice_context_is_refused(self):
        """The old escape hatch is gone and must stay gone."""
        with self.assertRaises(UserError):
            self.env['account.move.line'].with_context(
                sipanel_from_sale_invoice=True).create(self._line_vals())

    def test_forged_sale_line_ids_no_longer_exempts_the_payload(self):
        """Pointing at a real generated sale line must not confer its Scope."""
        rev = self._add_scope().current_revision_id
        real_line = self._lines_of(rev)[:1]
        self.assertTrue(real_line)
        with self.assertRaises(UserError):
            self.env['account.move.line'].create(self._line_vals(
                sale_line_ids=[(6, 0, real_line.ids)],
                sipanel_source_component_id=real_line.sipanel_source_component_id.id,
                sipanel_source_revision_id=rev.id))

    def test_sudo_is_refused(self):
        with self.assertRaises(UserError):
            self.env['account.move.line'].sudo().create(self._line_vals())

    def test_import_context_is_refused(self):
        with self.assertRaises(UserError):
            self.env['account.move.line'].with_context(
                import_file=True).create(self._line_vals())

    def test_guessed_token_is_refused(self):
        with self.assertRaises(UserError):
            self.env['account.move.line'].with_context(
                sipanel_invoice_trace=True,
                sipanel_guard_token='guessed').create(self._line_vals())

    def test_direct_write_of_provenance_remains_refused(self):
        line = self.env['account.move.line'].create({
            'move_id': self.move.id, 'name': 'ordinary', 'quantity': 1.0, 'price_unit': 1.0})
        for env_ in (line, line.sudo(), line.with_context(sipanel_invoice_trace=True),
                     line.with_context(import_file=True)):
            with self.assertRaises(UserError):
                env_.write({'sipanel_origin_key': 'forged-key'})
        self.assertFalse(line.sipanel_origin_key)

    def test_genuine_invoice_creation_still_carries_full_provenance(self):
        """The guard must not break the flow it exists to protect."""
        scope = self._add_scope()
        rev = self._make_sendable(scope.current_revision_id)
        scope.anchor_line_id.write({'price_unit': 1000.0})
        scope.order_id._sipanel_seal_current_revisions(actor='test')
        scope.order_id.action_confirm()
        rev = scope.current_revision_id
        invoice = scope.order_id._create_invoices()
        comp = self._comp_of(rev, self.l_sep)
        line = invoice.invoice_line_ids.filtered(lambda l: l.sipanel_source_component_id == comp)
        self.assertEqual(len(line), 1)
        for field_name in ('sipanel_source_revision_id', 'sipanel_source_quote_scope_id',
                           'sipanel_source_scope_id', 'sipanel_origin_key',
                           'sipanel_source_line_id'):
            self.assertTrue(line[field_name], f'{field_name} must survive the guarded flow')
        self.assertEqual(invoice.state, 'draft')


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sepbill', 'sipanel_hardening')
class TestPricelistFailsClosed(SeparatelyBillableCase):
    """STEP 2B-HARDENING: a failed pricelist calculation must never be replaced
    by product.list_price. That would invent a price - possibly in the wrong
    currency - and send it to a customer."""

    def _break_pricing(self):
        """Simulate a genuine pricing failure (a missing currency rate is the
        realistic one). Patch the registry class so the target does not depend on
        where Odoo happens to define it."""
        return patch.object(
            type(self.env['product.pricelist']), '_get_product_price',
            side_effect=UserError('no exchange rate for this currency'))

    def test_failed_pricing_leaves_no_governed_price(self):
        with self._break_pricing():
            scope = self._add_scope()
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_sep)
        self.assertTrue(comp.sell_price_error, 'the failure must be recorded, not swallowed')
        self.assertEqual(comp.sell_price_unit, 0.0,
                         'no price may be invented from the product list price')
        self.assertEqual(comp.sell_price_status, 'missing')

    def test_failed_pricing_blocks_readiness_and_the_seal(self):
        with self._break_pricing():
            scope = self._add_scope()
        rev = scope.current_revision_id
        codes = {c for c, _m in rev._projection_blocking_issues()}
        self.assertIn('SB_PRICE_FAILED', codes)
        blocking = {i['code'] for i in scope._readiness_issues() if i['level'] == 'block'}
        self.assertIn('SB_PRICE_FAILED', blocking)
        with self.assertRaises(UserError):
            scope.order_id._sipanel_check_readiness()

    def test_a_known_zero_reason_cannot_mask_a_pricing_failure(self):
        with self._break_pricing():
            scope = self._add_scope()
        comp = self._comp_of(scope.current_revision_id, self.l_sep)
        comp.write({'sell_known_zero_reason': 'looks deliberate but the pricelist failed'})
        self.assertEqual(comp.sell_price_status, 'missing',
                         'missing evidence must not be dressed up as a deliberate zero')

    def test_a_governed_manual_price_clears_the_failure(self):
        """Clearing one component clears exactly that component.

        Every separately-billable component of the fixture fails pricing while
        the pricelist is broken, so the issue list only empties once each one has
        a governed price - which is the fail-closed behaviour working, not a
        leftover.
        """
        with self._break_pricing():
            scope = self._add_scope()
        rev = scope.current_revision_id
        comp = self._comp_of(rev, self.l_sep)
        label = comp.customer_label_resolved or comp.name
        comp.action_set_manual_sell_price(500.0)
        self.assertFalse(comp.sell_price_error)
        self.assertEqual(comp.sell_price_status, 'known')
        still_failing = [m for c, m in rev._projection_blocking_issues() if c == 'SB_PRICE_FAILED']
        self.assertFalse([m for m in still_failing if label in m],
                         'this component must no longer be reported as unpriced')
        # once every failed component is priced, the block is gone entirely
        for other in rev.component_ids.filtered(lambda c: c.sell_price_error):
            other.action_set_manual_sell_price(500.0)
        self.assertNotIn('SB_PRICE_FAILED', {c for c, _m in rev._projection_blocking_issues()})

    def test_successful_pricing_records_no_error(self):
        comp = self._comp_of(self._add_scope().current_revision_id, self.l_sep)
        self.assertFalse(comp.sell_price_error)
        self.assertEqual(comp.sell_price_status, 'known')
