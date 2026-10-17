# -*- coding: utf-8 -*-
"""Production step P6b of the quotation-lines deployment: commercial data (owner requirements 2026-10-08, items 6-12;
decisions 2026-10-09; owner decisions 2026-10-11 and owner review 2026-10-12: payment term «۷۰٪ پیش‌پرداخت، ۳۰٪
باقیمانده قبل از بارگیری», 45 working days and validity run date + 8 days confirmed, no bank line, quotation date =
run date).

Runs after the install (P6: it needs the new delivery-time field) and BEFORE Standing Seam v3 (P7): with ru_RU
archived first, v3 is released without the R2 "no ru_RU translation" warning.

  item 11  language ru_RU archived (0 partners / users use it; not on the website). Reversible: active = True.
  item 6   company Default Terms & Conditions (res.company.invoice_terms, the source of every new quotation's note):
           the placeholder lines are replaced by the three approved lines. SI-26/2546's own note (a copy made when
           it was created) gets the same text. The quotation template "Standing Seam Roof System" has no note.
  item 10  company report header tagline (res.company.report_header, fa_IR); tax group "VAT" fa_IR name
           «مالیات بر ارزش افزوده»; contact of SI-26/2546 «جناب اقای ...» -> «جناب آقای ...».
  2026-10-12 payment term (id 11 in Production, created there on 2026-03-03 by the salesperson user, not by a
           SIPANEL script): fa_IR name exactly «۷۰٪ پیش‌پرداخت، ۳۰٪ باقیمانده قبل از بارگیری» (the report prints the
           name only, not its note); company report footer website www.sipanelco.com (en_US and fa_IR); Persian
           quotation name «طالقانی» of the salesperson user "Taleghani" (res.users.name unchanged).
  item 9   unit of measure meter (uom.product_uom_meter) fa_IR name «متر طول» (every record using it - intended).
  items 7, 8, 12 + decisions, on SI-26/2546 only: incoterm EXW; Persian line descriptions without the brand; section
           «متعلقات»; note «شامل: متعلقات استاندارد سیستم»; the "Excluded: ..." note removed; Project Site «طالقان»
           (a delivery address of the customer company, city «شهرستان طالقان», Iran: printed «شهرستان طالقان - ایران»);
           payment term 70/30; delivery time 45 working days; the
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
VALIDITY_DAYS = 8                                                     # owner, confirmed 2026-10-12
DELIVERY_DAYS = 45                                                    # owner, confirmed 2026-10-12
PAYMENT_TERM_EN = '70% in advance, 30% before delivery.'              # id 11 in Production (en_US name unchanged)
# P10 (owner 2026-10-17, after deployment) gives term 11 an English name and the company terms an English source with
# the Persian lines as the fa_IR translation: both states are accepted (the step stays re-runnable on Production)
PAYMENT_TERM_EN_P10 = '70% advance payment, 30% balance before loading'
TERMS_EN_P10 = ('This quotation is valid until the date stated above.',
                'Prices exclude transport, scaffolding, crane, and accommodation and meals for the installation crew.',
                'Quantities in this quotation are approximate. Exact quantities will be taken from the shop drawings and '
                'will be the basis of the final calculation.')
PAYMENT_TERM_FA_OLD = 'پیش پرداخت ۷۰٪ و قبل از بارگیری ۳۰٪باقیمانده'
PAYMENT_TERM_FA = '۷۰٪ پیش‌پرداخت، ۳۰٪ باقیمانده قبل از بارگیری'      # owner review 2026-10-12, exactly
WEBSITE_OLD = ('href="https://sipanelco.ir">www.sipanelco.ir<', )
WEBSITE_NEW = 'href="https://www.sipanelco.com">www.sipanelco.com<'  # owner review 2026-10-12 (footer, fa + en)
SALESPERSON_EN, SALESPERSON_FA = 'Taleghani', 'طالقانی'              # owner review 2026-10-12 (fa quotations)
OLD_PLACEHOLDERS = ('ساندویچ پانل تولید شرکت', 'شماره حساب جهت واریز پیش پرداخت')
# line 3: owner requirements 2026-10-14, item 6 (replaces «مقادیر نهایی بر اساس متره اجرایی و صورت‌وضعیت محاسبه می‌شود.»)
TERMS_LINES = ('اعتبار این پیش‌فاکتور تا تاریخ درج‌شده در بالای آن است.',
               'قیمت‌ها بدون احتساب هزینه حمل، داربست، جرثقیل، اسکان و خوراک پرسنل نصب می‌باشد.',
               'مقادیر این پیش‌فاکتور تقریبی است. مقادیر دقیق پس از تهیه‌ی نقشه‌های اجرایی (شاپ) استخراج می‌شود و ملاک محاسبه خواهد بود.')
TERMS_HTML = '<div data-oe-version="2.0">' + '</div><div>'.join(TERMS_LINES) + '</div>'
TAGLINE_OLD = 'طراحی.تامین ونصب انواع سامانه های پوشش سالنهای صنعتی'
TAGLINE_NEW = 'طراحی، تأمین و نصب انواع سامانه‌های پوشش سالن‌های صنعتی'
VAT_FA_OLD, VAT_FA_NEW = 'مالیات برارزش افزوده', 'مالیات بر ارزش افزوده'
METER_FA = 'متر طول'
CONTACT_OLD, CONTACT_NEW = 'جناب اقای ', 'جناب آقای '
SITE_NAME = 'طالقان'
SITE_CITY = 'شهرستان طالقان'                                           # owner review 2026-10-12, country Iran
LINE_NAMES = {'SIP-000074': 'سیستم پوشش سقف استندینگ سیم (فقط تأمین)',
              'SIP-000076': 'فلاشینگ و فیلر بلوک هم‌جنس ورق رویه (فقط تأمین)',
              'SIP-000077': 'آبرو ورق گالوانیزه ۱.۵ میلیمتر (فقط تأمین)'}
SECTION_OLD, SECTION_NEW = 'Accessories', 'متعلقات'
FIRST_SECTION_OLD, FIRST_SECTION_NEW = 'Standing Seam Roof System', 'سیستم پوشش سقف استندینگ سیم'   # owner 2026-10-11
SYSTEM_EN, SYSTEM_FA = 'Standing Seam', 'استندینگ سیم'          # account 2316, owner 2026-10-11
NOTE_OLD, NOTE_NEW = 'Included: Standard system components', 'شامل: متعلقات استاندارد سیستم'
NOTE_REMOVED = 'Excluded:'


def check(name, ok, detail=None):
    R['checks'][name] = {'ok': bool(ok), 'detail': detail}


def changed(what):
    R['changed'].append(what)


def stored(record, field):
    """Raw jsonb of a translated field (no language fallback); pending ORM writes are flushed first."""
    record.flush_recordset([field])
    env.cr.execute(f'SELECT "{field}" FROM "{record._table}" WHERE id = %s', (record.id,))
    return env.cr.fetchone()[0] or {}


def set_terms(record, field, terms):
    """en_US is passed with the new terms (Odoo 19: a lone fa_IR key would overwrite the en_US source). Other stored
    languages are not passed: Odoo merges them in unchanged, and refuses inactive ones (ru_RU, archived above)."""
    record.update_field_translations(field, dict({'en_US': stored(record, field)['en_US']}, **terms))


def set_raw_lang_value(record, field, lang, value):
    """Replace one language's stored value of a term-translated Html field as is. report_header is
    Html(translate=True) = term translation in Odoo 19, and its fa_IR value is a separate HTML (not a term-by-term
    translation of en_US), so update_field_translations would rebuild it from the en_US structure; this only swaps
    the text inside the fa_IR value (P1 run 20261011T154052Z)."""
    env.cr.execute(f'UPDATE "{record._table}" SET "{field}" = jsonb_set("{field}", %s, to_jsonb(%s::text)) WHERE id = %s',
                   ('{%s}' % lang, value, record.id))
    record.invalidate_recordset([field])
    record.modified([field])


def terms_done(html):
    """The approved terms text is in place: every line present, no placeholder left. Text based - Odoo sanitizes the
    HTML on write, so the stored markup never equals TERMS_HTML byte for byte (P1 run 20261011T154052Z)."""
    text = squash(html)
    return all(line in text for line in TERMS_LINES) and not any(p in text for p in OLD_PLACEHOLDERS)


def company_terms_ok(terms):
    """Approved terms in place: Persian en_US source (P6b), or English en_US source + Persian fa_IR (after P10)."""
    en = terms.get('en_US') or ''
    return terms_done(en) or (all(l in squash(en) for l in TERMS_EN_P10) and terms_done(terms.get('fa_IR')))


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
check('company_terms_expected_before', company_terms_ok(terms) or all(p in src for p in OLD_PLACEHOLDERS),
      squash(src)[:300])
if not company_terms_ok(terms) and all(p in src for p in OLD_PLACEHOLDERS):
    company.with_context(lang='en_US').invoice_terms = TERMS_HTML
    changed('res.company invoice_terms (en_US source; no other language stored)')
check('company_terms_new', company_terms_ok(stored(company, 'invoice_terms'))
      and set(stored(company, 'invoice_terms')) == set(terms), stored(company, 'invoice_terms'))
note = str(ref.note or '')
check('si26_note_expected_before', terms_done(note) or all(p in note for p in OLD_PLACEHOLDERS),
      squash(note)[:300])
if not terms_done(note) and all(p in note for p in OLD_PLACEHOLDERS):
    ref.note = TERMS_HTML
    changed('SI-26/2546 note')


def never_sent(order):
    """No e-mail, no message to a partner, no portal signature, still a draft (same rule as the rehearsal)."""
    msgs = env['mail.message'].search([('model', '=', 'sale.order'), ('res_id', '=', order.id)])
    comment = env.ref('mail.mt_comment')
    return order.state == 'draft' and not order.signed_by and not msgs.filtered(
        lambda m: m.message_type == 'email' or (m.subtype_id == comment and m.partner_ids))


# owner decision 2026-10-11: other quotations with the placeholder copy - only drafts never sent get the new text;
# sent / confirmed / cancelled ones stay as historical records
others = env['sale.order'].search([('id', '!=', ref.id), ('note', 'ilike', OLD_PLACEHOLDERS[0])])
R['other_orders_with_placeholder_note'] = sorted((o.name, o.state, never_sent(o)) for o in others)
for order in others.filtered(never_sent):
    if not terms_done(order.note) and all(p in str(order.note or '') for p in OLD_PLACEHOLDERS):
        order.note = TERMS_HTML
        changed(f'{order.name} note (draft, never sent)')
check('other_drafts_terms', all(terms_done(o.note) for o in others.filtered(never_sent)),
      [o.name for o in others.filtered(never_sent)])
check('historical_orders_untouched', all(not terms_done(o.note) for o in others - others.filtered(never_sent)),
      [(o.name, o.state) for o in others - others.filtered(never_sent)])

# ---- item 10: header tagline (fa_IR), VAT tax group (fa_IR), contact name
header = stored(company, 'report_header')
fa = header.get('fa_IR') or ''
check('tagline_expected_before', (TAGLINE_OLD in fa) != (TAGLINE_NEW in fa), fa)
if TAGLINE_OLD in fa:
    set_raw_lang_value(company, 'report_header', 'fa_IR', fa.replace(TAGLINE_OLD, TAGLINE_NEW))
    changed('res.company report_header fa_IR tagline')
after_header = stored(company, 'report_header')
check('tagline_new', after_header.get('fa_IR') == fa.replace(TAGLINE_OLD, TAGLINE_NEW)
      and after_header.get('en_US') == header.get('en_US') and set(after_header) == set(header), after_header)
# ---- owner review 2026-10-12: footer website (report_footer is term-translated Html with a separate fa_IR value)
footer = stored(company, 'report_footer')
check('footer_website_expected_before', set(footer) == {'en_US', 'fa_IR'} and all(
      (WEBSITE_OLD[0] in v) != (WEBSITE_NEW in v) for v in footer.values()), footer)
for lang, value in footer.items():
    if WEBSITE_OLD[0] in value:
        set_raw_lang_value(company, 'report_footer', lang, value.replace(WEBSITE_OLD[0], WEBSITE_NEW))
        changed(f'res.company report_footer {lang} website')
after_footer = stored(company, 'report_footer')
check('footer_website_new', set(after_footer) == set(footer) and all(
      after_footer[k] == v.replace(WEBSITE_OLD[0], WEBSITE_NEW) for k, v in footer.items())
      and all('sipanelco.ir' not in v for v in after_footer.values()), after_footer)
# ---- owner review 2026-10-12: salesperson Persian name on fa_IR quotations (report only)
seller = ref.user_id
check('salesperson_expected', seller.name == SALESPERSON_EN
      and seller.sipanel_quotation_name_fa in (False, SALESPERSON_FA), [seller.id, seller.name])
if seller.name == SALESPERSON_EN and not seller.sipanel_quotation_name_fa:
    seller.sipanel_quotation_name_fa = SALESPERSON_FA
    changed(f'res.users {seller.id} Persian quotation name')
check('salesperson_fa', seller.sipanel_quotation_name_fa == SALESPERSON_FA and seller.name == SALESPERSON_EN
      and seller.partner_id.name == SALESPERSON_EN, [seller.name, seller.sipanel_quotation_name_fa])
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

# ---- owner 2026-10-11: System account 2316 fa_IR name; SI-26/2546 prints its Requested System from a snapshot
# taken in the quotation language when the System was set, so the snapshot is refreshed below
system = env['account.analytic.account'].with_context(lang='en_US').search(
    [('name', '=', SYSTEM_EN), ('plan_id', '=', env['sipanel.config'].resolve_system_plan().id)])
sterms = stored(system, 'name') if len(system) == 1 else {}
check('system_account_found', len(system) == 1 and sterms.get('en_US') == SYSTEM_EN
      and sterms.get('fa_IR') in (None, SYSTEM_FA), [system.ids, sterms])
if len(system) == 1 and sterms.get('fa_IR') is None:
    set_terms(system, 'name', {'fa_IR': SYSTEM_FA})
    changed(f'account.analytic.account {system.id} fa_IR name')
check('system_account_fa', len(system) == 1 and stored(system, 'name').get('fa_IR') == SYSTEM_FA
      and stored(system, 'name').get('en_US') == SYSTEM_EN, stored(system, 'name') if len(system) == 1 else None)

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
first = lines.filtered(lambda l: l.display_type == 'line_section' and l.name in (FIRST_SECTION_OLD, FIRST_SECTION_NEW))
check('first_section_found', len(first) == 1, first.mapped('name'))
if len(first) == 1 and first.name != FIRST_SECTION_NEW:
    first.name = FIRST_SECTION_NEW
    changed('SI-26/2546 section Standing Seam Roof System')
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
    lambda l: l.display_type in ('line_section', 'line_note') and (l.name or '') in (SECTION_OLD, NOTE_OLD, FIRST_SECTION_OLD)
    or (l.name or '').startswith(NOTE_REMOVED)))
# Project Site: a delivery address of the customer company (sipanel_quotation_project_info prints it on page 1)
commercial = ref.partner_id.commercial_partner_id
Partner = env['res.partner'].with_context(active_test=False)
site = Partner.search([('parent_id', '=', commercial.id), ('type', '=', 'delivery'), ('name', '=', SITE_NAME)])
check('site_at_most_one', len(site) <= 1, site.ids)
if not site:
    # the customer company's country (and state): the Domestic fiscal position auto-applies by country, an address
    # without one matched "Foreign Trade" and the Page 1 guard refused the change (P1 run 20261011T154052Z)
    site = Partner.create({'parent_id': commercial.id, 'type': 'delivery', 'name': SITE_NAME, 'lang': 'fa_IR',
                           'city': SITE_CITY, 'country_id': commercial.country_id.id,
                           'state_id': commercial.state_id.id})
    changed(f'res.partner {site.id} delivery address «{SITE_NAME}» under {commercial.name}')
check('site_country_iran', commercial.country_id == env.ref('base.ir') and site.country_id == env.ref('base.ir'),
      [commercial.country_id.code, site.country_id.code])
if len(site) == 1 and site.city != SITE_CITY:
    site.city = SITE_CITY                     # the address of a P1 clone created before 2026-10-12 had city «طالقان»
    changed(f'res.partner {site.id} city «{SITE_CITY}»')
if len(site) == 1 and ref.partner_shipping_id != site:
    ref.partner_shipping_id = site           # refused by sipanel_quotation_project_info if it moved the taxes
    changed('SI-26/2546 project site')
check('project_site', ref._sipanel_page1_project_site() == site and site.name == SITE_NAME, ref.partner_shipping_id.display_name)
check('project_site_line', ref.with_context(lang='fa_IR')._sipanel_project_site_line() == 'شهرستان طالقان - ایران',
      ref.with_context(lang='fa_IR')._sipanel_project_site_line())
if ref.sipanel_requested_system_id == system and ref.sipanel_requested_system_name_snapshot != ref._sipanel_system_print_name():
    R['system_snapshot_before'] = ref.sipanel_requested_system_name_snapshot
    ref._sipanel_refresh_system_snapshot()
    changed('SI-26/2546 Requested System snapshot (quotation language)')
check('requested_system_snapshot', ref.sipanel_requested_system_id == system and (
      ref.sipanel_requested_system_name_snapshot == (SYSTEM_FA if ref.partner_id.lang == 'fa_IR' else SYSTEM_EN)),
      [ref.partner_id.lang, ref.sipanel_requested_system_name_snapshot])
# commercial terms
term = env['account.payment.term'].with_context(lang='en_US').search([('name', 'in', (PAYMENT_TERM_EN, PAYMENT_TERM_EN_P10))])
check('payment_term_found', len(term) == 1, term.ids)
pterms = stored(term, 'name') if len(term) == 1 else {}
R['payment_term_record'] = {'id': term.id, 'create_date': str(term.create_date), 'create_uid': term.create_uid.id,
                            'name': pterms, 'orders': sorted(env['sale.order'].search(
                                [('payment_term_id', '=', term.id)]).mapped(lambda o: (o.name, o.state)))}
check('payment_term_expected_before', pterms.get('fa_IR') in (PAYMENT_TERM_FA_OLD, PAYMENT_TERM_FA), pterms)
if pterms.get('fa_IR') == PAYMENT_TERM_FA_OLD:
    set_terms(term, 'name', {'fa_IR': PAYMENT_TERM_FA})
    changed(f'account.payment.term {term.id} fa_IR name')
check('payment_term_fa', len(term) == 1 and stored(term, 'name') == dict(pterms, fa_IR=PAYMENT_TERM_FA),
      stored(term, 'name') if len(term) == 1 else None)
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
