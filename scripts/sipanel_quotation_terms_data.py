# -*- coding: utf-8 -*-
"""Production step P6b of the quotation-lines deployment: commercial data (owner requirements 2026-10-08, items 6-12;
decisions 2026-10-09: payment term 70/30, 45 working days, no bank line, quotation date = run date, validity + 8 days).

Runs after the install (P6: it needs the new delivery-time field) and BEFORE Standing Seam v3 (P7): with ru_RU
archived first, v3 is released without the R2 "no ru_RU translation" warning.

  item 11  language ru_RU archived (0 partners / users use it; not on the website). Reversible: active = True.
  item 6   company Default Terms & Conditions (res.company.invoice_terms, the source of every new quotation's note):
           the placeholder lines are replaced by the three approved lines. SI-26/2546's own note (a copy made when
           it was created) gets the same text. The quotation template "Standing Seam Roof System" has no note.
  item 10  company report header tagline (res.company.report_header, fa_IR); tax group "VAT" fa_IR name
           «مالیات بر ارزش افزوده»; contact of SI-26/2546 «جناب اقای ...» -> «جناب آقای ...».
  item 9   unit of measure meter (uom.product_uom_meter) fa_IR name «متر طول» (every record using it - intended).
  items 7, 8, 12 + decisions, on SI-26/2546 only: incoterm EXW; Persian line descriptions without the brand; section
           «متعلقات»; note «شامل: متعلقات استاندارد سیستم»; the "Excluded: ..." note removed; Project Site «طالقان»
           (a delivery address of the customer company); payment term 70/30; delivery time 45 working days; the
           stored "Delivery Date" (commitment_date 1405/08/13, typed on this order only - nothing defaults it) cleared;
           quotation date = run date, validity = run date + 8 days.

Run (odoo shell):
  docker exec -i [-e SIPANEL_TERMS_COMMIT=1] odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d sipanel --no-http < this
Without SIPANEL_TERMS_COMMIT=1 everything is rolled back (dry run). With it, the transaction is committed only when
EVERY check passes; otherwise it is rolled back and nothing changes. Idempotent: a second run on the same day changes
nothing. Every record is found by a business key and must be in the expected "before" or "after" state; anything
else is refused (fail closed). Prices, quantities, taxes and the fiscal position of SI-26/2546 must not move.
"""
import datetime
import json
import os

import pytz

from odoo import fields

R = {'db': env.cr.dbname, 'checks': {}, 'changed': []}
env = env(su=True)
TZ = pytz.timezone('Asia/Tehran')
VALIDITY_DAYS = 8                                                     # owner decision 2026-10-09
DELIVERY_DAYS = 45                                                    # owner decision 2026-10-09
PAYMENT_TERM_EN = '70% in advance, 30% before delivery.'              # owner decision 2026-10-09 (id 11 today)
OLD_PLACEHOLDERS = ('ساندویچ پانل تولید شرکت', 'شماره حساب جهت واریز پیش پرداخت')
TERMS_LINES = ('اعتبار این پیش‌فاکتور تا تاریخ درج‌شده در بالای آن است.',
               'قیمت‌ها بدون احتساب هزینه حمل، داربست، جرثقیل، اسکان و خوراک پرسنل نصب می‌باشد.',
               'مقادیر نهایی بر اساس متره اجرایی و صورت‌وضعیت محاسبه می‌شود.')
TERMS_HTML = '<div data-oe-version="2.0">' + '</div><div>'.join(TERMS_LINES) + '</div>'
TAGLINE_OLD = 'طراحی.تامین ونصب انواع سامانه های پوشش سالنهای صنعتی'
TAGLINE_NEW = 'طراحی، تأمین و نصب انواع سامانه‌های پوشش سالن‌های صنعتی'
VAT_FA_OLD, VAT_FA_NEW = 'مالیات برارزش افزوده', 'مالیات بر ارزش افزوده'
METER_FA = 'متر طول'
CONTACT_OLD, CONTACT_NEW = 'جناب اقای ', 'جناب آقای '
SITE_NAME = 'طالقان'
LINE_NAMES = {'SIP-000074': 'سیستم پوشش سقف استندینگ سیم (فقط تأمین)',
              'SIP-000076': 'فلاشینگ و فیلر بلوک هم‌جنس ورق رویه (فقط تأمین)',
              'SIP-000077': 'آبرو ورق گالوانیزه ۱.۵ میلیمتر (فقط تأمین)'}
SECTION_OLD, SECTION_NEW = 'Accessories', 'متعلقات'
NOTE_OLD, NOTE_NEW = 'Included: Standard system components', 'شامل: متعلقات استاندارد سیستم'
NOTE_REMOVED = 'Excluded:'


def check(name, ok, detail=None):
    R['checks'][name] = {'ok': bool(ok), 'detail': detail}


def changed(what):
    R['changed'].append(what)


def stored(record, field):
    """Raw jsonb of a translated field (no language fallback)."""
    env.cr.execute(f'SELECT "{field}" FROM "{record._table}" WHERE id = %s', (record.id,))
    return env.cr.fetchone()[0] or {}


def set_terms(record, field, terms):
    """All current languages are passed (Odoo 19: a lone fa_IR key would overwrite the en_US source)."""
    record.update_field_translations(field, dict(stored(record, field), **terms))


def squash(html):
    return ' '.join((html or '').replace('&nbsp;', ' ').split())


def fiscal_state(order):
    return {'fiscal_position': order.fiscal_position_id.id,
            'lines': [(l.id, l.product_id.default_code, l.product_uom_qty, l.price_unit, l.discount,
                       tuple(sorted(l.tax_ids.ids)), l.price_subtotal) for l in order.order_line.sorted('id')
                      if not l.display_type],
            'untaxed': order.amount_untaxed, 'tax': order.amount_tax, 'total': order.amount_total}


ref = env['sale.order'].search([('name', '=', 'SI-26/2546')])
company = ref.company_id
assert len(ref) == 1 and ref.state == 'draft', (len(ref), ref.state)
assert 'sipanel_delivery_days' in ref._fields, 'sipanel_quotation_lines (with the commercial terms) is not installed'
before = fiscal_state(ref)
R['before'] = {'totals': [before['untaxed'], before['tax'], before['total']], 'date_order': str(ref.date_order),
               'validity_date': str(ref.validity_date), 'commitment_date': str(ref.commitment_date),
               'incoterm': ref.incoterm.code, 'payment_term': ref.payment_term_id.name,
               'shipping': ref.partner_shipping_id.display_name, 'problems': ref._sipanel_customer_document_problems()}

# ---- item 11: ru_RU archived
ru = env['res.lang'].with_context(active_test=False).search([('code', '=', 'ru_RU')])
users_ru = env['res.partner'].with_context(active_test=False).search_count([('lang', '=', 'ru_RU')])
on_website = 'website' in env and bool(env['website'].search([('language_ids', 'in', ru.ids)])) if ru else False
check('ru_RU_unused', len(ru) == 1 and users_ru == 0 and not on_website, [len(ru), users_ru, on_website])
if len(ru) == 1 and ru.active and users_ru == 0 and not on_website:
    ru.active = False
    changed('res.lang ru_RU archived')
check('ru_RU_archived', len(ru) == 1 and not ru.active)

# ---- item 6: company default terms + the note of SI-26/2546
terms = stored(company, 'invoice_terms')
src = terms.get('en_US') or ''
check('company_terms_expected_before', squash(src) == squash(TERMS_HTML) or all(p in src for p in OLD_PLACEHOLDERS),
      squash(src)[:300])
if squash(src) != squash(TERMS_HTML) and all(p in src for p in OLD_PLACEHOLDERS):
    company.with_context(lang='en_US').invoice_terms = TERMS_HTML
    changed('res.company invoice_terms (en_US source; no other language stored)')
check('company_terms_new', squash(stored(company, 'invoice_terms').get('en_US')) == squash(TERMS_HTML)
      and set(stored(company, 'invoice_terms')) == set(terms))
note = str(ref.note or '')
check('si26_note_expected_before', squash(note) == squash(TERMS_HTML) or all(p in note for p in OLD_PLACEHOLDERS),
      squash(note)[:300])
if squash(note) != squash(TERMS_HTML) and all(p in note for p in OLD_PLACEHOLDERS):
    ref.note = TERMS_HTML
    changed('SI-26/2546 note')
R['other_orders_with_placeholder_note'] = env['sale.order'].search(
    [('id', '!=', ref.id), ('note', 'ilike', OLD_PLACEHOLDERS[0])]).mapped(lambda o: (o.name, o.state))

# ---- item 10: header tagline (fa_IR), VAT tax group (fa_IR), contact name
header = stored(company, 'report_header')
fa = header.get('fa_IR') or ''
check('tagline_expected_before', (TAGLINE_OLD in fa) != (TAGLINE_NEW in fa), fa)
if TAGLINE_OLD in fa:
    set_terms(company, 'report_header', {'fa_IR': fa.replace(TAGLINE_OLD, TAGLINE_NEW)})
    changed('res.company report_header fa_IR tagline')
after_header = stored(company, 'report_header')
check('tagline_new', TAGLINE_NEW in after_header.get('fa_IR', '') and after_header.get('en_US') == header.get('en_US'))
groups = env['account.tax.group'].with_context(active_test=False).search([])
vat = groups.filtered(lambda g: stored(g, 'name').get('fa_IR') in (VAT_FA_OLD, VAT_FA_NEW))
check('vat_group_found', len(vat) == 1 and stored(vat, 'name').get('en_US') == 'VAT', [(g.id, stored(g, 'name')) for g in vat])
if len(vat) == 1 and stored(vat, 'name').get('fa_IR') == VAT_FA_OLD:
    set_terms(vat, 'name', {'fa_IR': VAT_FA_NEW})
    changed(f'account.tax.group {vat.id} fa_IR name')
check('vat_group_fa', len(vat) == 1 and stored(vat, 'name').get('fa_IR') == VAT_FA_NEW
      and stored(vat, 'name').get('en_US') == 'VAT')
contact = ref.partner_id
check('contact_expected_before', contact.name.startswith((CONTACT_OLD, CONTACT_NEW)), contact.name)
if contact.name.startswith(CONTACT_OLD):
    contact.name = CONTACT_NEW + contact.name[len(CONTACT_OLD):]
    changed(f'res.partner {contact.id} name')
check('contact_new', contact.name.startswith(CONTACT_NEW), contact.name)

# ---- item 9: meter fa_IR
meter = env.ref('uom.product_uom_meter')
mterms = stored(meter, 'name')
check('meter_is_m', mterms.get('en_US') == 'm', mterms)
if mterms.get('en_US') == 'm' and mterms.get('fa_IR') != METER_FA:
    set_terms(meter, 'name', {'fa_IR': METER_FA})
    changed('uom meter fa_IR name')
check('meter_fa', stored(meter, 'name') == dict(mterms, fa_IR=METER_FA), stored(meter, 'name'))

# ---- SI-26/2546: items 7, 8, 12 + decisions
exw = env.ref('account.incoterm_EXW')
if ref.incoterm != exw:
    ref.incoterm = exw
    changed('SI-26/2546 incoterm EXW')
check('incoterm_exw', ref.incoterm == exw, ref.incoterm.code)
lines = ref.order_line
for code, name in LINE_NAMES.items():
    line = lines.filtered(lambda l: l.product_id.default_code == code and not l.sipanel_is_installation_line)
    check(f'line_{code}_found', len(line) == 1, len(line))
    if len(line) == 1 and line.name != name:
        line.name = name
        changed(f'SI-26/2546 line {code} description')
    check(f'line_{code}_name', len(line) == 1 and line.name == name, line.mapped('name'))
section = lines.filtered(lambda l: l.display_type == 'line_section' and l.name in (SECTION_OLD, SECTION_NEW))
check('section_found', len(section) == 1, section.mapped('name'))
if len(section) == 1 and section.name != SECTION_NEW:
    section.name = SECTION_NEW
    changed('SI-26/2546 section Accessories')
included = lines.filtered(lambda l: l.display_type == 'line_note' and l.name in (NOTE_OLD, NOTE_NEW))
check('included_note_found', len(included) == 1, included.mapped('name'))
if len(included) == 1 and included.name != NOTE_NEW:
    included.name = NOTE_NEW
    changed('SI-26/2546 note Included')
excluded = lines.filtered(lambda l: l.display_type == 'line_note' and (l.name or '').startswith(NOTE_REMOVED))
check('excluded_note_at_most_one', len(excluded) <= 1, excluded.mapped('name'))
if len(excluded) == 1:
    R['removed_note'] = excluded.name
    excluded.unlink()
    changed('SI-26/2546 note Excluded removed')
ref.invalidate_recordset()
check('no_english_section_or_note_left', not ref.order_line.filtered(
    lambda l: l.display_type in ('line_section', 'line_note') and (l.name or '') in (SECTION_OLD, NOTE_OLD)
    or (l.name or '').startswith(NOTE_REMOVED)))
# Project Site: a delivery address of the customer company (sipanel_quotation_project_info prints it on page 1)
commercial = ref.partner_id.commercial_partner_id
Partner = env['res.partner'].with_context(active_test=False)
site = Partner.search([('parent_id', '=', commercial.id), ('type', '=', 'delivery'), ('name', '=', SITE_NAME)])
check('site_at_most_one', len(site) <= 1, site.ids)
if not site:
    site = Partner.create({'parent_id': commercial.id, 'type': 'delivery', 'name': SITE_NAME, 'lang': 'fa_IR'})
    changed(f'res.partner {site.id} delivery address «{SITE_NAME}» under {commercial.name}')
if len(site) == 1 and ref.partner_shipping_id != site:
    ref.partner_shipping_id = site           # refused by sipanel_quotation_project_info if it moved the taxes
    changed('SI-26/2546 project site')
check('project_site', ref._sipanel_page1_project_site() == site and site.name == SITE_NAME, ref.partner_shipping_id.display_name)
# commercial terms
term = env['account.payment.term'].with_context(lang='en_US').search([('name', '=', PAYMENT_TERM_EN)])
check('payment_term_found', len(term) == 1, term.ids)
if len(term) == 1 and ref.payment_term_id != term:
    ref.payment_term_id = term
    changed('SI-26/2546 payment term')
if ref.sipanel_delivery_days != DELIVERY_DAYS:
    ref.sipanel_delivery_days = DELIVERY_DAYS
    changed('SI-26/2546 delivery time')
check('bank_line_off', not ref.sipanel_show_bank_account)
if ref.commitment_date:
    ref.commitment_date = False
    changed('SI-26/2546 commitment_date cleared')
today = datetime.datetime.now(TZ).date()
if ref.date_order.replace(tzinfo=pytz.utc).astimezone(TZ).date() != today:
    ref.date_order = fields.Datetime.now()
    changed('SI-26/2546 date_order = run date')
if ref.validity_date != today + datetime.timedelta(days=VALIDITY_DAYS):
    ref.validity_date = today + datetime.timedelta(days=VALIDITY_DAYS)
    changed('SI-26/2546 validity_date = run date + 8 days')
check('dates', ref.date_order.replace(tzinfo=pytz.utc).astimezone(TZ).date() == today
      and ref.validity_date == today + datetime.timedelta(days=VALIDITY_DAYS), [str(ref.date_order), str(ref.validity_date)])
ref.invalidate_recordset()
after = fiscal_state(ref)
check('si26_prices_taxes_fiscal_unchanged', after == before, {'before': before, 'after': after})
check('si26_printable', ref._sipanel_customer_document_problems() == [], ref._sipanel_customer_document_problems())
R['after'] = {'date_order': str(ref.date_order), 'validity_date': str(ref.validity_date),
              'validity_shamsi': ref.validity_date_shamsi, 'date_order_shamsi': ref.date_order_shamsi,
              'incoterm': ref.incoterm.code, 'payment_term': ref.payment_term_id.with_context(lang='fa_IR').name,
              'delivery_days': ref.sipanel_delivery_days, 'shipping': ref.partner_shipping_id.display_name,
              'contact': ref.partner_id.name,
              'lines': [(l.sequence, l.display_type or l.product_id.default_code, l.name) for l in
                        ref.order_line.sorted(lambda l: (l.sequence, l.id))]}

R['all_ok'] = all(c['ok'] for c in R['checks'].values())
print('SIPANEL_TERMS ' + json.dumps(R, ensure_ascii=False, default=str))
if os.environ.get('SIPANEL_TERMS_COMMIT') == '1' and R['all_ok']:
    env.cr.commit()
    print('SIPANEL_TERMS COMMITTED')
else:
    env.cr.rollback()
    print('SIPANEL_TERMS ROLLED_BACK' + ('' if R['all_ok'] else ' (checks failed: '
          + ', '.join(k for k, c in R['checks'].items() if not c['ok']) + ')'))
