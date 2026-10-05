# -*- coding: utf-8 -*-
"""Quotation Page 1 project information (work order 2026-10-04): snapshots (M), Project Site and the
fiscal-position guard (B, L), Customer / Contact (F), System plan resolution (C), Page 1 rendering (N).
Every record is synthetic (SIPANEL-PT-PAGE1 prefix) and rolled back with the test transaction."""
import ast
import os

from lxml import html as lxml_html

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged

from odoo.addons.sipanel_quotation_project_info.models.sale_order import FISCAL_BLOCK_CODE, FISCAL_CHANGE_GUARD
from odoo.addons.sipanel_sale_scope.tests.common import SipanelSaleCase
from odoo.addons.sipanel_quotation_project_info.models.system_plan import SYSTEM_PLAN_XMLIDS

PT = 'SIPANEL-PT-PAGE1'
MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_page1')
class TestQuotationPage1(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        cls.iran = env.ref('base.ir')
        try:
            cls.plan = env['sipanel.config'].resolve_system_plan()
        except UserError:
            cls.plan = env['account.analytic.plan'].create({'name': 'SIPANEL System'})
            env['ir.config_parameter'].sudo().set_param('sipanel_scope.system_plan_id', cls.plan.id)
        Account = env['account.analytic.account']
        cls.sys_seam = Account.create({'name': f'{PT} Standing Seam', 'code': 'PT-SEAM-CODE',
                                       'plan_id': cls.plan.id, 'company_id': cls.company.id})
        cls.sys_sandwich = Account.create({'name': f'{PT} Sandwich Panel', 'plan_id': cls.plan.id, 'company_id': cls.company.id})
        cls.other_plan = env['account.analytic.plan'].create({'name': f'{PT} Not The System Plan'})
        cls.not_a_system = Account.create({'name': f'{PT} Project Account', 'plan_id': cls.other_plan.id, 'company_id': cls.company.id})

        Partner = env['res.partner']
        cls.customer_co = Partner.create({'name': f'{PT} Customer Co', 'is_company': True, 'lang': 'en_US',
                                          'street': f'{PT} Head Office 1', 'city': f'{PT}-HQ-City', 'country_id': cls.iran.id})
        cls.contact = Partner.create({'name': f'{PT} Contact Person', 'parent_id': cls.customer_co.id, 'type': 'contact'})
        cls.individual = Partner.create({'name': f'{PT} Individual', 'is_company': False, 'lang': 'en_US'})
        cls.lead = env['crm.lead'].create({'name': f'{PT} پروژه طالقان', 'type': 'opportunity',
                                           'partner_id': cls.customer_co.id, 'sipanel_requested_system_id': cls.sys_seam.id})

    # ------------------------------------------------------------------ helpers
    def _quotation_from(self, lead, partner=None, env=None):
        """Same path as the CRM 'New Quotation' button: opportunity only in the context defaults."""
        env = env or self.env
        return env['sale.order'].with_context(**lead._prepare_opportunity_quotation_context()).create(
            {'partner_id': (partner or lead.partner_id).id})

    def _site(self, parent, name='Taleghan Site', city=None, **vals):
        return self.env['res.partner'].create(dict({
            'name': f'{PT} {name}', 'parent_id': parent.id, 'type': 'delivery', 'street': f'{PT} Site Road 7',
            'city': city or f'{PT}-SiteCity', 'country_id': self.iran.id}, **vals))

    def _page1(self, order):
        content = self.env['ir.actions.report']._render_qweb_html('sale.report_saleorder', order.ids)[0]
        blocks = lxml_html.fromstring(content).xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' o_sipanel_page1 ')]")
        self.assertEqual(len(blocks), 1, 'exactly one Page 1 information block per quotation')
        return blocks[0]

    @staticmethod
    def _text(node):
        return ' '.join(node.text_content().split())

    def _cell(self, block, cls):
        cells = block.xpath(f".//td[contains(concat(' ', normalize-space(@class), ' '), ' {cls} ')]")
        return self._text(cells[0]) if cells else None

    def _title(self, block):
        titles = block.xpath(".//div[contains(concat(' ', normalize-space(@class), ' '), ' o_sipanel_page1_title ')]")
        self.assertEqual(len(titles), 1, 'exactly one Page 1 title')
        return self._text(titles[0])

    def _labels(self, block):
        return [self._text(td) for td in block.xpath(
            ".//td[contains(@class, 'o_sipanel_page1_label') or contains(@class, 'o_sipanel_page1_section')]")]

    def _activate_fa(self):
        self.env['res.lang']._activate_lang('fa_IR')
        self.env['ir.module.module']._load_module_terms(['sipanel_quotation_project_info'], ['fa_IR'], overwrite=True)

    # ------------------------------------------------------------------ M — snapshots
    def test_m01_m02_project_name_snapshot_from_opportunity(self):
        order = self._quotation_from(self.lead)
        self.assertEqual(order.opportunity_id, self.lead)
        self.assertEqual(order.sipanel_project_name, f'{PT} پروژه طالقان')
        self.lead.write({'name': f'{PT} Renamed Opportunity'})
        order.invalidate_recordset()
        self.assertEqual(order.sipanel_project_name, f'{PT} پروژه طالقان', 'opportunity rename must not rewrite the snapshot')
        self.assertIn(f'{PT} پروژه طالقان', self._cell(self._page1(order), 'o_sipanel_page1_project_name'))

    def test_m03_m04_m05_requested_system_reference_and_snapshot(self):
        order = self._quotation_from(self.lead)
        self.assertEqual(order.sipanel_requested_system_id, self.sys_seam)
        self.assertEqual(order.sipanel_requested_system_name_snapshot, f'{PT} Standing Seam')
        # M4: renaming the System master does not change the quotation nor its PDF
        self.sys_seam.write({'name': f'{PT} Standing Seam RENAMED'})
        order.invalidate_recordset()
        self.assertEqual(order.sipanel_requested_system_name_snapshot, f'{PT} Standing Seam')
        printed = self._cell(self._page1(order), 'o_sipanel_page1_requested_system')
        self.assertEqual(printed, f'{PT} Standing Seam')
        self.assertNotIn('RENAMED', printed)
        self.assertNotIn('PT-SEAM-CODE', printed, 'the analytic Reference code is internal')
        # M5: changing the CRM Requested System does not change the existing quotation
        self.lead.write({'sipanel_requested_system_id': self.sys_sandwich.id})
        order.invalidate_recordset()
        self.assertEqual(order.sipanel_requested_system_id, self.sys_seam)
        self.assertEqual(order.sipanel_requested_system_name_snapshot, f'{PT} Standing Seam')

    def test_m06_m07_direct_quotation_manual_entry(self):
        order = self.env['sale.order'].create({'partner_id': self.individual.id, 'sipanel_project_name': f'{PT} Manual Project'})
        self.assertFalse(order.opportunity_id)
        self.assertEqual(order.sipanel_project_name, f'{PT} Manual Project')
        order.write({'sipanel_project_name': f'{PT} Manual Project v2'})
        self.assertEqual(order.sipanel_project_name, f'{PT} Manual Project v2')
        # M7: manual System selection initialises the snapshot; an intentional change re-captures it; clearing clears it
        order.write({'sipanel_requested_system_id': self.sys_sandwich.id})
        self.assertEqual(order.sipanel_requested_system_name_snapshot, f'{PT} Sandwich Panel')
        order.write({'sipanel_requested_system_id': self.sys_seam.id})
        self.assertEqual(order.sipanel_requested_system_name_snapshot, f'{PT} Standing Seam')
        order.write({'sipanel_requested_system_id': False})
        self.assertFalse(order.sipanel_requested_system_name_snapshot)

    def test_m08_existing_quotation_not_backfilled(self):
        """A quotation without snapshots (= every pre-existing quotation) is never filled by side effects."""
        order = self.env['sale.order'].create({'partner_id': self.customer_co.id})
        self.assertFalse(order.sipanel_project_name)
        self.assertFalse(order.sipanel_requested_system_id)
        self.lead.write({'name': f'{PT} Another Name'})
        self.sys_seam.write({'name': f'{PT} Another System Name'})
        order.write({'note': f'{PT} unrelated edit'})
        block = self._page1(order)
        order.invalidate_recordset()
        self.assertFalse(order.sipanel_project_name)
        self.assertFalse(order.sipanel_requested_system_id)
        self.assertFalse(order.sipanel_requested_system_name_snapshot)
        for cls in ('o_sipanel_page1_project_name', 'o_sipanel_page1_project_site', 'o_sipanel_page1_requested_system'):
            self.assertEqual(self._cell(block, cls), 'Not specified')

    def test_m09_no_install_hook_no_migration(self):
        """Upgrade/install cannot backfill: no init hook, no migration script, no data file touching sale.order."""
        with open(os.path.join(MODULE_DIR, '__manifest__.py'), encoding='utf-8') as f:
            manifest = ast.literal_eval(f.read())
        self.assertFalse({'pre_init_hook', 'post_init_hook', 'uninstall_hook'} & set(manifest))
        self.assertFalse(os.path.exists(os.path.join(MODULE_DIR, 'migrations')))
        self.assertFalse([d for d in manifest['data'] if d.startswith('data/')])

    def test_m10_opportunity_assigned_later_fills_only_empty_values(self):
        empty = self.env['sale.order'].create({'partner_id': self.customer_co.id})
        empty.write({'opportunity_id': self.lead.id})
        self.assertEqual(empty.sipanel_project_name, self.lead.name)
        self.assertEqual(empty.sipanel_requested_system_id, self.sys_seam)
        self.assertEqual(empty.sipanel_requested_system_name_snapshot, f'{PT} Standing Seam')
        filled = self.env['sale.order'].create({'partner_id': self.customer_co.id, 'sipanel_project_name': f'{PT} Kept',
                                                'sipanel_requested_system_id': self.sys_sandwich.id})
        filled.write({'opportunity_id': self.lead.id})
        self.assertEqual(filled.sipanel_project_name, f'{PT} Kept', 'never overwrite an existing Project Name')
        self.assertEqual(filled.sipanel_requested_system_id, self.sys_sandwich)
        self.assertEqual(filled.sipanel_requested_system_name_snapshot, f'{PT} Sandwich Panel')

    def test_m11_sales_operator_form_flow(self):
        """A normal Sales user sets Requested System on the Opportunity and creates the quotation through the form."""
        user = new_test_user(self.env, login='sipanel_pt_page1_sales', name=f'{PT} Sales',
                             groups='sales_team.group_sale_salesman')
        lead = self.env['crm.lead'].with_user(user).create({'name': f'{PT} Sales Opportunity', 'type': 'opportunity',
                                                            'partner_id': self.customer_co.id, 'user_id': user.id})
        with Form(lead) as lead_form:
            lead_form.sipanel_requested_system_id = self.sys_sandwich
        self.assertEqual(lead.sipanel_requested_system_id, self.sys_sandwich)
        SaleOrder = self.env['sale.order'].with_user(user).with_context(**lead._prepare_opportunity_quotation_context())
        with Form(SaleOrder) as so_form:
            self.assertEqual(so_form.sipanel_project_name, f'{PT} Sales Opportunity', 'form previews the snapshot')
            self.assertEqual(so_form.sipanel_requested_system_id, self.sys_sandwich)
        order = so_form.save()
        self.assertEqual(order.sipanel_requested_system_name_snapshot, f'{PT} Sandwich Panel')

    # ------------------------------------------------------------------ C — System plan
    def test_c01_requested_system_must_be_a_system(self):
        with self.assertRaises(ValidationError):
            self.lead.write({'sipanel_requested_system_id': self.not_a_system.id})
        order = self.env['sale.order'].create({'partner_id': self.individual.id})
        with self.assertRaises(ValidationError):
            order.write({'sipanel_requested_system_id': self.not_a_system.id})
        self.assertEqual(self.lead.sipanel_system_plan_id, self.plan)

    def test_c02_plan_resolution_fails_closed_on_ambiguity(self):
        if any(self.env.ref(xmlid, raise_if_not_found=False) for xmlid in SYSTEM_PLAN_XMLIDS):
            self.skipTest('plan resolved by XML id: name ambiguity cannot arise')
        self.env['account.analytic.plan'].create({'name': 'SIPANEL System'})
        with self.assertRaises(UserError):
            self.env['sipanel.config'].resolve_system_plan()
        self.assertFalse(self.env['sipanel.config'].system_plan_or_empty())
        self.lead.invalidate_recordset(['sipanel_system_plan_id'])
        self.assertFalse(self.lead.sipanel_system_plan_id, 'an ambiguous plan offers no System at all')

    def test_c03_configured_plan_must_agree(self):
        self.env['ir.config_parameter'].sudo().set_param('sipanel_scope.system_plan_id', self.other_plan.id)
        with self.assertRaises(UserError):
            self.env['sipanel.config'].resolve_system_plan()

    def test_c04_system_of_another_company_is_refused(self):
        other_company = self.env['res.company'].create({'name': f'{PT} Other Company'})
        foreign_system = self.env['account.analytic.account'].create({
            'name': f'{PT} Other Company System', 'plan_id': self.plan.id, 'company_id': other_company.id})
        lead = self.env['crm.lead'].create({'name': f'{PT} Company Lead', 'type': 'opportunity', 'company_id': self.company.id})
        with self.assertRaises(UserError):
            lead.write({'sipanel_requested_system_id': foreign_system.id})

    # ------------------------------------------------------------------ F — Customer / Contact
    def test_f01_customer_contact_hierarchy(self):
        on_contact = self.env['sale.order'].create({'partner_id': self.contact.id})
        customer, contact = on_contact._sipanel_page1_parties()
        self.assertEqual((customer, contact), (self.customer_co, self.contact))
        block = self._page1(on_contact)
        self.assertEqual(self._cell(block, 'o_sipanel_page1_customer'), f'{PT} Customer Co')
        self.assertEqual(self._cell(block, 'o_sipanel_page1_contact'), f'{PT} Contact Person')

        on_company = self.env['sale.order'].create({'partner_id': self.customer_co.id})
        block = self._page1(on_company)
        self.assertEqual(self._cell(block, 'o_sipanel_page1_customer'), f'{PT} Customer Co')
        self.assertIsNone(self._cell(block, 'o_sipanel_page1_contact'), 'no separate contact: Customer only')

        on_individual = self.env['sale.order'].create({'partner_id': self.individual.id})
        block = self._page1(on_individual)
        self.assertEqual(self._cell(block, 'o_sipanel_page1_customer'), f'{PT} Individual')
        self.assertIsNone(self._cell(block, 'o_sipanel_page1_contact'), 'no company is invented')

    # ------------------------------------------------------------------ B / L — Project Site and fiscal guard
    def _fiscal_fixture(self):
        env = self.env
        Tax, FP = env['account.tax'], env['account.fiscal.position']
        tax_dom = Tax.create({'name': f'{PT} VAT 10', 'amount': 10.0, 'amount_type': 'percent', 'type_tax_use': 'sale'})
        fp_dom = FP.create({'name': f'{PT} Domestic'})
        fp_foreign = FP.create({'name': f'{PT} Foreign'})
        tax_exp = Tax.create({'name': f'{PT} VAT 0 export', 'amount': 0.0, 'amount_type': 'percent', 'type_tax_use': 'sale',
                              'fiscal_position_ids': [(6, 0, fp_foreign.ids)], 'original_tax_ids': [(6, 0, tax_dom.ids)]})
        customer = env['res.partner'].create({'name': f'{PT} Fiscal Customer', 'is_company': True, 'lang': 'en_US',
                                              'street': f'{PT} Fiscal HQ', 'city': f'{PT}-FiscalCity', 'country_id': self.iran.id})
        # deterministic resolution independent of the database's auto-apply positions: manual positions win
        customer.with_company(self.company).property_account_position_id = fp_dom
        product = env['product.product'].create({'name': f'{PT} Panel', 'list_price': 1000.0, 'taxes_id': [(6, 0, tax_dom.ids)]})
        order = env['sale.order'].create({'partner_id': customer.id, 'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 3})]})
        return order, customer, tax_dom, tax_exp, fp_dom, fp_foreign

    @staticmethod
    def _fiscal_snapshot(order):
        order.invalidate_recordset()
        return (order.fiscal_position_id, [tuple(l.tax_ids.ids) for l in order.order_line],
                order.amount_untaxed, order.amount_tax, order.amount_total)

    def test_l01_default_delivery_address_is_not_a_project_site(self):
        order, customer, *_ = self._fiscal_fixture()
        self.assertEqual(order.partner_shipping_id, customer, 'Odoo defaults the Delivery Address to the customer')
        self.assertFalse(order._sipanel_page1_project_site())
        self.assertEqual(self._cell(self._page1(order), 'o_sipanel_page1_project_site'), 'Not specified')
        self.assertNotIn(f'{PT} Fiscal HQ', self._text(self._page1(order)), 'head office is not printed as Project Site')
        # a person of the same customer is not a site either
        person = self.env['res.partner'].create({'name': f'{PT} Site Engineer', 'parent_id': customer.id, 'type': 'contact'})
        order.write({'partner_shipping_id': person.id})
        self.assertFalse(order._sipanel_page1_project_site())

    def test_l02_distinct_site_same_fiscal_position_is_saved(self):
        order, customer, tax_dom, _tax_exp, fp_dom, _fp_foreign = self._fiscal_fixture()
        site = self._site(customer, city=f'{PT}-Taleghan')
        before = self._fiscal_snapshot(order)
        self.assertEqual(before[0], fp_dom)
        order.write({'partner_shipping_id': site.id})
        after = self._fiscal_snapshot(order)
        self.assertEqual(order.partner_shipping_id, site)
        self.assertEqual(before, after, 'Project Site entry must not change fiscal position, taxes or totals')
        self.assertEqual(before[1], [tuple(tax_dom.ids)])
        cell = self._cell(self._page1(order), 'o_sipanel_page1_project_site')
        self.assertIn(f'{PT} Taleghan Site', cell)
        self.assertIn(f'{PT} Site Road 7', cell)
        self.assertEqual(cell.count(f'{PT}-Taleghan'), 1, 'City is printed once, inside the formatted address')
        self.assertNotIn(f'{PT}-FiscalCity', cell)

    def test_l03_site_changing_fiscal_position_is_blocked(self):
        order, customer, tax_dom, _tax_exp, fp_dom, fp_foreign = self._fiscal_fixture()
        foreign_site = self._site(customer, name='Foreign Site', city=f'{PT}-Berlin', country_id=self.env.ref('base.de').id)
        foreign_site.with_company(self.company).property_account_position_id = fp_foreign
        before = self._fiscal_snapshot(order)
        with self.assertRaisesRegex(UserError, FISCAL_BLOCK_CODE):
            order.write({'partner_shipping_id': foreign_site.id})
        # the form sends the recomputed fiscal position along with the address: still refused
        with self.assertRaisesRegex(UserError, FISCAL_BLOCK_CODE):
            order.write({'partner_shipping_id': foreign_site.id, 'fiscal_position_id': fp_foreign.id})
        self.assertEqual(self._fiscal_snapshot(order), before)
        self.assertEqual(order.partner_shipping_id, customer)

    def test_l04_customer_change_is_left_to_the_native_flow(self):
        order, *_ = self._fiscal_fixture()
        order.write({'partner_id': self.individual.id, 'partner_shipping_id': self.individual.id})
        self.assertEqual(order.partner_shipping_id, self.individual)

    # ------------------------------------------------------------------ N — Page 1 rendering
    def test_n01_page1_english(self):
        order = self._quotation_from(self.lead, partner=self.contact)
        site = self._site(self.customer_co, city=f'{PT}-Taleghan')
        order.write({'partner_shipping_id': site.id})
        block = self._page1(order)
        self.assertEqual(block.get('dir'), 'ltr')
        text = self._text(block)
        labels = self._labels(block)
        self.assertEqual(self._title(block), 'COMMERCIAL QUOTATION')
        self.assertEqual(labels, ['Quotation No.', 'Quotation Date', 'Valid Until', 'CUSTOMER', 'Customer', 'Contact Person',
                                  'PROJECT INFORMATION', 'Project Name', 'Project Site', 'Requested System']
                         if order.validity_date else
                         ['Quotation No.', 'Quotation Date', 'CUSTOMER', 'Customer', 'Contact Person',
                          'PROJECT INFORMATION', 'Project Name', 'Project Site', 'Requested System'])
        for label in labels:
            self.assertFalse(any('\u0600' <= ch <= '\u06ff' for ch in label), f'bilingual label in an English document: {label}')
        self.assertIn(order.name, text)
        self.assertEqual(self._cell(block, 'o_sipanel_page1_requested_system'), f'{PT} Standing Seam')
        self.assertEqual(text.count(f'{PT}-Taleghan'), 1)
        self.assertNotIn(self.plan.name, text, 'internal System plan is not printed')

    def test_n02_page1_persian(self):
        self._activate_fa()
        self.customer_co.write({'lang': 'fa_IR'})
        order = self._quotation_from(self.lead, partner=self.contact)
        self.contact.write({'lang': 'fa_IR'})
        block = self._page1(order)
        self.assertEqual(block.get('dir'), 'rtl')
        text = self._text(block)
        labels = self._labels(block)
        self.assertEqual(self._title(block), 'پیش‌فاکتور', 'fa_IR cover title is the plain term (not "پیش‌فاکتور تجاری")')
        self.assertNotIn('تجاری', text)
        self.assertNotIn('COMMERCIAL QUOTATION', text)
        for fa in ('شماره پیش‌فاکتور', 'تاریخ پیش‌فاکتور', 'مشخصات کارفرما', 'کارفرما', 'شخص تماس',
                   'اطلاعات پروژه', 'نام پروژه', 'محل پروژه', 'سیستم درخواستی'):
            self.assertIn(fa, labels)
        for label in labels:
            self.assertFalse(any(ch.isascii() and ch.isalpha() for ch in label), f'English label in a Persian document: {label}')
        self.assertIn(f'{PT} پروژه طالقان', text)
        self.assertEqual(self._cell(block, 'o_sipanel_page1_project_site'), 'مشخص نشده')
        self.assertIn(order.date_order_shamsi, text, 'Persian documents keep the Shamsi date')

    def test_n03_native_address_row_is_not_printed(self):
        """V-01: the native recipient / invoicing / shipping row of web.address_layout is not printed, in either
        language, with or without a distinct Project Site; Page 1 still carries Customer and Project Site."""
        self._activate_fa()
        order = self._quotation_from(self.lead, partner=self.contact)
        site = self._site(self.customer_co, city=f'{PT}-Taleghan')
        for with_site in (False, True):
            order.write({'partner_shipping_id': (site if with_site else self.contact).id})
            for lang in ('en_US', 'fa_IR'):
                (self.customer_co | self.contact).write({'lang': lang})
                content = self.env['ir.actions.report']._render_qweb_html('sale.report_saleorder', order.ids)[0]
                doc = lxml_html.fromstring(content)
                where = f'{lang}, distinct site={with_site}'
                self.assertFalse(doc.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' address ')]"),
                                 f'native address row printed ({where})')
                self.assertFalse(doc.xpath("//*[@name='information_block']"), f'information block printed ({where})')
                self.assertFalse(doc.xpath("//*[contains(@class, 'customer_label')]"), f'"Customer:" label printed ({where})')
                block = self._page1(order)
                self.assertEqual(self._cell(block, 'o_sipanel_page1_customer'), f'{PT} Customer Co')
                site_cell = self._cell(block, 'o_sipanel_page1_project_site')
                if with_site:
                    self.assertIn(f'{PT} Taleghan Site', site_cell)
                else:
                    self.assertIn(site_cell, ('Not specified', 'مشخص نشده'))

    # ------------------------------------------------------------------ A — Requested System access (amendment)
    def test_s01_sales_user_selects_system_without_analytic_group(self):
        """A plain Sales user selects the System through the native Sales access (no new group, no ACL change)."""
        user = new_test_user(self.env, login='sipanel_pt_page1_s01', name=f'{PT} Plain Sales',
                             groups='sales_team.group_sale_salesman')
        found = self.env['account.analytic.account'].with_user(user).name_search(
            'PAGE1 Standing', domain=[('plan_id', '=', self.plan.id)])
        self.assertIn(self.sys_seam.id, [r[0] for r in found])
        lead = self.env['crm.lead'].with_user(user).create({
            'name': f'{PT} S01', 'type': 'opportunity', 'user_id': user.id, 'sipanel_requested_system_id': self.sys_seam.id})
        self.assertEqual(lead.sipanel_requested_system_id.name, f'{PT} Standing Seam')

    def test_s02_native_access_tripwire(self):
        """Evidence for the amendment decision (fail closed): native Odoo already grants Sales users read/write/create
        on account.analytic.account (sale: group_sale_salesman 1,1,1,0; account: group_user 1,0,0,0), and quotation
        send/confirm validate line distributions WITHOUT sudo. A restrictive "System Reader" record rule would therefore
        neither remove those rights (ACLs are a union) nor be safe (it would break send/confirm of lines carrying
        non-System analytic distributions). If this test fails, native access changed: revisit the decision."""
        user = new_test_user(self.env, login='sipanel_pt_page1_s02', name=f'{PT} Plain Sales 2',
                             groups='sales_team.group_sale_salesman')
        Account = self.env['account.analytic.account'].with_user(user)
        self.assertTrue(Account.has_access('read'))
        self.assertTrue(Account.has_access('write'))
        self.assertTrue(Account.has_access('create'))
        self.assertFalse(Account.has_access('unlink'))
        self.assertFalse(self.env['ir.model.access'].search([
            ('model_id.model', '=', 'account.analytic.account'), ('group_id.name', 'ilike', 'System Reader')]),
            'no SIPANEL reader group/ACL was added')
        self.assertFalse(self.env['ir.rule'].search([
            ('model_id.model', '=', 'account.analytic.account'), ('name', 'ilike', 'sipanel')]),
            'no SIPANEL record rule narrows analytic accounts')

    def test_s03_full_analytic_user_keeps_working(self):
        user = new_test_user(self.env, login='sipanel_pt_page1_s03', name=f'{PT} Analytic Sales',
                             groups='sales_team.group_sale_salesman,analytic.group_analytic_accounting')
        self.assertTrue(self.env['account.analytic.account'].with_user(user).search([('id', '=', self.not_a_system.id)]))
        order = self.env['sale.order'].with_user(user).create({'partner_id': self.individual.id,
                                                               'sipanel_requested_system_id': self.sys_seam.id})
        self.assertEqual(order.sipanel_requested_system_name_snapshot, f'{PT} Standing Seam')

    # ------------------------------------------------------------------ B — controlled fiscal change (amendment)
    def _foreign_site(self, customer, fp_foreign):
        site = self._site(customer, name='Foreign Site', city=f'{PT}-Berlin', country_id=self.env.ref('base.de').id)
        site.with_company(self.company).property_account_position_id = fp_foreign
        return site

    def _manager(self):
        return new_test_user(self.env, login='sipanel_pt_page1_mgr', name=f'{PT} Sales Manager',
                             groups='sales_team.group_sale_manager')

    def test_w01_manager_applies_fiscal_change_natively_with_audit(self):
        order, customer, tax_dom, tax_exp, fp_dom, fp_foreign = self._fiscal_fixture()
        site = self._foreign_site(customer, fp_foreign)
        manager = self._manager()
        self.assertEqual((order.amount_untaxed, order.amount_tax, order.amount_total), (3000.0, 300.0, 3300.0))
        wizard = self.env['sipanel.project.site.fiscal.change'].with_user(manager).create(
            {'order_id': order.id, 'proposed_site_id': site.id})
        # preview: nothing written yet
        self.assertEqual(wizard.current_site_id, customer)
        self.assertEqual(wizard.current_fiscal_position_id, fp_dom)
        self.assertEqual(wizard.proposed_fiscal_position_id, fp_foreign)
        self.assertTrue(wizard.fiscal_impact)
        self.assertEqual((wizard.current_amount_untaxed, wizard.current_amount_tax, wizard.current_amount_total),
                         (3000.0, 300.0, 3300.0))
        self.assertEqual((wizard.projected_amount_untaxed, wizard.projected_amount_tax, wizard.projected_amount_total),
                         (3000.0, 0.0, 3000.0))
        self.assertIn(tax_dom.name, wizard.line_taxes_html)
        self.assertIn(tax_exp.name, wizard.line_taxes_html)
        self.assertEqual(order.partner_shipping_id, customer)
        self.assertEqual(order.order_line.tax_ids, tax_dom)
        # confirmation is mandatory
        with self.assertRaises(UserError):
            wizard.action_apply()
        wizard.confirm = True
        wizard.action_apply()
        order.invalidate_recordset()
        self.assertEqual(order.partner_shipping_id, site)
        self.assertEqual(order.fiscal_position_id, fp_foreign, 'native fiscal-position resolution')
        self.assertEqual(order.order_line.tax_ids, tax_exp, 'native Update Taxes remapped the line')
        self.assertEqual((order.amount_untaxed, order.amount_tax, order.amount_total), (3000.0, 0.0, 3000.0))
        self.assertFalse(order.show_update_fpos)
        audit = order.message_ids.filtered(lambda m: 'Project Site change with fiscal impact approved' in (m.body or ''))
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.author_id, manager.partner_id)
        for text in (manager.name, customer.name, site.name, fp_dom.name, fp_foreign.name):
            self.assertIn(text, audit.body)
        self.assertTrue(order.message_ids.filtered(lambda m: 'Product taxes have been recomputed' in (m.body or '')),
                        'the native Update Taxes note is posted too')

    def test_w02_normal_sales_user_cannot_bypass(self):
        order, customer, _tax_dom, _tax_exp, fp_dom, fp_foreign = self._fiscal_fixture()
        site = self._foreign_site(customer, fp_foreign)
        sales = new_test_user(self.env, login='sipanel_pt_page1_w02', name=f'{PT} Plain Sales W02',
                              groups='sales_team.group_sale_salesman_all_leads')
        with self.assertRaises(AccessError):
            self.env['sipanel.project.site.fiscal.change'].with_user(sales).create({'order_id': order.id, 'proposed_site_id': site.id})
        with self.assertRaises(AccessError):
            order.with_user(sales).action_sipanel_project_site_fiscal_change()
        # a context flag without the internal token is not a bypass
        with self.assertRaisesRegex(UserError, FISCAL_BLOCK_CODE):
            order.with_user(sales).with_context(**{FISCAL_CHANGE_GUARD: True, 'sipanel_guard_token': 'forged'}).write(
                {'partner_shipping_id': site.id})
        self.assertEqual((order.partner_shipping_id, order.fiscal_position_id), (customer, fp_dom))

    def test_w03_state_stale_preview_and_confirmed_orders_refused(self):
        order, customer, _tax_dom, _tax_exp, fp_dom, fp_foreign = self._fiscal_fixture()
        site = self._foreign_site(customer, fp_foreign)
        manager = self._manager()
        Wizard = self.env['sipanel.project.site.fiscal.change'].with_user(manager)
        wizard = Wizard.create({'order_id': order.id, 'proposed_site_id': site.id, 'confirm': True})
        order.write({'partner_shipping_id': self._site(customer, name='Same FP Site').id})   # allowed: same position
        with self.assertRaisesRegex(UserError, 'changed after this preview'):
            wizard.action_apply()
        order.action_confirm()
        with self.assertRaisesRegex(UserError, 'not in draft'):
            Wizard.create({'order_id': order.id, 'proposed_site_id': site.id})
        self.assertEqual(order.fiscal_position_id, fp_dom)


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_page1')
class TestProjectSiteFiscalChangeSeal(SipanelSaleCase):
    """A sealed SIPANEL Scope revision is historical customer content: the controlled change fails closed."""

    def test_w04_sealed_scope_refused(self):
        order, scope = self._make_order(85.0)
        order.action_quotation_sent()
        self.assertEqual(scope.current_revision_id.state, 'sent_sealed')
        order.action_draft()
        self.assertEqual(order.state, 'draft')
        site = self.env['res.partner'].create({'name': f'{PT} Sealed Site', 'parent_id': self.partner.id, 'type': 'delivery',
                                               'city': f'{PT}-SealCity'})
        with self.assertRaisesRegex(UserError, 'sealed'):
            self.env['sipanel.project.site.fiscal.change'].with_user(self.sales_mgr).create(
                {'order_id': order.id, 'proposed_site_id': site.id})
