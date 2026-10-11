# -*- coding: utf-8 -*-
"""P9 post-checks of the quotation-lines deployment (READ-ONLY: everything is rolled back at the end).

Same script on the P1 clone and on Production (owner decision 2026-10-08):
  docker exec -i -e OUT=/tmp/sipanel_p9 odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d sipanel --no-http < this
  docker cp odoo-sipanel:/tmp/sipanel_p9 <evidence dir>
Writes p9_SI-26-2546_{fa_IR,en_US}.pdf and p9_summary.json to OUT; prints "SIPANEL_P9 {...}".

Checks: module installed; Standing Seam v3 (three new versions released, previous superseded with intact checksum,
supply-only description, fa_IR label, no installation work, no release warnings - ru_RU archived by P6b); master data
(SIP-000075 in Units, installation base flags, System mapping); SI-26/2546 after way A (quotation, totals, the
installation line, supply lines, amount in words); the commercial terms and data of P6b; the quotation form as the Sales user uid 10 (installation line
readonly); the two PDFs. Rendering switches the partner language inside this transaction (rolled back).
"""
import json
import os

OUT = os.environ.get('OUT', '/tmp/sipanel_p9')
os.makedirs(OUT, exist_ok=True)
SALES_UID = int(os.environ.get('SIPANEL_P9_SALES_UID', '10'))
UNTAXED, TAX, TOTAL, INSTALL_10 = 27_352_380_000, 2_735_238_000, 30_087_618_000, 2_486_580_000
SUPPLY_LINES = [('SIP-000074', 206.0, 88_000_000), ('SIP-000076', 162.7, 34_000_000), ('SIP-000077', 18.0, 67_000_000)]
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
         'incoterm': 'EXW', 'site': 'طالقان', 'contact_prefix': 'جناب آقای ', 'vat_fa': 'مالیات بر ارزش افزوده',
         'meter_fa': 'متر طول', 'tagline_fa': 'طراحی، تأمین و نصب انواع سامانه‌های پوشش سالن‌های صنعتی',
         'terms_lines': ('اعتبار این پیش‌فاکتور تا تاریخ درج‌شده در بالای آن است.',
                         'قیمت‌ها بدون احتساب هزینه حمل، داربست، جرثقیل، اسکان و خوراک پرسنل نصب می‌باشد.',
                         'مقادیر نهایی بر اساس متره اجرایی و صورت‌وضعیت محاسبه می‌شود.'),
         'lines': {'SIP-000074': 'سیستم پوشش سقف استندینگ سیم (فقط تأمین)',
                   'SIP-000076': 'فلاشینگ و فیلر بلوک هم‌جنس ورق رویه (فقط تأمین)',
                   'SIP-000077': 'آبرو ورق گالوانیزه ۱.۵ میلیمتر (فقط تأمین)'}}
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
    il = ref.order_line.filtered(lambda l: l.sipanel_is_installation_line and not l.display_type)
    ordered = ref.order_line.sorted(lambda l: (l.sequence, l.id))
    supply = ref.order_line.filtered(lambda l: not l.display_type and not l.sipanel_is_installation_line)
    R['si26_2546'] = {
        'state': ref.state, 'untaxed': ref.amount_untaxed, 'tax': ref.amount_tax, 'total': ref.amount_total,
        'pct': ref.sipanel_installation_pct, 'requested_system': ref.sipanel_requested_system_id.name,
        'lines': [(l.sequence, l.display_type or l.product_id.default_code, ' '.join((l.name or '').split())[:60],
                   l.product_uom_qty, l.product_uom_id.name, l.price_unit, l.price_subtotal)
                  for l in ordered],
        'words_fa': ref.with_context(lang='fa_IR')._sipanel_amount_total_in_words(),
        'words_en': ref.with_context(lang='en_US')._sipanel_amount_total_in_words()}
    R['unit_name'] = {lang: unit.with_context(lang=lang).name for lang in ('en_US', 'fa_IR')}
    check('si26_2546_quotation', len(ref) == 1 and ref.state == 'draft', ref.state)
    check('si26_2546_totals', close(ref.amount_untaxed, UNTAXED) and close(ref.amount_tax, TAX)
          and close(ref.amount_total, TOTAL), [ref.amount_untaxed, ref.amount_tax, ref.amount_total])
    check('si26_2546_installation_line', len(il) == 1 and il.product_id == install and il.product_uom_qty == 1.0
          and il.product_uom_id == unit and close(il.price_unit, INSTALL_10) and close(il.price_subtotal, INSTALL_10),
          R['si26_2546']['lines'][-1:])
    check('si26_2546_installation_last', bool(il) and ordered[-1] == il)
    check('si26_2546_supply_lines', sorted((l.product_id.default_code, l.product_uom_qty, l.price_unit) for l in supply)
          == sorted((c, q, float(p)) for c, q, p in SUPPLY_LINES))
    check('si26_2546_words_en', R['si26_2546']['words_en'] == 'Thirty Billion, Eighty-Seven Million, Six Hundred And '
                                                              'Eighteen Thousand Rials only', R['si26_2546']['words_en'])
    check('si26_2546_words_fa', R['si26_2546']['words_fa'] == 'سی میلیارد و هشتاد و هفت میلیون و ششصد و هجده هزار ریال',
          R['si26_2546']['words_fa'])

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
    names = {l.product_id.default_code: l.name for l in supply}
    check('si26_2546_line_descriptions', names == TERMS['lines'] and 'ARCZIP' not in str(texts['lines']), names)
    notes = [(l.display_type, l.name) for l in ordered if l.display_type and not l.sipanel_is_installation_line]
    check('si26_2546_sections_notes', notes == [('line_section', 'سیستم پوشش سقف استندینگ سیم'),
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
    check('si26_2546_project_site_printed_once', ref._sipanel_project_site_address_lines() == [],
          ref._sipanel_project_site_address_lines())
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
    for lang in ('fa_IR', 'en_US'):
        ref.partner_id.lang = lang
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
