# -*- coding: utf-8 -*-
"""Quotation lines (work order 2026-10-05): technical description (A), Installation / Execution line (B,
B1-B4), amount in words (C). Every record is synthetic (SIPANEL-PT-QLINES prefix) and rolled back."""
import uuid

from lxml import html as lxml_html

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sipanel_commercial_scope_core.tests.common import SipanelCoreCase, set_translation

PT = 'SIPANEL-PT-QLINES'
ROOF_QTY, ROOF_PRICE = 206.0, 88_000_000.0
FLASH_QTY, FLASH_PRICE = 162.7, 34_000_000.0
GUTTER_QTY, GUTTER_PRICE = 18.0, 67_000_000.0
SUPPLY = 24_865_800_000.0


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_quotation_lines')
class TestQuotationLines(SipanelCoreCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.estimator.write({'group_ids': [(4, env.ref('sipanel_sale_scope.group_scope_sales').id),
                                           (4, env.ref('sales_team.group_sale_manager').id)]})
        cls.vat = env['account.tax'].create({'name': f'{PT} VAT 10%', 'amount': 10.0, 'amount_type': 'percent',
                                             'type_tax_use': 'sale', 'company_id': cls.company.id})
        # One System plan for everything: the Requested System guard (sipanel_quotation_project_info) resolves the
        # plan by name and requires the configured plan to agree; the core fixture configured a fresh test plan.
        real = env['account.analytic.plan'].with_context(lang='en_US').search([('name', '=', 'SIPANEL System')])
        if real:
            cls.plan_system = real
            env['ir.config_parameter'].sudo().set_param('sipanel_scope.system_plan_id', real.id)
        else:
            cls.plan_system.name = 'SIPANEL System'
        Product = env['product.product']

        def mk(name, ptype='service', base=False, desc_en=None, desc_fa=None, uom=None, price=0.0):
            p = Product.create({'name': f'{PT} {name}', 'type': ptype, 'sale_ok': True, 'list_price': price,
                                'uom_id': (uom or cls.uom_unit).id, 'taxes_id': [(6, 0, cls.vat.ids)],
                                'sipanel_installation_base': base})
            if desc_en is not None:
                set_translation(p.product_tmpl_id, 'description_sale', en=desc_en, fa=desc_fa)
            return p
        # list price = the reference price: Odoo 19 treats a price_unit given at create as the product price
        # (technical_price_unit) and re-prices such a line from the product on a quantity change / Update prices
        cls.p_roof = mk('Roof Supply', base=True, uom=cls.uom_m, desc_en='Roof desc line 1\nRoof desc line 2',
                        desc_fa='شرح سقف ۱\nشرح سقف ۲', price=ROOF_PRICE)
        cls.p_flash = mk('Flashing', base=True, uom=cls.uom_m, price=FLASH_PRICE)
        cls.p_gut = mk('Gutter', base=True, uom=cls.uom_m, price=GUTTER_PRICE)
        cls.p_zero = mk('Zero list price item', base=True, uom=cls.uom_m)
        cls.p_crane_svc = mk('Crane (not flagged)')
        cls.p_install = mk('Installation Service', desc_en='Install desc EN', desc_fa='شرح نصب')
        cls.p_own = mk('Own-line bracket', ptype='consu', desc_en='Bracket spec EN', desc_fa='مشخصات بست', price=5.0)
        Account = env['account.analytic.account']
        cls.system = Account.create({'name': f'{PT} Standing Seam', 'plan_id': cls.plan_system.id,
                                     'sipanel_installation_product_id': cls.p_install.id})
        cls.system_unmapped = Account.create({'name': f'{PT} Unmapped', 'plan_id': cls.plan_system.id})
        cls.v_new = cls._make_version('NEW', include_install=False)
        cls.v_old = cls._make_version('OLD', include_install=True)
        cls.v_own = cls._make_version('OWN', include_install=False, own_line=True)
        Partner = env['res.partner']
        cls.cust_en = Partner.create({'name': f'{PT} Customer EN', 'lang': 'en_US'})
        env['res.lang']._activate_lang('fa_IR')
        cls.cust_fa = Partner.create({'name': f'{PT} Customer FA', 'lang': 'fa_IR'})

    @classmethod
    def _make_version(cls, tag, include_install, own_line=False):
        env = cls.env
        scope = env['sipanel.scope'].create({'code': f'{PT}-{tag}-{uuid.uuid4().hex[:8]}', 'name': f'{PT} Seam {tag}',
                                             'owner_user_id': cls.steward.id})
        v = env['sipanel.scope.version'].create({
            'scope_id': scope.id, 'base_uom_id': cls.uom_m.id, 'dimension_family': 'length',
            'anchor_product_id': cls.p_roof.id, 'anchor_owner_mode': 'component_bridge_owner',
            'system_ids': [(6, 0, cls.system.ids)]})
        set_translation(v, 'customer_label', en='Standing Seam Roof', fa='سقف استندینگ سیم')
        L = env['sipanel.scope.recipe.line']
        L.create({'version_id': v.id, 'sequence': 10, 'product_id': cls.p_screw.id, 'uom_id': cls.uom_unit.id,
                  'dimension_family': 'count', 'basis': 'manual', 'execution_mode': 'no_action', 'no_action_reason': 'covered_cost',
                  'cost_policy': 'manual_estimate', 'disclosure': 'internal_only', 'customer_eligible': False})
        if own_line:
            own = L.create({'version_id': v.id, 'sequence': 20, 'product_id': cls.p_own.id, 'uom_id': cls.uom_unit.id,
                            'dimension_family': 'count', 'basis': 'fixed', 'fixed_qty': 4.0, 'execution_mode': 'no_action', 'no_action_reason': 'covered_cost',
                            'cost_policy': 'manual_estimate', 'placement': 'own_line', 'customer_eligible': True})
            set_translation(own, 'customer_label', en='Bracket', fa='بست')
        if include_install:
            inst = L.create({'version_id': v.id, 'sequence': 100, 'product_id': cls.p_install.id, 'uom_id': cls.uom_unit.id,
                             'dimension_family': 'count', 'basis': 'manual', 'execution_mode': 'no_action', 'no_action_reason': 'covered_cost',
                             'cost_policy': 'manual_estimate', 'placement': 'included_parent', 'customer_eligible': True})
            set_translation(inst, 'customer_label', en='Installation', fa='نصب')
        v.action_release()
        return v

    # ------------------------------------------------------------------ helpers
    def _order(self, partner=None, system=None, **vals):
        return self.env['sale.order'].create(dict({
            'partner_id': (partner or self.cust_en).id, 'origin': PT,
            'sipanel_requested_system_id': (system or self.system).id}, **vals))

    def _line(self, order, product, qty, price, **vals):
        return self.env['sale.order.line'].create(dict({
            'order_id': order.id, 'product_id': product.id, 'product_uom_qty': qty, 'price_unit': price}, **vals))

    def _si_2546_copy(self, partner=None, scope_version=None):
        """Synthetic copy of SI-26/2546: Roof / Flashing / Gutter at the reference quantities and prices.
        With a scope_version, the Roof is a Commercial Scope anchor (the new or the old model)."""
        order = self._order(partner)
        self.env['sale.order.line'].create({'order_id': order.id, 'display_type': 'line_section',
                                            'name': 'Standing Seam Roof System', 'sequence': 1})
        if scope_version:
            scope = self.env['sipanel.quote.scope']._create_from_version(
                order, scope_version, ROOF_QTY, self.uom_m, system=self.system, sequence=20)
            scope.anchor_line_id.write({'price_unit': ROOF_PRICE})
        else:
            self._line(order, self.p_roof, ROOF_QTY, ROOF_PRICE, sequence=20)
        self.env['sale.order.line'].create({'order_id': order.id, 'display_type': 'line_section',
                                            'name': 'Accessories', 'sequence': 40})
        self._line(order, self.p_flash, FLASH_QTY, FLASH_PRICE, sequence=50)
        self._line(order, self.p_gut, GUTTER_QTY, GUTTER_PRICE, sequence=60)
        return order

    @staticmethod
    def _managed(order):
        return order.order_line.filtered('sipanel_is_installation_line')

    def _install_line(self, order):
        lines = self._managed(order).filtered(lambda l: not l.display_type)
        self.assertLessEqual(len(lines), 1, 'never more than one installation line')
        return lines

    def _assert_last(self, order):
        ordered = order.order_line.sorted(lambda l: (l.sequence, l.id))
        self.assertEqual(ordered[-1], self._install_line(order), 'installation line is the last line')
        self.assertEqual(ordered[-2].display_type, 'line_section')
        self.assertTrue(ordered[-2].sipanel_is_installation_line, 'its own section is right before it')

    def _html(self, order):
        return self.env['ir.actions.report']._render_qweb_html('sale.report_saleorder', order.ids)[0].decode()

    def _supply(self, order):
        return sum(order.order_line.filtered(lambda l: l.product_id.sipanel_installation_base).mapped('price_subtotal'))

    # ------------------------------------------------------------------ A. technical description
    def test_01_description_sale_is_appended_natively_and_printed_under_the_title(self):
        for partner, desc in ((self.cust_en, ['Roof desc line 1', 'Roof desc line 2']),
                              (self.cust_fa, ['شرح سقف ۱', 'شرح سقف ۲'])):
            order = self._order(partner)
            line = self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.p_roof.id,
                                                       'product_uom_qty': 1.0})
            parts = line.name.split('\n')
            self.assertIn(self.p_roof.name, parts[0], 'first line is the item title (native)')
            self.assertEqual(parts[1:], desc, 'description_sale follows in the partner language (native)')
            doc = lxml_html.fromstring(self._html(order))
            cell = doc.xpath("//td[@name='td_product_name'][.//span[contains(@class,'o_sipanel_line_title')]]")
            self.assertEqual(len(cell), 1)
            title = cell[0].xpath(".//span[contains(@class,'o_sipanel_line_title')]")[0].text_content().strip()
            muted = cell[0].xpath(".//div[contains(@class,'o_sipanel_line_desc')]")
            self.assertIn(self.p_roof.name, title)
            self.assertNotIn(desc[0], title, 'the description is not part of the title')
            self.assertEqual(len(muted), 1, 'one muted description block inside the same cell')
            self.assertIn('text-muted', muted[0].get('class'))
            self.assertEqual([t.strip() for t in muted[0].itertext() if t.strip()], desc)

    def test_02_scope_generated_line_carries_the_description(self):
        order = self._order(self.cust_fa)
        scope = self.env['sipanel.quote.scope']._create_from_version(order, self.v_own, 10.0, self.uom_m,
                                                                      system=self.system)
        generated = order.order_line.filtered(lambda l: l.sipanel_is_generated)
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated.name.split('\n'), ['بست', 'مشخصات بست'],
                         'label (snapshot language) stays the title; description_sale follows')
        # the anchor keeps the governed Scope note untouched
        self.assertEqual(scope.anchor_line_id.name, scope.current_revision_id.final_note)
        self.assertIn('o_sipanel_line_desc', self._html(order))

    # ------------------------------------------------------------------ B. installation line
    def test_03_acceptance_40pct_on_the_new_scope_version(self):
        order = self._si_2546_copy(scope_version=self.v_new)
        self.assertEqual(self._supply(order), SUPPLY)
        self.assertFalse(self._managed(order), 'percentage 0 (company default unset): no installation line')
        order.sipanel_installation_pct = 40.0
        inst = self._install_line(order)
        self.assertEqual(inst.product_id, self.p_install, 'installation product of the order System (B2)')
        self.assertEqual((inst.product_uom_qty, inst.price_unit), (1.0, 9_946_320_000.0))
        self.assertEqual(inst.tax_ids, self.vat, 'taxes from the product, natively')
        self.assertEqual(order.amount_untaxed, 34_812_120_000.0)
        self.assertEqual(order.amount_tax, 3_481_212_000.0)
        self.assertEqual(order.amount_total, 38_293_332_000.0)
        self.assertEqual(order.sipanel_installation_amount, 9_946_320_000.0)
        self._assert_last(order)
        self.assertEqual(inst.name.split('\n')[0], 'Installation & Execution (40% of item subtotal)')

    def test_04_acceptance_10pct_and_fa_label(self):
        order = self._si_2546_copy(partner=self.cust_fa)
        order.sipanel_installation_pct = 10.0
        inst = self._install_line(order)
        self.assertEqual(inst.price_unit, 2_486_580_000.0)
        self.assertEqual(order.amount_untaxed, 27_352_380_000.0)
        self.assertEqual(order.amount_tax, 2_735_238_000.0)
        self.assertEqual(order.amount_total, 30_087_618_000.0)
        self.assertEqual(inst.name.split('\n'), ['نصب و اجرا (10٪ مبلغ اقلام)', 'شرح نصب'])
        self.assertEqual(self._managed(order).filtered('display_type').name, 'نصب و اجرا')

    def test_05_crane_line_is_not_in_the_base(self):
        order = self._si_2546_copy()
        order.sipanel_installation_pct = 40.0
        self._line(order, self.p_crane_svc, 1.0, 500_000_000.0, sequence=70)
        self.assertEqual(self._install_line(order).price_unit, 9_946_320_000.0, 'unflagged crane line excluded (B1)')
        self.assertEqual(order.sipanel_installation_base_amount, SUPPLY)
        self._assert_last(order)

    def test_06_recompute_while_quotation(self):
        order = self._si_2546_copy()
        order.sipanel_installation_pct = 40.0
        gutter = order.order_line.filtered(lambda l: l.product_id == self.p_gut)
        gutter.product_uom_qty = 28.0                         # +10 x 67,000,000
        self.assertEqual(self._install_line(order).price_unit, 10_214_320_000.0)
        gutter.price_unit = 77_000_000.0                      # +28 x 10,000,000
        self.assertEqual(self._install_line(order).price_unit, 10_326_320_000.0)
        gutter.unlink()
        self.assertEqual(self._install_line(order).price_unit, 9_463_920_000.0)
        new = self._line(order, self.p_gut, GUTTER_QTY, GUTTER_PRICE)
        self.assertEqual(self._install_line(order).price_unit, 9_946_320_000.0)
        self._assert_last(order)
        order.sipanel_installation_pct = 12.5
        self.assertEqual(self._install_line(order).price_unit, 3_108_225_000.0)
        self.assertEqual(self._install_line(order).name.split('\n')[0], 'Installation & Execution (12.5% of item subtotal)')
        order.action_quotation_sent()
        self.assertEqual(order.state, 'sent')
        new.product_uom_qty = 28.0
        self.assertEqual(self._install_line(order).price_unit, 3_191_975_000.0, 'sent quotations still recompute')
        self.assertEqual(len(self._managed(order)), 2, 'one section + one line, no duplicates')

    def test_07_frozen_after_confirmation_and_cancel(self):
        order = self._si_2546_copy()
        order.sipanel_installation_pct = 40.0
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        roof = order.order_line.filtered(lambda l: l.product_id == self.p_roof)
        roof.product_uom_qty = 300.0
        self.assertEqual(self._install_line(order).price_unit, 9_946_320_000.0, 'confirmed: never recomputed')
        with self.assertRaises(UserError):
            order.sipanel_installation_pct = 50.0
        order._action_cancel()
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(self._install_line(order).price_unit, 9_946_320_000.0, 'cancelled: still frozen')
        with self.assertRaises(UserError):
            order.sipanel_installation_pct = 10.0

    def test_08_zero_pct_means_no_line(self):
        order = self._si_2546_copy()
        order.sipanel_installation_pct = 0.0
        self.assertFalse(self._managed(order))
        order.sipanel_installation_pct = 40.0
        self.assertEqual(len(self._managed(order)), 2)
        order.sipanel_installation_pct = 0.0
        self.assertFalse(self._managed(order), 'back to 0 removes the section and the line')
        self.assertEqual(order.amount_untaxed, SUPPLY)

    def test_09_stays_last_and_single_after_scope_regeneration(self):
        order = self._si_2546_copy(scope_version=self.v_new)
        order.sipanel_installation_pct = 40.0
        # a second Scope is added, its projection regenerated, and the first Scope's components resynced
        scope2 = self.env['sipanel.quote.scope']._create_from_version(order, self.v_new, 5.0, self.uom_m,
                                                                       system=self.system, sequence=500)
        scope2.anchor_line_id.write({'price_unit': 1_000_000.0})
        for scope in order.sipanel_quote_scope_ids:
            rev = scope.current_revision_id
            rev._sync_separately_billable_lines()
            rev.action_generate_note()
        self._assert_last(order)
        self.assertEqual(len(self._managed(order)), 2)
        self.assertEqual(self._install_line(order).price_unit, order.currency_id.round((SUPPLY + 5_000_000.0) * 0.4))
        for scope in order.sipanel_quote_scope_ids:
            comps = scope.current_revision_id.component_ids
            self.assertNotIn(self.p_install, comps.mapped('product_id'), 'never a Scope component')
            self.assertNotIn(self._install_line(order), scope.anchor_line_id | scope.current_revision_id.projected_line_ids)

    def test_10_excluded_from_scope_costing(self):
        order = self._si_2546_copy(scope_version=self.v_new)
        revs = order.sipanel_quote_scope_ids.mapped('current_revision_id').sudo()
        before = (revs.mapped('eligible_cost_total'), order.sudo().sipanel_total_cost)
        order.sipanel_installation_pct = 40.0
        revs.invalidate_recordset()
        order.invalidate_recordset()
        self.assertEqual((revs.mapped('eligible_cost_total'), order.sudo().sipanel_total_cost), before,
                         'Scope cost base unchanged by the installation line')
        inst = self._install_line(order)
        self.assertFalse(inst.sipanel_quote_scope_id or inst.sipanel_is_generated or inst.sipanel_source_component_id)

    def test_11_old_scope_version_refuses_a_percentage(self):
        order = self._si_2546_copy(scope_version=self.v_old)
        with self.assertRaisesRegex(UserError, 'charge installation twice'):
            order.sipanel_installation_pct = 40.0
        self.assertFalse(self._managed(order))

    def test_12_no_mapping_refuses_and_creates_nothing(self):
        order = self._order(system=self.system_unmapped)
        self._line(order, self.p_roof, 1.0, 100.0)
        with self.assertRaisesRegex(UserError, 'no installation product'):
            order.sipanel_installation_pct = 10.0
        no_system = self._order()
        no_system.sipanel_requested_system_id = False
        with self.assertRaisesRegex(UserError, 'no SIPANEL System'):
            no_system.sipanel_installation_pct = 10.0

    def test_13_company_default_and_quotation_override(self):
        self.company.sipanel_installation_pct_default = 12.0
        order = self._si_2546_copy()
        self.assertEqual(order.sipanel_installation_pct, 12.0, 'new quotation proposes the company default')
        self.assertEqual(self._install_line(order).price_unit, 2_983_896_000.0)
        order.sipanel_installation_pct = 40.0
        self.assertEqual(self._install_line(order).price_unit, 9_946_320_000.0, 'quotation value overrides')
        settings = self.env['res.config.settings'].create({})
        self.assertEqual(settings.sipanel_installation_pct_default, 12.0)

    def test_14_protection_copy_update_prices_forgery_delete(self):
        order = self._si_2546_copy()
        order.sipanel_installation_pct = 40.0
        copy = order.copy()
        self.assertEqual(len(self._managed(copy)), 2, 'copy: rebuilt once, never duplicated')
        self.assertEqual(self._install_line(copy).price_unit, 9_946_320_000.0)
        order.action_update_prices()
        self.assertEqual(self._install_line(order).price_unit, 9_946_320_000.0, 'pricelist update keeps the amount')
        self._install_line(order).write({'price_unit': 1.0})
        self.assertEqual(self._install_line(order).price_unit, 9_946_320_000.0, 'a manual edit is re-governed')
        with self.assertRaises(UserError):
            self._install_line(order).unlink()
        roof = order.order_line.filtered(lambda l: l.product_id == self.p_roof)
        with self.assertRaises(UserError):
            roof.write({'sipanel_is_installation_line': True})
        with self.assertRaises(UserError):
            self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.p_crane_svc.id,
                                                'sipanel_is_installation_line': True})
        dp = self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.p_roof.id,
                                                 'is_downpayment': True, 'price_unit': 1_000.0, 'product_uom_qty': 1.0})
        self.assertTrue(dp)
        self.assertEqual(self._install_line(order).price_unit, 9_946_320_000.0, 'down payments excluded')

    def test_16_update_prices_to_a_zero_base_removes_the_line_cleanly(self):
        """Regression (clone run 2026-10-06): "Update prices" re-priced the base to 0 mid-batch, the engine
        removed the managed lines and the native discount reset then wrote on deleted lines (MissingError)."""
        order = self._order()
        self._line(order, self.p_zero, 10.0, 1_000_000.0, sequence=20)
        order.sipanel_installation_pct = 40.0
        self.assertEqual(self._install_line(order).price_unit, 4_000_000.0)
        order.action_update_prices()
        self.assertEqual(order.sipanel_installation_base_amount, 0.0)
        self.assertFalse(self._managed(order), 'base 0 after the update: no installation line, no error')
        self._line(order, self.p_roof, 1.0, ROOF_PRICE, sequence=30)
        self.assertEqual(self._install_line(order).price_unit, 35_200_000.0, 'rebuilt once the base is back')
        self._assert_last(order)

    # ------------------------------------------------------------------ C. amount in words
    def test_15_amount_in_words(self):
        irr = self.env.ref('base.IRR')
        fa = irr.with_context(lang='fa_IR')
        self.assertEqual(' '.join(fa.amount_to_text(38_293_332_000).split()),
                         'سی و هشت میلیارد و دویست و نود و سه میلیون و سیصد و سی و دو هزار ریال')
        self.assertEqual(' '.join(fa.amount_to_text(27_352_380_000).split()),
                         'بیست و هفت میلیارد و سیصد و پنجاه و دو میلیون و سیصد و هشتاد هزار ریال')
        self.assertTrue(irr.with_context(lang='en_US').amount_to_text(38_293_332_000).startswith('Thirty-Eight Billion'))
        for partner, label in ((self.cust_fa, 'مبلغ کل به حروف:'), (self.cust_en, 'Amount in words:')):
            order = self._si_2546_copy(partner=partner)
            order.sipanel_installation_pct = 40.0
            doc = lxml_html.fromstring(self._html(order))
            block = doc.xpath("//div[@name='so_total_summary']//div[@name='sipanel_amount_in_words']")
            self.assertEqual(len(block), 1, 'printed once, below the totals box')
            text = ' '.join(block[0].text_content().split())
            words = ' '.join(order.currency_id.with_context(lang=partner.lang).amount_to_text(order.amount_total).split())
            self.assertEqual(text, f'{label} {words}')
