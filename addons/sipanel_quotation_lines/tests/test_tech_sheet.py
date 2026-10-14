# -*- coding: utf-8 -*-
"""System technical sheet + Shop Drawings line (owner requirements 2026-10-14, items 1-3 and 5). Every record is
synthetic (SIPANEL-PT-QLINES prefix) and rolled back."""
import base64
import io

from lxml import html as lxml_html
from PIL import Image

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.sipanel_commercial_scope_core.tests.common import SipanelCoreCase, set_translation

PT = 'SIPANEL-PT-QLINES'


def png(color):
    buf = io.BytesIO()
    Image.new('RGB', (4, 2), color).save(buf, 'PNG')
    return base64.b64encode(buf.getvalue())


PNG_1PX, PNG_1PX_B = png((10, 20, 30)), png((200, 100, 50))
ROWS = [(1, ('Shop drawings', 'نقشه‌های اجرایی'), ('Preparation of shop drawings', 'تهیه‌ی نقشه‌های شاپ')),
        (2, ('Liner sheet', 'ورق زیرین'), ('Galvanized sheet, {liner_thickness} mm thick',
                                           'ورق گالوانیزه، ضخامت {liner_thickness} میلیمتر')),
        (3, ('Vapour barrier', 'لایه‌ی بخاربند'), ('220 microns', '۲۲۰ میکرون'))]
SUPPLY, INSTALL_10 = 24_865_800_000.0, 2_486_580_000.0
UNTAXED, TAX, TOTAL = 27_352_380_000.0, 2_735_238_000.0, 30_087_618_000.0
SHOP_2 = 547_047_600.0


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_quotation_lines')
class TestTechSheetAndShopDrawings(SipanelCoreCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        real = env['account.analytic.plan'].with_context(lang='en_US').search([('name', '=', 'SIPANEL System')])
        if real:
            cls.plan_system = real
            env['ir.config_parameter'].sudo().set_param('sipanel_scope.system_plan_id', real.id)
        else:
            cls.plan_system.name = 'SIPANEL System'
        env['res.lang']._activate_lang('fa_IR')
        cls.vat = env['account.tax'].create({'name': f'{PT} Sheet VAT 10%', 'amount': 10.0, 'amount_type': 'percent',
                                             'type_tax_use': 'sale', 'company_id': cls.company.id})
        Product = env['product.product']

        def mk(name, base=False, uom=None, price=0.0):
            return Product.create({'name': f'{PT} {name}', 'type': 'service', 'sale_ok': True, 'list_price': price,
                                   'uom_id': (uom or cls.uom_unit).id, 'taxes_id': [(6, 0, cls.vat.ids)],
                                   'sipanel_installation_base': base})
        cls.p_roof = mk('Sheet Roof', base=True, uom=cls.uom_m, price=88_000_000.0)
        cls.p_flash = mk('Sheet Flashing', base=True, uom=cls.uom_m, price=34_000_000.0)
        cls.p_gut = mk('Sheet Gutter', base=True, uom=cls.uom_m, price=67_000_000.0)
        cls.p_install = mk('Sheet Installation')
        cls.p_shop = mk('Sheet Shop Drawings')
        Account = env['account.analytic.account']
        cls.system = Account.create({'name': f'{PT} Sheet System', 'plan_id': cls.plan_system.id,
                                     'sipanel_installation_product_id': cls.p_install.id,
                                     'sipanel_shop_drawing_product_id': cls.p_shop.id,
                                     'sipanel_tech_image': PNG_1PX})
        for number, (title_en, title_fa), (desc_en, desc_fa) in ROWS:
            row = env['sipanel.system.spec.line'].create({'system_id': cls.system.id, 'sequence': number * 10,
                                                          'number': number, 'title': title_en, 'description': desc_en})
            set_translation(row, 'title', en=title_en, fa=title_fa)
            set_translation(row, 'description', en=desc_en, fa=desc_fa)
        cls.system_plain = Account.create({'name': f'{PT} Sheet Plain System', 'plan_id': cls.plan_system.id,
                                           'sipanel_installation_product_id': cls.p_install.id})
        Partner = env['res.partner']
        cls.cust_en = Partner.create({'name': f'{PT} Sheet Customer EN', 'lang': 'en_US'})
        cls.cust_fa = Partner.create({'name': f'{PT} Sheet Customer FA', 'lang': 'fa_IR'})

    # ------------------------------------------------------------------ helpers
    def _order(self, partner=None, system=None, **vals):
        return self.env['sale.order'].create(dict({
            'partner_id': (partner or self.cust_fa).id, 'origin': PT,
            'sipanel_requested_system_id': (system or self.system).id}, **vals))

    def _si_2546(self, partner=None):
        order = self._order(partner)
        Line = self.env['sale.order.line']
        Line.create({'order_id': order.id, 'display_type': 'line_section', 'name': 'Roof', 'sequence': 1})
        Line.create({'order_id': order.id, 'product_id': self.p_roof.id, 'product_uom_qty': 206.0, 'sequence': 2})
        Line.create({'order_id': order.id, 'product_id': self.p_flash.id, 'product_uom_qty': 108.47, 'sequence': 3})
        Line.create({'order_id': order.id, 'product_id': self.p_flash.id, 'product_uom_qty': 54.23, 'sequence': 4})
        Line.create({'order_id': order.id, 'product_id': self.p_gut.id, 'product_uom_qty': 18.0, 'sequence': 5})
        return order

    @staticmethod
    def _rows(order, lang):
        return order.with_context(lang=lang)._sipanel_tech_sheet_rows()

    @staticmethod
    def _stored(record, field):
        record.flush_recordset([field])
        record.env.cr.execute(f'SELECT "{field}" FROM "{record._table}" WHERE id = %s', (record.id,))
        return record.env.cr.fetchone()[0]

    def _doc(self, order):
        return lxml_html.fromstring(
            self.env['ir.actions.report']._render_qweb_html('sale.report_saleorder', order.ids)[0])

    def _shop(self, order):
        return order._sipanel_managed_lines('shop_drawing')

    # ------------------------------------------------------------------ technical sheet
    def test_01_snapshot_copied_with_translations_and_independent_of_the_system(self):
        order = self._order()
        self.assertTrue(order.sipanel_has_tech_sheet)
        self.assertEqual(order.sipanel_tech_image, self.system.sipanel_tech_image)
        snap = order.sipanel_tech_spec_ids.sorted('number')
        self.assertEqual(snap.mapped('number'), [1, 2, 3])
        for row, src in zip(snap, self.system.sipanel_tech_spec_ids.sorted('number')):
            for fname in ('title', 'description'):
                self.assertEqual(self._stored(row, fname), self._stored(src, fname), 'every stored language copied')
        self.assertEqual(self._rows(order, 'fa_IR')[2], ('۳', 'لایه‌ی بخاربند', '۲۲۰ میکرون'))
        self.assertEqual(self._rows(order, 'en_US')[2], ('3', 'Vapour barrier', '220 microns'))
        # a later change of the System sheet does not reach the quotation
        src3 = self.system.sipanel_tech_spec_ids.filtered(lambda r: r.number == 3)
        set_translation(src3, 'description', en='CHANGED', fa='تغییر')
        self.system.sipanel_tech_image = PNG_1PX_B
        self.assertEqual(self._rows(order, 'fa_IR')[2][2], '۲۲۰ میکرون')
        self.assertEqual(order.sipanel_tech_image, PNG_1PX)
        # a new quotation takes the System sheet as it is now
        self.assertEqual(self._rows(self._order(), 'fa_IR')[2][2], 'تغییر')

    def test_02_editable_on_draft_frozen_once_sent_or_confirmed(self):
        order = self._order()
        self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.p_gut.id, 'product_uom_qty': 1.0})
        row = order.sipanel_tech_spec_ids.filtered(lambda r: r.number == 3)
        row.with_context(lang='fa_IR').description = '۲۵۰ میکرون'
        self.assertEqual(self._rows(order, 'fa_IR')[2][2], '۲۵۰ میکرون', 'the quotation copy is editable on a draft')
        self.assertEqual(self._rows(order, 'en_US')[2][2], '220 microns', 'per language, natively')
        self.env['sipanel.quotation.spec.line'].create({'order_id': order.id, 'number': 4, 'sequence': 40,
                                                        'title': 'Extra'})
        order.action_quotation_sent()
        self.assertEqual(order.state, 'sent')
        attempts = (lambda: row.write({'title': 'X'}), row.unlink,
                    lambda: self.env['sipanel.quotation.spec.line'].create({'order_id': order.id, 'number': 9, 'title': 'Y'}),
                    lambda: order.write({'sipanel_liner_thickness': '0.5'}),
                    lambda: order.write({'sipanel_tech_image': PNG_1PX_B}),
                    lambda: order.write({'sipanel_tech_spec_ids': [(5, 0, 0)]}),
                    order.action_sipanel_load_tech_sheet,
                    lambda: order.write({'sipanel_requested_system_id': self.system_plain.id}))
        for attempt in attempts:
            with self.assertRaises(UserError):
                attempt()
        self.assertEqual(len(order.sipanel_tech_spec_ids), 4)
        self.assertEqual(self._rows(order, 'fa_IR')[2][2], '۲۵۰ میکرون')
        order.action_confirm()
        with self.assertRaises(UserError):
            row.write({'title': 'X'})
        # a duplicate of a sent / confirmed quotation is a new draft with its own editable copy
        copy = order.copy()
        self.assertEqual(copy.state, 'draft')
        self.assertEqual(self._rows(copy, 'fa_IR'), self._rows(order, 'fa_IR'))
        copy.sipanel_tech_spec_ids[:1].title = 'Editable again'

    def test_03_reload_and_system_change_on_a_draft(self):
        order = self._order()
        order.sipanel_tech_spec_ids.unlink()
        self.assertTrue(order.sipanel_has_tech_sheet, 'the image alone is still a sheet')
        order.action_sipanel_load_tech_sheet()
        self.assertEqual(len(order.sipanel_tech_spec_ids), 3, 'reloaded from the System')
        order.sipanel_requested_system_id = self.system_plain
        self.assertFalse(order.sipanel_tech_spec_ids or order.sipanel_tech_image, 'a System without a sheet clears it')
        self.assertFalse(order.sipanel_has_tech_sheet)
        order.sipanel_requested_system_id = self.system
        self.assertEqual(len(order.sipanel_tech_spec_ids), 3)
        with self.assertRaises(ValidationError):
            self.env['account.analytic.account'].create({'name': f'{PT} not a System', 'plan_id': self.plan_activity.id,
                                                         'sipanel_tech_image': PNG_1PX})

    def test_04_liner_thickness_in_row_2(self):
        order = self._order()
        self.assertEqual(order.sipanel_liner_thickness, '0.7', 'default 0.7 mm')
        self.assertEqual(self._rows(order, 'fa_IR')[1][2], 'ورق گالوانیزه، ضخامت ۰.۷ میلیمتر')
        self.assertEqual(self._rows(order, 'en_US')[1][2], 'Galvanized sheet, 0.7 mm thick')
        order.sipanel_liner_thickness = '0.5'
        self.assertEqual(self._rows(order, 'fa_IR')[1][2], 'ورق گالوانیزه، ضخامت ۰.۵ میلیمتر')
        self.assertIn('{liner_thickness}', order.sipanel_tech_spec_ids.filtered(lambda r: r.number == 2).description,
                      'the stored text keeps the placeholder; the printout puts the value in')
        with self.assertRaises(ValueError):
            order.sipanel_liner_thickness = '0.6'

    def test_05_layout_sheet_page_between_page_1_and_the_price_table(self):
        for partner, heading, row2 in ((self.cust_fa, f'مشخصات فنی سیستم {PT} Sheet System', 'ضخامت ۰.۷ میلیمتر'),
                                       (self.cust_en, f'Technical Specification of the {PT} Sheet System System',
                                        '0.7 mm thick')):
            order = self._order(partner)
            doc = self._doc(order)
            sheet = doc.xpath("//div[@name='sipanel_tech_sheet']")
            cover = doc.xpath("//div[contains(@class, 'custom-full-page-cover')]")
            page = doc.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' page ')]")
            self.assertEqual((len(sheet), len(cover), len(page)), (1, 1, 1), partner.lang)
            parent = sheet[0].getparent()
            self.assertTrue(parent.index(cover[0]) < parent.index(sheet[0]) < parent.index(page[0]),
                            'Page 1 (cover), then the sheet, then the price table')
            self.assertIn('page-break-after: always', sheet[0].get('style'))
            self.assertEqual(sheet[0].get('dir'), 'rtl' if partner.lang == 'fa_IR' else 'ltr')
            self.assertEqual(' '.join(sheet[0].xpath('.//h4')[0].text_content().split()), heading)
            self.assertTrue(sheet[0].xpath(".//img[starts-with(@src, 'data:image/png;base64,')]"))
            rows = sheet[0].xpath(".//tr[contains(@class, 'o_sipanel_tech_spec_row')]")
            self.assertEqual(len(rows), 3)
            self.assertIn(row2, rows[1].text_content())
            self.assertFalse(page[0].xpath(".//div[@name='sipanel_tech_sheet']"), 'not inside the price table page')
        plain = self._order(self.cust_fa, system=self.system_plain)
        self.assertFalse(self._doc(plain).xpath("//div[@name='sipanel_tech_sheet']"),
                         'a quotation without a sheet keeps the earlier layout')

    # ------------------------------------------------------------------ shop drawings line
    def test_06_shop_drawings_2pct_of_supply_and_installation_discount_100(self):
        order = self._si_2546()
        order.write({'sipanel_installation_pct': 10.0, 'sipanel_shop_drawing_pct': 2.0,
                     'sipanel_shop_drawing_discount': 100.0})
        shop = self._shop(order)
        line = shop.filtered(lambda l: not l.display_type)
        self.assertEqual(len(shop), 2)
        self.assertEqual(line.product_id, self.p_shop)
        self.assertEqual((line.product_uom_qty, line.price_unit, line.discount), (1.0, SHOP_2, 100.0))
        self.assertEqual((line.price_subtotal, line.price_tax), (0.0, 0.0), 'net 0, shown in the price table')
        self.assertEqual(line.name.split('\n')[0], 'تهیه‌ی نقشه‌های اجرایی (شاپ)')
        self.assertEqual(shop.filtered('display_type').name, 'نقشه‌های اجرایی')
        self.assertEqual((order.amount_untaxed, order.amount_tax, order.amount_total), (UNTAXED, TAX, TOTAL))
        self.assertEqual(order.sipanel_installation_amount, INSTALL_10, 'the shop line is not installation')
        ordered = order.order_line.sorted(lambda l: (l.sequence, l.id))
        inst = order._sipanel_managed_lines('installation').filtered(lambda l: not l.display_type)
        self.assertEqual(list(ordered[-2:]), list(shop.sorted(lambda l: (l.sequence, l.id))), 'shop block last')
        self.assertEqual(ordered[-3], inst, 'right after the installation line')
        self.assertEqual(inst.price_unit, INSTALL_10, 'the shop line is not in the installation base')
        # recomputed while a quotation: base = items + installation
        roof = order.order_line.filtered(lambda l: l.product_id == self.p_roof)
        roof.product_uom_qty = 106.0
        base = (SUPPLY - 100 * 88_000_000.0) * 1.1
        self.assertEqual(line.price_unit, round(base * 0.02))
        self.assertEqual(ordered[-3], inst)
        # discount 0: charged
        order.sipanel_shop_drawing_discount = 0.0
        self.assertEqual(line.discount, 0.0)
        self.assertEqual(line.price_subtotal, round(base * 0.02))
        order.sipanel_shop_drawing_pct = 0.0
        self.assertFalse(self._shop(order), 'percentage 0: no shop drawings line')
        with self.assertRaises(UserError):
            order.sipanel_shop_drawing_discount = 120.0

    def test_07_shop_drawings_without_installation_and_protection(self):
        order = self._si_2546(self.cust_en)
        order.write({'sipanel_shop_drawing_pct': 2.0, 'sipanel_shop_drawing_discount': 100.0})
        line = self._shop(order).filtered(lambda l: not l.display_type)
        self.assertEqual(line.price_unit, round(SUPPLY * 0.02), 'no installation line: 2 % of the items')
        self.assertEqual(line.name.split('\n')[0], 'Preparation of shop drawings')
        line.write({'price_unit': 1.0, 'discount': 0.0})
        self.assertEqual((line.price_unit, line.discount), (round(SUPPLY * 0.02), 100.0), 'a manual edit is re-governed')
        order.action_update_prices()
        self.assertEqual((line.price_unit, line.discount), (round(SUPPLY * 0.02), 100.0), 'pricelist update keeps it')
        with self.assertRaises(UserError):
            line.unlink()
        with self.assertRaises(UserError):
            order.order_line.filtered(lambda l: l.product_id == self.p_roof).write({'sipanel_managed_role': 'shop_drawing'})
        with self.assertRaises(UserError):
            self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.p_shop.id,
                                                'sipanel_managed_role': 'shop_drawing'})
        copy = order.copy()
        self.assertEqual(len(self._shop(copy)), 2, 'copy: rebuilt once, never duplicated')
        order.action_confirm()
        with self.assertRaises(UserError):
            order.sipanel_shop_drawing_pct = 5.0
        with self.assertRaises(UserError):
            order.sipanel_shop_drawing_discount = 0.0

    def test_08_shop_drawings_needs_a_product_on_the_system(self):
        order = self._order(system=self.system_plain)
        with self.assertRaisesRegex(UserError, 'no shop drawings product'):
            order.sipanel_shop_drawing_pct = 2.0
        self.assertFalse(self._shop(order))
        self.company.write({'sipanel_shop_drawing_pct_default': 2.0, 'sipanel_shop_drawing_discount_default': 100.0})
        new = self._order()
        self.assertEqual((new.sipanel_shop_drawing_pct, new.sipanel_shop_drawing_discount), (2.0, 100.0),
                         'company defaults proposed on new quotations')
