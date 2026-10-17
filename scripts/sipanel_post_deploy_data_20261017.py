# -*- coding: utf-8 -*-
"""Production step P10 (owner, 2026-10-17, after P9 passed): English names, list prices, the canonical SKU sequence,
English commercial terms and the Persian label of "Opportunity No.". No contact language is changed, nothing is
deleted.

  1  en_US product names (fa_IR names unchanged):
       SIP-000074 "Standing Seam Roof and Wall Cladding System (Supply Only)"
       SIP-000076 "Flashing, Same Material as Top Sheet, Developed Width up to 58 cm (Supply Only)"
       SIP-000085 "Flashing, Same Material as Top Sheet, Developed Width up to 20 cm (Supply Only)"
       SIP-000077 "Gutter, Galvanized Sheet 1.5 mm (Supply Only)"
  2  list prices: SIP-000074 88,000,000 (m²), SIP-000077 67,000,000 (m)
  3  ir.sequence sipanel.product.canonical (prefix SIP-): next number = highest existing SIP-nnnnnn + 1 (the sequence
     is only set, not consumed)
  4  company Default Terms (res.company.invoice_terms): the en_US source becomes the English text of the three lines,
     the Persian text stays as the fa_IR translation (new quotations copy the terms in the customer's language);
     payment term 11 en_US name "70% advance payment, 30% balance before loading" (fa_IR unchanged).
     Existing quotations keep their own note (SI-26/2546 unchanged).
  5  fa_IR label «شماره فرصت فروش» for the field label "Opportunity No." (cyan_crm_reference*: crm.lead, sale.order,
     account.move, account.bank.statement.line, project.project); en_US unchanged.

Run (odoo shell):  docker exec -i [-e SIPANEL_P10_COMMIT=1] odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d sipanel --no-http < this
Dry run without SIPANEL_P10_COMMIT=1. Commits only when every check passes. Idempotent. Prints the before/after diff of
every value it touches (SIPANEL_P10_DIFF). After this step the P6b / P8c / P9 scripts of 2026-10-17 are not re-runnable
as they are (they expect the earlier English names / terms) - by design they refuse (fail closed).
"""
import json
import os
import re

R = {'db': env.cr.dbname, 'checks': {}, 'changed': [], 'diff': []}
env = env(su=True)
EN_NAMES = {
    'SIP-000074': 'Standing Seam Roof and Wall Cladding System (Supply Only)',
    'SIP-000076': 'Flashing, Same Material as Top Sheet, Developed Width up to 58 cm (Supply Only)',
    'SIP-000085': 'Flashing, Same Material as Top Sheet, Developed Width up to 20 cm (Supply Only)',
    'SIP-000077': 'Gutter, Galvanized Sheet 1.5 mm (Supply Only)',
}
FA_NAMES = {   # P8c, unchanged here (checked)
    'SIP-000074': 'سیستم پوشش سقف و دیوار استندینگ سیم (فقط تأمین)',
    'SIP-000076': 'فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۵۸ سانتی‌متر (فقط تأمین)',
    'SIP-000085': 'فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۲۰ سانتی‌متر (فقط تأمین)',
    'SIP-000077': 'آبرو ورق گالوانیزه ۱.۵ میلیمتر (فقط تأمین)',
}
LIST_PRICES = {'SIP-000074': 88_000_000, 'SIP-000077': 67_000_000}
TERMS_FA = ('اعتبار این پیش‌فاکتور تا تاریخ درج‌شده در بالای آن است.',
            'قیمت‌ها بدون احتساب هزینه حمل، داربست، جرثقیل، اسکان و خوراک پرسنل نصب می‌باشد.',
            'مقادیر این پیش‌فاکتور تقریبی است. مقادیر دقیق پس از تهیه‌ی نقشه‌های اجرایی (شاپ) استخراج می‌شود و ملاک محاسبه خواهد بود.')
TERMS_EN = ('This quotation is valid until the date stated above.',
            'Prices exclude transport, scaffolding, crane, and accommodation and meals for the installation crew.',
            'Quantities in this quotation are approximate. Exact quantities will be taken from the shop drawings and '
            'will be the basis of the final calculation.')
TERMS_EN_HTML = '<div data-oe-version="2.0">' + '</div><div>'.join(TERMS_EN) + '</div>'
PAYMENT_TERM_ID = 11
PAYMENT_EN_OLD, PAYMENT_EN_NEW = '70% in advance, 30% before delivery.', '70% advance payment, 30% balance before loading'
PAYMENT_FA = '۷۰٪ پیش‌پرداخت، ۳۰٪ باقیمانده قبل از بارگیری'
OPPORTUNITY_EN, OPPORTUNITY_FA = 'Opportunity No.', 'شماره فرصت فروش'
OPPORTUNITY_FIELDS = [('crm.lead', 'opportunity_no'), ('sale.order', 'opportunity_no'), ('account.move', 'opportunity_refs'),
                      ('account.bank.statement.line', 'opportunity_refs'), ('project.project', 'opportunity_refs')]
SEQ_CODE = 'sipanel.product.canonical'


def check(name, ok, detail=None):
    R['checks'][name] = {'ok': bool(ok), 'detail': detail}


def changed(what):
    R['changed'].append(what)


def stored(record, field):
    record.flush_recordset([field])
    env.cr.execute(f'SELECT "{field}" FROM "{record._table}" WHERE id = %s', (record.id,))
    return env.cr.fetchone()[0] or {}


def text(html):
    return [' '.join(re.sub(r'<[^>]+>', ' ', d).replace('&nbsp;', ' ').split())
            for d in re.findall(r'<div[^>]*>(.*?)</div>', html or '', re.S)]


def diff(what, before, after):
    if before != after:
        R['diff'].append({'what': what, 'before': before, 'after': after})


try:
    Product = env['product.product'].with_context(active_test=False)
    prods = {c: Product.search([('default_code', '=', c)]) for c in EN_NAMES}
    check('products_found', all(len(p) == 1 for p in prods.values()), {c: p.ids for c, p in prods.items()})
    for code, p in prods.items():
        p.ensure_one()
        tmpl = p.product_tmpl_id
        before = stored(tmpl, 'name')
        check(f'{code}_fa_name_unchanged', before.get('fa_IR') == FA_NAMES[code], before)
        if before.get('en_US') != EN_NAMES[code]:
            # en_US source written with the fa_IR term passed along (Odoo 19: a lone key would rebuild the source)
            tmpl.update_field_translations('name', {'en_US': EN_NAMES[code], 'fa_IR': before['fa_IR']})
            changed(f'{code} en_US name')
        after = stored(tmpl, 'name')
        diff(f'{code} name', before, after)
        check(f'{code}_name', after.get('en_US') == EN_NAMES[code] and after.get('fa_IR') == FA_NAMES[code]
              and set(after) == set(before) | {'en_US'}, after)
    for code, price in LIST_PRICES.items():
        tmpl = prods[code].product_tmpl_id
        before = tmpl.list_price
        check(f'{code}_list_price_expected_before', before in (0.0, float(price)), before)
        if before != price:
            tmpl.list_price = price
            changed(f'{code} list price {price:,}')
        diff(f'{code} list price ({tmpl.uom_id.name})', before, tmpl.list_price)
        check(f'{code}_list_price', tmpl.list_price == price, [tmpl.list_price, tmpl.uom_id.name])

    # ---- 3: canonical SKU sequence
    seq = env['ir.sequence'].search([('code', '=', SEQ_CODE)])
    check('sequence_found', len(seq) == 1 and seq.prefix == 'SIP-' and seq.padding == 6, seq.ids)
    seq.ensure_one()
    codes = Product.search([('default_code', '=like', 'SIP-%')]).mapped('default_code')
    numbers = [int(c[4:]) for c in codes if re.fullmatch(r'SIP-\d{6}', c)]
    target = max(numbers) + 1
    before = seq.number_next_actual
    check('sequence_expected_before', before <= target, [before, target])
    if before != target:
        seq.number_next_actual = target
        changed(f'ir.sequence {seq.id} next number {before} -> {target}')
    seq.invalidate_recordset()
    diff(f'ir.sequence {SEQ_CODE} next number', before, seq.number_next_actual)
    nxt = f'SIP-{seq.number_next_actual:06d}'
    R['sequence'] = {'highest': f'SIP-{max(numbers):06d}', 'next': nxt, 'implementation': seq.implementation}
    check('sequence_next_free', seq.number_next_actual == target and not Product.search_count([('default_code', '=', nxt)]),
          R['sequence'])

    # ---- 4: English terms (company default) + payment term name
    company = env.ref('base.main_company')
    before = stored(company, 'invoice_terms')
    check('terms_expected_before', text(before.get('en_US')) in (list(TERMS_FA), list(TERMS_EN)), before)
    if text(before.get('en_US')) == list(TERMS_FA):
        company.with_context(lang='en_US').invoice_terms = TERMS_EN_HTML
        # Html(translate=True) is term-translated in Odoo 19: the fa_IR value = each English line -> its Persian line
        company.update_field_translations('invoice_terms', {'fa_IR': dict(zip(TERMS_EN, TERMS_FA))})
        changed('res.company invoice_terms: en_US English, fa_IR Persian')
    after = stored(company, 'invoice_terms')
    diff('res.company invoice_terms', before, after)
    check('terms_en_fa', text(after.get('en_US')) == list(TERMS_EN) and text(after.get('fa_IR')) == list(TERMS_FA),
          {k: text(v) for k, v in after.items()})
    check('terms_read_per_language', text(company.with_context(lang='fa_IR').invoice_terms) == list(TERMS_FA)
          and text(company.with_context(lang='en_US').invoice_terms) == list(TERMS_EN))
    term = env['account.payment.term'].browse(PAYMENT_TERM_ID).exists()
    before = stored(term, 'name') if term else {}
    check('payment_term_expected_before', before.get('en_US') in (PAYMENT_EN_OLD, PAYMENT_EN_NEW)
          and before.get('fa_IR') == PAYMENT_FA, before)
    if term and before.get('en_US') == PAYMENT_EN_OLD:
        term.update_field_translations('name', {'en_US': PAYMENT_EN_NEW, 'fa_IR': PAYMENT_FA})
        changed(f'account.payment.term {term.id} en_US name')
    after = stored(term, 'name') if term else {}
    diff('account.payment.term 11 name', before, after)
    check('payment_term_names', after == dict(before, en_US=PAYMENT_EN_NEW), after)

    # ---- 5: "Opportunity No." in Persian
    Fields = env['ir.model.fields']
    for model, fname in OPPORTUNITY_FIELDS:
        f = Fields._get(model, fname)
        before = stored(f, 'field_description') if f else {}
        check(f'opportunity_{model}_expected_before', bool(f) and before.get('en_US') == OPPORTUNITY_EN
              and before.get('fa_IR') in (None, OPPORTUNITY_FA), before)
        if f and before.get('en_US') == OPPORTUNITY_EN and before.get('fa_IR') != OPPORTUNITY_FA:
            f.update_field_translations('field_description', {'en_US': OPPORTUNITY_EN, 'fa_IR': OPPORTUNITY_FA})
            changed(f'ir.model.fields {model}.{fname} fa_IR label')
        after = stored(f, 'field_description') if f else {}
        diff(f'label {model}.{fname}', before, after)
        check(f'opportunity_{model}', after == {'en_US': OPPORTUNITY_EN, 'fa_IR': OPPORTUNITY_FA}, after)

    # ---- untouched: SI-26/2546, contact languages
    ref = env['sale.order'].search([('name', '=', 'SI-26/2546')])
    R['si26_2546'] = {'totals': [ref.amount_untaxed, ref.amount_tax, ref.amount_total], 'state': ref.state,
                      'printable': ref._sipanel_customer_document_problems()}
    check('si26_2546_unchanged', abs(ref.amount_untaxed - 27_364_418_400) < 0.5 and abs(ref.amount_total - 30_100_860_240) < 0.5
          and ref.state == 'draft' and not R['si26_2546']['printable'], R['si26_2546'])
except (AssertionError, ValueError) as exc:
    import traceback
    R['error'] = traceback.format_exc()

R['all_ok'] = all(c['ok'] for c in R['checks'].values()) and 'error' not in R
print('SIPANEL_P10 ' + json.dumps({'all_ok': R['all_ok'], 'failed': [k for k, c in R['checks'].items() if not c['ok']],
                                   'changed': R['changed'], 'error': R.get('error', '')[-600:]}, ensure_ascii=False))
print('SIPANEL_P10_DIFF ' + json.dumps(R['diff'], ensure_ascii=False, default=str))
print('SIPANEL_P10_DETAIL ' + json.dumps(R, ensure_ascii=False, default=str))
if os.environ.get('SIPANEL_P10_COMMIT') == '1' and R['all_ok']:
    env.cr.commit()
    print('SIPANEL_P10 COMMITTED')
else:
    env.cr.rollback()
    print('SIPANEL_P10 ROLLED_BACK')
