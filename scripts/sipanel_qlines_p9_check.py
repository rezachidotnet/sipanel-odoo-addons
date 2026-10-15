# -*- coding: utf-8 -*-
"""P9 post-checks of the quotation-lines deployment (READ-ONLY: everything is rolled back at the end).

Same script on the P1 clone and on Production (owner decision 2026-10-08):
  docker exec -i -e OUT=/tmp/sipanel_p9 odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d sipanel --no-http < this
  docker cp odoo-sipanel:/tmp/sipanel_p9 <evidence dir>
Writes p9_SI-26-2546_{fa_IR,en_US}.pdf and p9_summary.json to OUT; prints "SIPANEL_P9 {...}".

Checks: module installed; Standing Seam v3 (three new versions released, previous superseded with intact checksum,
supply-only description, fa_IR label, no installation work, no release warnings - ru_RU archived by P6b); master data
(SIP-000075 in Units, installation base flags, System mapping); SI-26/2546 after way A (quotation, totals, the
installation line, supply lines, amount in words); the commercial terms and data of P6b; the technical sheet, shop drawings
line and flashing split of P8b (owner requirements 2026-10-14); the quotation form as the Sales user uid 10 (installation
line readonly); the two PDFs. Rendering switches the partner language inside this transaction (rolled back).
"""
import json
import os

OUT = os.environ.get('OUT', '/tmp/sipanel_p9')
os.makedirs(OUT, exist_ok=True)
SALES_UID = int(os.environ.get('SIPANEL_P9_SALES_UID', '10'))
# owner 2026-10-14 (P8b): flashing 3:1 prices -> supply 24,876,744,000, installation 10 %, shop drawings net 0
UNTAXED, TAX, TOTAL, INSTALL_10 = 27_364_418_400, 2_736_441_840, 30_100_860_240, 2_487_674_400
# P8b (owner requirements 2026-10-14): the flashing line is split 2:1 (108.47 + 54.23 = 162.70 m, same price)
SUPPLY_LINES = [('SIP-000074', 206.0, 88_000_000), ('SIP-000076', 108.47, 43_800_000), ('SIP-000076', 54.23, 14_600_000),
                ('SIP-000077', 18.0, 67_000_000)]
SHOP = {'pct': 2.0, 'discount': 100.0, 'price': 547_288_368, 'label_fa': 'تهیه‌ی نقشه‌های اجرایی (شاپ)',
        'section_fa': 'نقشه‌های اجرایی', 'product_fa': 'تهیه‌ی نقشه‌های اجرایی (شاپ)'}
SHEET = {'rows': 8, 'image_sha256': 'e64859f0257b42676a2a8d910d503e827759047b3ebe2bb9c7dee569c478dfbc',
         'heading_fa': 'مشخصات فنی سیستم استندینگ سیم', 'row2_fa': 'ضخامت ۰.۷ میلیمتر', 'row2_en': '0.7 mm thick',
         'heading_en': 'Technical Specification of the Standing Seam System', 'system_en': 'Standing Seam',
         'system_fa': 'استندینگ سیم', 'material': ('Top sheet material', 'جنس ورق رویه'),
         'row7_fa': 'ورق فولادی گالوانیزه‌ی پیش‌رنگ به ضخامت ۰.۵ میلیمتر', 'row7_en': 'Pre-painted galvanized steel sheet',
         'row8_fa': 'سازه‌ی نگهدارنده (پرلین)',
         'liner': '0.7'}
EXPECTED = {  # scope code: (new version name, previous version name, fa_IR label, description)
    'CS-STANDING-SEAM': ('CS-STANDING-SEAM v3', 'CS-STANDING-SEAM v2', 'سیستم پوشش سقف استندینگ سیم',
                         {'en_US': 'Supply of Standing Seam roof system (supply only).',
                          'fa_IR': 'تأمین سیستم سقف استندینگ سیم (فقط تأمین).'}),
    'CS-STANDING-SEAM-FLASHING': ('CS-STANDING-SEAM-FLASHING v2', 'CS-STANDING-SEAM-FLASHING v1', 'فلاشینگ',
                                  {'en_US': 'Supply of flashing & sealing package (supply only).',
                                   'fa_IR': 'تأمین پکیج فلاشینگ و آب‌بندی (فقط تأمین).'}),
    'CS-STANDING-SEAM-GUTTER': ('CS-STANDING-SEAM-GUTTER v2', 'CS-STANDING-SEAM-GUTTER v1', 'آبرو',
                                {'en_US': 'Supply of gutter system (supply only).',
                                 'fa_IR': 'تأمین سیستم ناودان (فقط تأمین).'}),
}
# P6b archives ru_RU before P7, so v3 is released without the R2 "no ru_RU label" warning (requirements 2026-10-08)
TERMS = {'payment_term_en': '70% in advance, 30% before delivery.', 'delivery_days': 45, 'validity_days': 8,
         'payment_term_fa': '۷۰٪ پیش‌پرداخت، ۳۰٪ باقیمانده قبل از بارگیری', 'site_line_fa': 'شهرستان طالقان - ایران',
         'salesperson': ('Taleghani', 'طالقانی'), 'website': 'www.sipanelco.com',
         'incoterm': 'EXW', 'site': 'طالقان', 'contact_prefix': 'جناب آقای ', 'vat_fa': 'مالیات بر ارزش افزوده',
         'meter_fa': 'متر طول', 'tagline_fa': 'طراحی، تأمین و نصب انواع سامانه‌های پوشش سالن‌های صنعتی',
         'terms_lines': ('اعتبار این پیش‌فاکتور تا تاریخ درج‌شده در بالای آن است.',
                         'قیمت‌ها بدون احتساب هزینه حمل، داربست، جرثقیل، اسکان و خوراک پرسنل نصب می‌باشد.',
                         'مقادیر این پیش‌فاکتور تقریبی است. مقادیر دقیق پس از تهیه‌ی نقشه‌های اجرایی (شاپ) استخراج می‌شود و ملاک محاسبه خواهد بود.'),
         # P8b 2026-10-14: the material chosen on the line follows as the native «جنس ورق رویه: گالوانیزه» line
         'lines': [('SIP-000074', 'سیستم پوشش سقف و دیوار استندینگ سیم (فقط تأمین)\nجنس ورق رویه: گالوانیزه'),
                   ('SIP-000076', 'فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۵۸ سانتی‌متر (فقط تأمین)\nجنس ورق رویه: گالوانیزه'),
                   ('SIP-000076', 'فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۲۰ سانتی‌متر (فقط تأمین)\nجنس ورق رویه: گالوانیزه'),
                   ('SIP-000077', 'آبرو ورق گالوانیزه ۱.۵ میلیمتر (فقط تأمین)')]}
R = {'db': env.cr.dbname, 'checks': {}}
su = env(su=True)


def check(name, ok, detail=None):
    R['checks'][name] = {'ok': bool(ok), 'detail': detail}


def close(a, b):
    return abs((a or 0.0) - b) < 0.5


def stored(record, field):
    su.cr.execute(f'SELECT "{field}" FROM {record._table} WHERE id = %s', (record.id,))
    return su.cr.fetchone()[0] or {}


try:
    mod = su['ir.module.module'].search([('name', '=', 'sipanel_quotation_lines')])
    check('module_installed', mod.state == 'installed', [mod.state, mod.latest_version])

    # ---- Standing Seam v3
    install = su['product.product'].with_context(active_test=False).search([('default_code', '=', 'SIP-000075')])
    work = su['product.product']._sipanel_installation_work_products() | install
    Version = su['sipanel.scope.version'].with_context(active_test=False)
    R['v3'] = {}
    for code, (new_name, prev_name, label_fa, desc) in EXPECTED.items():
        scope = su['sipanel.scope'].search([('code', '=', code)])
        cur, prev = scope.current_version_id, Version.search([('scope_id', '=', scope.id), ('name', '=', prev_name)])
        warnings = [str(m.body) for m in cur.message_ids if 'Release warning' in str(m.body)]
        label, description = stored(cur, 'customer_label'), stored(cur, 'customer_description')
        R['v3'][code] = {'current': cur.name, 'state': cur.state, 'previous_state': prev.state,
                         'previous_checksum_ok': prev.verify_release_checksum() if prev else None,
                         'label': label, 'description': description, 'release_warnings': warnings,
                         'recipe': [(l.sequence, l.product_id.default_code) for l in cur.recipe_line_ids.sorted('sequence')]}
        check(f'{code}_released', len(scope) == 1 and cur.name == new_name and cur.state == 'released', R['v3'][code]['current'])
        check(f'{code}_previous_superseded', len(prev) == 1 and prev.state == 'superseded' and prev.verify_release_checksum(),
              [prev.state, R['v3'][code]['previous_checksum_ok']])
        check(f'{code}_label_fa', label.get('fa_IR') == label_fa and bool(label.get('en_US')), label)
        check(f'{code}_description', {k: description.get(k) for k in desc} == desc, description)
        check(f'{code}_no_installation_work',
              not cur.recipe_line_ids.filtered(lambda l: l.responsibility == 'sipanel' and l.product_id in work))
        check(f'{code}_no_release_warnings', not warnings, warnings)

    # ---- master data
    unit = su.ref('uom.product_uom_unit')
    check('M4_sip_000075_in_units', install.uom_id == unit, install.uom_id.name)
    base = su['product.product'].with_context(active_test=False).search(
        [('default_code', 'in', [c for c, _q, _p in SUPPLY_LINES])])
    check('installation_base_flags', len(base) == 3 and all(base.product_tmpl_id.mapped('sipanel_installation_base')),
          base.mapped('default_code'))
    seam = su['account.analytic.account'].with_context(lang='en_US').search(
        [('name', '=', 'Standing Seam'), ('active', '=', True)])
    check('standing_seam_maps_sip_000075', len(seam) == 1 and seam.sipanel_installation_product_id == install,
          seam.ids)
    R['account_2316_name'] = stored(seam, 'name') if len(seam) == 1 else None

    # ---- SI-26/2546 after way A
    ref = su['sale.order'].search([('name', '=', 'SI-26/2546')])
    il = ref._sipanel_managed_lines('installation').filtered(lambda l: not l.display_type)
    shop_block = ref._sipanel_managed_lines('shop_drawing').sorted(lambda l: (l.sequence, l.id))
    sl = shop_block.filtered(lambda l: not l.display_type)
    ordered = ref.order_line.sorted(lambda l: (l.sequence, l.id))
    supply = ref.order_line.filtered(lambda l: not l.display_type and not l.sipanel_is_installation_line)
    R['si26_2546'] = {
        'state': ref.state, 'untaxed': ref.amount_untaxed, 'tax': ref.amount_tax, 'total': ref.amount_total,
        'pct': ref.sipanel_installation_pct, 'requested_system': ref.sipanel_requested_system_id.name,
        'lines': [(l.sequence, l.display_type or l.product_id.default_code, ' '.join((l.name or '').split())[:60],
                   l.product_uom_qty, l.product_uom_id.name, l.price_unit, l.discount, l.price_subtotal,
                   l.sipanel_managed_role) for l in ordered],
        'words_fa': ref.with_context(lang='fa_IR')._sipanel_amount_total_in_words(),
        'words_en': ref.with_context(lang='en_US')._sipanel_amount_total_in_words()}
    R['unit_name'] = {lang: unit.with_context(lang=lang).name for lang in ('en_US', 'fa_IR')}
    check('si26_2546_quotation', len(ref) == 1 and ref.state == 'draft', ref.state)
    check('si26_2546_totals', close(ref.amount_untaxed, UNTAXED) and close(ref.amount_tax, TAX)
          and close(ref.amount_total, TOTAL), [ref.amount_untaxed, ref.amount_tax, ref.amount_total])
    check('si26_2546_installation_line', len(il) == 1 and il.product_id == install and il.product_uom_qty == 1.0
          and il.product_uom_id == unit and close(il.price_unit, INSTALL_10) and close(il.price_subtotal, INSTALL_10),
          R['si26_2546']['lines'][-1:])
    # owner requirements 2026-10-14: the shop drawings block (section + line) comes right after the installation line
    check('si26_2546_installation_last', bool(il) and len(shop_block) == 2 and ordered[-3] == il
          and list(ordered[-2:]) == list(shop_block))
    check('si26_2546_shop_line', len(sl) == 1 and sl.product_uom_qty == 1.0 and close(sl.price_unit, SHOP['price'])
          and sl.discount == SHOP['discount'] and close(sl.price_subtotal, 0) and close(sl.price_tax, 0)
          and sl.name.split('\n')[0] == SHOP['label_fa'] and shop_block[0].name == SHOP['section_fa']
          and (ref.sipanel_shop_drawing_pct, ref.sipanel_shop_drawing_discount) == (SHOP['pct'], SHOP['discount']),
          R['si26_2546']['lines'][-2:])
    seam_shop = seam.sipanel_shop_drawing_product_id if len(seam) == 1 else su['product.product']
    check('standing_seam_maps_shop_product', bool(seam_shop) and sl.product_id == seam_shop
          and seam_shop.type == 'service' and not seam_shop.purchase_ok
          and stored(seam_shop.product_tmpl_id, 'name').get('fa_IR') == SHOP['product_fa'],
          stored(seam_shop.product_tmpl_id, 'name') if seam_shop else None)
    check('si26_2546_supply_lines', sorted((l.product_id.default_code, l.product_uom_qty, l.price_unit) for l in supply)
          == sorted((c, q, float(p)) for c, q, p in SUPPLY_LINES),
          sorted((l.product_id.default_code, l.product_uom_qty, l.price_unit) for l in supply))
    # ---- technical sheet (P8b)
    import base64
    import hashlib
    sha = lambda b64: hashlib.sha256(base64.b64decode(b64)).hexdigest() if b64 else None
    sys_rows = [(r.number, stored(r, 'title'), stored(r, 'description')) for r in seam.sipanel_tech_spec_ids.sorted(
        lambda r: (r.sequence, r.number, r.id))] if len(seam) == 1 else []
    sys_linked = [bool(r.attribute_id) for r in seam.sipanel_tech_spec_ids.sorted(
        lambda r: (r.sequence, r.number, r.id))] if len(seam) == 1 else []
    so_rows = [(r.number, stored(r, 'title'), stored(r, 'description')) for r in ref.sipanel_tech_spec_ids.sorted(
        lambda r: (r.sequence, r.number, r.id))]
    R['tech_sheet'] = {'system_rows': sys_rows, 'printed_fa': ref.with_context(lang='fa_IR')._sipanel_tech_sheet_rows(),
                       'printed_en': ref.with_context(lang='en_US')._sipanel_tech_sheet_rows(),
                       'liner': ref.sipanel_liner_thickness}
    check('system_tech_sheet', len(sys_rows) == SHEET['rows'] and [n for n, _t, _d in sys_rows] == list(range(1, 9))
          # a row linked to an attribute (row 7, top-sheet material) has no text of its own: it prints the chosen value's
          and all(t.get('fa_IR') and t.get('en_US') and (linked or d.get('fa_IR') and d.get('en_US'))
                  for (_n, t, d), linked in zip(sys_rows, sys_linked))
          and sys_linked == [n == 7 for n in range(1, 9)]
          and sha(seam.sipanel_tech_image) == SHEET['image_sha256'], [n for n, _t, _d in sys_rows])
    check('si26_2546_tech_sheet_snapshot', so_rows == sys_rows and sha(ref.sipanel_tech_image) == SHEET['image_sha256'])
    check('si26_2546_liner_0_7', ref.sipanel_liner_thickness == SHEET['liner']
          and SHEET['row2_fa'] in R['tech_sheet']['printed_fa'][1][2] and SHEET['row2_en'] in R['tech_sheet']['printed_en'][1][2]
          if len(so_rows) >= 2 else False, R['tech_sheet']['printed_fa'][1:2])
    printed_fa, printed_en = R['tech_sheet']['printed_fa'], R['tech_sheet']['printed_en']
    check('si26_2546_row7_galvanized', len(printed_fa) == 8 and printed_fa[6][2].startswith(SHEET['row7_fa'])
          and printed_en[6][2].startswith(SHEET['row7_en']), [printed_fa[6:7], printed_en[6:7]])
    check('si26_2546_row8_purlin', len(printed_fa) == 8 and printed_fa[7][1] == SHEET['row8_fa'], printed_fa[7:8])
    attr = su['product.attribute'].with_context(lang='en_US').search([('name', '=', SHEET['material'][0])])
    galv = attr.value_ids.sorted(lambda v: (v.sequence, v.id))[:1]
    alu = attr.value_ids - galv
    R['material'] = {'attribute': stored(attr, 'name') if len(attr) == 1 else None, 'create_variant': attr.create_variant,
                     'values': [(stored(v, 'name'), v.sipanel_price_required) for v in attr.value_ids],
                     'price_extras': [(p.product_tmpl_id.default_code, p.name, p.price_extra) for p in
                                      su['product.template.attribute.value'].search([('attribute_id', 'in', attr.ids)])]}
    check('material_attribute_native_no_variant', len(attr) == 1 and attr.create_variant == 'no_variant'
          and stored(attr, 'name').get('fa_IR') == SHEET['material'][1] and len(attr.value_ids) == 2
          and alu.sipanel_price_required and not galv.sipanel_price_required, R['material'])
    priced = ref.order_line.filtered(lambda l: l.product_id.default_code in ('SIP-000074', 'SIP-000076'))
    check('si26_2546_material_galvanized', len(priced) == 3 and all(
        l.product_no_variant_attribute_value_ids.product_attribute_value_id == galv for l in priced)
          and all(len(l.product_id.product_tmpl_id.with_context(active_test=False).product_variant_ids) == 1 for l in priced),
          [(l.id, l.product_no_variant_attribute_value_ids.mapped('name')) for l in priced])
    # aluminium with price extra 0 blocks printing (rolled back with the rest of this read-only check)
    if alu and priced:
        alu_ptav = priced[0].product_id.product_tmpl_id.attribute_line_ids.product_template_value_ids.filtered(
            lambda p: p.product_attribute_value_id == alu)
        class Probe(Exception):
            pass
        problems = None
        try:
            with su.cr.savepoint():
                priced[0].product_no_variant_attribute_value_ids = [(6, 0, alu_ptav.ids)]
                problems = ref._sipanel_customer_document_problems()
                raise Probe
        except Probe:
            pass
        su.invalidate_all()
        R['aluminium_probe'] = problems
        check('aluminium_without_price_blocks', 'قیمت گزینه‌ی آلومینیوم تعیین نشده است' in (problems or []), problems)
        check('aluminium_probe_undone', all(l.product_no_variant_attribute_value_ids.product_attribute_value_id == galv
                                            for l in priced))
    names = {lang: ref.with_context(lang=lang)._sipanel_system_print_label() for lang in ('en_US', 'fa_IR')}
    check('si26_2546_system_name_per_language', names == {'en_US': SHEET['system_en'], 'fa_IR': SHEET['system_fa']}, names)
    # 30,100,860,240 (owner 2026-10-14): native words, reported in p9_summary.json for review
    words_en, words_fa = R['si26_2546']['words_en'], R['si26_2546']['words_fa']
    check('si26_2546_words_en', words_en.startswith('Thirty Billion, One Hundred Million, Eight Hundred')
          and 'Sixty Thousand' in words_en and words_en.endswith('Forty Rials only'), words_en)
    check('si26_2546_words_fa', words_fa.startswith('سی میلیارد') and 'شصت هزار' in words_fa and 'چهل' in words_fa
          and words_fa.endswith('ریال'), words_fa)

    # ---- commercial terms and data (P6b, requirements 2026-10-08 items 2-12)
    import datetime
    import pytz
    tehran = pytz.timezone('Asia/Tehran')
    order_day = ref.date_order.replace(tzinfo=pytz.utc).astimezone(tehran).date()
    company = ref.company_id
    texts = {
        'note': ' '.join(str(ref.note or '').replace('&nbsp;', ' ').split()),
        'company_terms': ' '.join((stored(company, 'invoice_terms').get('en_US') or '').split()),
        'header_fa': stored(company, 'report_header').get('fa_IR'),
        'lines': [(l.display_type or l.product_id.default_code, l.name) for l in ordered]}
    R['si26_2546_terms'] = dict(texts, payment_term=ref.payment_term_id.with_context(lang='en_US').name,
                                delivery_days=ref.sipanel_delivery_days, bank=ref.sipanel_show_bank_account,
                                incoterm=ref.incoterm.code, date_order=str(ref.date_order),
                                validity=str(ref.validity_date), commitment=str(ref.commitment_date),
                                site=ref.partner_shipping_id.display_name, contact=ref.partner_id.name,
                                problems=ref._sipanel_customer_document_problems())
    check('si26_2546_printable', ref._sipanel_customer_document_problems() == [],
          ref._sipanel_customer_document_problems())
    check('si26_2546_payment_term', ref.payment_term_id.with_context(lang='en_US').name == TERMS['payment_term_en'])
    check('si26_2546_delivery_days', ref.sipanel_delivery_days == TERMS['delivery_days'])
    check('si26_2546_no_bank_line', not ref.sipanel_show_bank_account)
    check('si26_2546_incoterm_exw', ref.incoterm.code == TERMS['incoterm'], ref.incoterm.code)
    check('si26_2546_dates', ref.validity_date == order_day + datetime.timedelta(days=TERMS['validity_days'])
          and not ref._sipanel_customer_document_problems() and not ref.commitment_date, [str(ref.date_order), str(ref.validity_date)])
    check('si26_2546_project_site', ref._sipanel_page1_project_site().name == TERMS['site'],
          ref.partner_shipping_id.display_name)
    check('si26_2546_contact', ref.partner_id.name.startswith(TERMS['contact_prefix']), ref.partner_id.name)
    check('si26_2546_note', all(t in texts['note'] for t in TERMS['terms_lines']) and '...' not in texts['note'],
          texts['note'])
    check('company_default_terms', all(t in texts['company_terms'] for t in TERMS['terms_lines'])
          and '...' not in texts['company_terms'], texts['company_terms'])
    check('company_tagline_fa', TERMS['tagline_fa'] in (texts['header_fa'] or ''), texts['header_fa'])
    names = sorted((l.product_id.default_code, l.name) for l in supply)
    check('si26_2546_line_descriptions', names == sorted(TERMS['lines']) and 'ARCZIP' not in str(texts['lines']), names)
    notes = [(l.display_type, l.name) for l in ordered if l.display_type and not l.sipanel_is_installation_line]
    check('si26_2546_sections_notes', notes == [('line_section', 'سیستم پوشش سقف و دیوار استندینگ سیم'),   # P8b
                                                ('line_section', 'متعلقات'),
                                                ('line_note', 'شامل: متعلقات استاندارد سیستم')], notes)
    vat = su['account.tax.group'].search([]).filtered(lambda g: stored(g, 'name').get('en_US') == 'VAT')
    check('vat_group_fa', [stored(g, 'name').get('fa_IR') for g in vat] == [TERMS['vat_fa']],
          [stored(g, 'name') for g in vat])
    check('meter_fa', stored(su.ref('uom.product_uom_meter'), 'name').get('fa_IR') == TERMS['meter_fa'])
    check('account_2316_fa_name', R['account_2316_name'] == {'en_US': 'Standing Seam', 'fa_IR': 'استندینگ سیم'},
          R['account_2316_name'])
    check('si26_2546_requested_system_fa', ref.sipanel_requested_system_name_snapshot == 'استندینگ سیم',
          ref.sipanel_requested_system_name_snapshot)
    # owner review 2026-10-12
    site_line = ref.with_context(lang='fa_IR')._sipanel_project_site_line()
    check('si26_2546_project_site_one_line', site_line == TERMS['site_line_fa'], site_line)
    check('payment_term_fa_name', stored(ref.payment_term_id, 'name').get('fa_IR') == TERMS['payment_term_fa'],
          stored(ref.payment_term_id, 'name'))
    seller = ref.user_id
    check('salesperson_fa_name', (seller.name, seller.sipanel_quotation_name_fa) == TERMS['salesperson']
          and seller.partner_id.name == TERMS['salesperson'][0], [seller.name, seller.sipanel_quotation_name_fa])
    footer = stored(company, 'report_footer')
    check('footer_website', all(TERMS['website'] in v and 'sipanelco.ir' not in v for v in footer.values())
          and set(footer) == {'en_US', 'fa_IR'}, footer)
    ru = su['res.lang'].with_context(active_test=False).search([('code', '=', 'ru_RU')])
    check('ru_RU_archived', len(ru) == 1 and not ru.active)

    # ---- the quotation form as the Sales user (no sudo)
    user = su['res.users'].browse(SALES_UID).exists()
    if user:
        uenv = env(user=user.id, su=False)
        so = uenv['sale.order'].browse(ref.id)
        arch = uenv['sale.order'].get_views([(False, 'form')])['views']['form']['arch']
        data = so.web_read({'name': {}, 'amount_total': {}, 'sipanel_installation_pct': {},
                            'order_line': {'fields': {'product_uom_qty': {}, 'price_unit': {},
                                                      'sipanel_is_installation_line': {}}}})
        check('form_as_sales_user', bool(data) and close(data[0]['amount_total'], TOTAL), [user.login, len(data)])
        from lxml import etree
        qty = etree.fromstring(arch).xpath("//field[@name='order_line']/list/field[@name='product_uom_qty']")
        ro = qty[0].get('readonly', '') if qty else None
        check('form_installation_line_readonly', bool(ro) and 'sipanel_is_installation_line' in ro, ro)
    else:
        check('form_as_sales_user', False, f'uid {SALES_UID} not found')

    # ---- PDFs
    lang0 = ref.partner_id.lang
    R['partner_lang'] = lang0
    from lxml import html as lxml_html
    for lang in ('fa_IR', 'en_US'):
        ref.partner_id.lang = lang
        # owner review 2026-10-12: layout of the printed quotation (HTML of the same report)
        doc = lxml_html.fromstring(su['ir.actions.report']._render_qweb_html('sale.report_saleorder', ref.ids)[0])
        text = ' '.join(doc.text_content().split())
        closing = doc.xpath("//div[@name='sipanel_closing']")
        cells = [c.get('name') for c in closing[0] if c.tag == 'div'] if len(closing) == 1 else None
        terms = closing[0].xpath(".//div[@name='sipanel_terms']") if len(closing) == 1 else []
        terms_text = ' '.join(terms[0].text_content().split()) if terms else ''
        seller_name = TERMS['salesperson'][1] if lang == 'fa_IR' else TERMS['salesperson'][0]
        box = doc.xpath("//div[@id='informations']//div[contains(@class, 'o_sipanel_salesperson')]")
        R.setdefault('layout', {})[lang] = {'cells': cells, 'terms': terms_text,
                                            'salesperson': box[0].text_content().strip() if box else None}
        # owner requirements 2026-10-14: the technical sheet page sits between Page 1 and the price table
        sheet_div = doc.xpath("//div[@name='sipanel_tech_sheet']")
        page_div = doc.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' page ')]")
        cover = doc.xpath("//div[contains(@class, 'custom-full-page-cover')]")
        order_ok = (len(sheet_div) == 1 and len(page_div) == 1 and len(cover) == 1
                    and sheet_div[0].getparent() == page_div[0].getparent() == cover[0].getparent()
                    and cover[0].getparent().index(cover[0]) < sheet_div[0].getparent().index(sheet_div[0])
                    < page_div[0].getparent().index(page_div[0]))
        spec_rows = sheet_div[0].xpath(".//tr[contains(@class, 'o_sipanel_tech_spec_row')]") if sheet_div else []
        heading = ' '.join(sheet_div[0].xpath(".//h4")[0].text_content().split()) if sheet_div else ''
        check(f'layout_{lang}_tech_sheet_page', order_ok and len(spec_rows) == SHEET['rows']
              and 'page-break-after: always' in (sheet_div[0].get('style') or '')
              and bool(sheet_div[0].xpath(".//img[starts-with(@src, 'data:image/png;base64,')]"))
              and heading == SHEET['heading_fa' if lang == 'fa_IR' else 'heading_en'], [order_ok, len(spec_rows), heading])
        system_cell = doc.xpath("//td[contains(@class, 'o_sipanel_page1_requested_system')]")
        check(f'layout_{lang}_page1_system_name', len(system_cell) == 1 and ' '.join(system_cell[0].text_content().split())
              == SHEET['system_fa' if lang == 'fa_IR' else 'system_en'], [c.text_content() for c in system_cell])
        check(f'layout_{lang}_no_incoterm', 'EXW' not in text and 'Incoterm' not in text and 'اینکوترم' not in text)
        check(f'layout_{lang}_signature_left_terms_right', cells == ['sipanel_signature', 'sipanel_terms']
              and closing[0].get('dir') == 'ltr' and not doc.xpath("//div[contains(@class, 'o_sipanel_signature_block')]")
              and closing[0].getparent().index(closing[0]) > 0, cells)
        check(f'layout_{lang}_terms_block', terms_text.startswith(TERMS['terms_lines'][0]) and str(TERMS['delivery_days']) in terms_text and 'جهت شروع تولید' not in text
              and 'is required to commence production' not in text, terms_text)
        check(f'layout_{lang}_salesperson', bool(box) and box[0].text_content().strip() == seller_name
              and (lang != 'fa_IR' or TERMS['salesperson'][0] not in text), R['layout'][lang]['salesperson'])
        if lang == 'fa_IR':
            check('layout_fa_IR_payment_term_one_text', f"شرایط پرداخت: {TERMS['payment_term_fa']}" in terms_text, terms_text)
            cell = doc.xpath("//td[contains(@class, 'o_sipanel_page1_project_site')]")
            check('layout_fa_IR_project_site', len(cell) == 1 and ' '.join(cell[0].text_content().split())
                  == TERMS['site_line_fa'], [c.text_content() for c in cell])
        pdf, _ = su['ir.actions.report']._render_qweb_pdf('sale.report_saleorder', ref.ids)
        with open(os.path.join(OUT, f'p9_SI-26-2546_{lang}.pdf'), 'wb') as f:
            f.write(pdf)
    ref.partner_id.lang = lang0
except Exception:                                    # noqa: BLE001 - reported, then rolled back
    import traceback
    R['error'] = traceback.format_exc()
finally:
    env.cr.rollback()

R['all_ok'] = all(c['ok'] for c in R['checks'].values()) and 'error' not in R
with open(os.path.join(OUT, 'p9_summary.json'), 'w') as f:
    json.dump(R, f, ensure_ascii=False, indent=1, default=str)
print('SIPANEL_P9 ' + json.dumps({'all_ok': R['all_ok'], 'failed': [k for k, c in R['checks'].items() if not c['ok']],
                                  'error': R.get('error', '')[-600:]}, ensure_ascii=False))
