# -*- coding: utf-8 -*-
"""Production step P8c of the quotation-lines deployment: quotation products and defaults (owner decisions of
2026-10-17 after the UI acceptance test). Runs after P8b.

  item 1   every Standing Seam quotation product prints its own name as the line title, so the products carry the
           approved titles (fa_IR as given by the owner; en_US = English translation, for owner review):
             SIP-000074 roof          «سیستم پوشش سقف و دیوار استندینگ سیم (فقط تأمین)»
             SIP-000076 flashing      becomes the 58 cm flashing «فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۵۸ سانتی‌متر
                                      (فقط تأمین)», list price 43,800,000 / m
             new product              the 20 cm flashing «… عرض گسترده تا ۲۰ سانتی‌متر (فقط تأمین)», list price
                                      14,600,000 / m: same type, unit, category, taxes, installation base flag and
                                      top-sheet material attribute as SIP-000076; next SIP- code
             SIP-000077 gutter        «آبرو ورق گالوانیزه ۱.۵ میلیمتر (فقط تأمین)»
           The installation product SIP-000075 and the Shop Drawings product must already have a fa_IR name (checked,
           not changed): their quotation lines print the engine labels «نصب و اجرا (…)» / «تهیه‌ی نقشه‌های اجرایی
           (شاپ)», not the product name.
           SI-26/2546 uses the same products: the 20 cm flashing line moves to the new product (same quantity, price,
           taxes, material «گالوانیزه»), and the four supply lines get exactly the description Odoo gives a
           salesperson who adds the product in the quotation (product name in the customer's language + the
           material option line) - nothing typed. Totals unchanged.
  item 3   default contact language (ir.default res.partner.lang, global) en_US -> fa_IR. Existing contacts are not
           changed: the en_US customers are LISTED for the owner (R['en_us_customers']).
  item 5   default quotation validity (res.company.quotation_validity_days, native setting) 30 -> 8 days.

Run (odoo shell):
  docker exec -i [-e SIPANEL_PRODUCTS_COMMIT=1] odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d sipanel --no-http < this
Without SIPANEL_PRODUCTS_COMMIT=1 everything is rolled back (dry run). With it, the transaction is committed only when
EVERY check passes; otherwise it is rolled back and nothing changes. Idempotent: a second run finds everything in the
"after" state and changes nothing. Every record is found by a business key and must be in the expected "before" or
"after" state; anything else is refused (fail closed).
"""
import json
import os
import re

from odoo.exceptions import UserError

R = {'db': env.cr.dbname, 'checks': {}, 'changed': []}
env = env(su=True)
UNTAXED, TAX, TOTAL = 27_364_418_400, 2_736_441_840, 30_100_860_240      # SI-26/2546 after P8b, unchanged here
ROOF_CODE, FLASH_CODE, GUTTER_CODE, INSTALL_CODE = 'SIP-000074', 'SIP-000076', 'SIP-000077', 'SIP-000075'
NAMES = {   # owner 2026-10-17 (fa_IR, exact); en_US = translation for owner review
    ROOF_CODE: {'fa_IR': 'سیستم پوشش سقف و دیوار استندینگ سیم (فقط تأمین)',
                'en_US': 'Standing Seam roof and wall cladding system (supply only)'},
    FLASH_CODE: {'fa_IR': 'فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۵۸ سانتی‌متر (فقط تأمین)',
                 'en_US': 'Flashing in the top-sheet material, developed width up to 58 cm (supply only)'},
    'flash20': {'fa_IR': 'فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۲۰ سانتی‌متر (فقط تأمین)',
                'en_US': 'Flashing in the top-sheet material, developed width up to 20 cm (supply only)'},
    GUTTER_CODE: {'fa_IR': 'آبرو ورق گالوانیزه ۱.۵ میلیمتر (فقط تأمین)',
                  'en_US': 'Galvanized sheet gutter, 1.5 mm (supply only)'},
}
FLASH58_PRICE, FLASH20_PRICE = 43_800_000, 14_600_000
FLASH20_QTY = 54.23
MATERIAL_EN = 'Top sheet material'
PARTNER_LANG_OLD, PARTNER_LANG_NEW = 'en_US', 'fa_IR'
VALIDITY_OLD, VALIDITY_NEW = 30, 8
# fields of the 20 cm flashing copied from SIP-000076 (and compared after)
SAME_AS_FLASH = ('type', 'uom_id', 'categ_id', 'taxes_id', 'supplier_taxes_id', 'sale_ok', 'purchase_ok',
                 'invoice_policy', 'company_id', 'sipanel_installation_base', 'sipanel_installation_work')
OPTIONAL_SAME = ('is_storable', 'service_tracking', 'purchase_method', 'sale_line_warn')
PERSIAN = re.compile('[؀-ۿ]')


def check(name, ok, detail=None):
    R['checks'][name] = {'ok': bool(ok), 'detail': detail}


def changed(what):
    R['changed'].append(what)


def close(a, b):
    return abs((a or 0.0) - b) < 0.5


def stored(record, field):
    record.flush_recordset([field])
    env.cr.execute(f'SELECT "{field}" FROM "{record._table}" WHERE id = %s', (record.id,))
    return env.cr.fetchone()[0] or {}


def set_name(tmpl, terms):
    """en_US written as the source, then both terms (Odoo 19: a lone fa_IR key would overwrite the en_US source).
    Other stored languages are merged in unchanged by update_field_translations."""
    tmpl.with_context(lang='en_US').name = terms['en_US']
    tmpl.update_field_translations('name', dict(terms))


def totals(order):
    return [order.amount_untaxed, order.amount_tax, order.amount_total]


def never_sent(order):
    msgs = env['mail.message'].search([('model', '=', 'sale.order'), ('res_id', '=', order.id)])
    comment = env.ref('mail.mt_comment')
    return order.state == 'draft' and not order.signed_by and not msgs.filtered(
        lambda m: m.message_type == 'email' or (m.subtype_id == comment and m.partner_ids))


def native_name(line):
    """The description Odoo gives the line when a salesperson adds the product (sale.order.line._compute_name):
    product name in the order's language + the no_variant option lines."""
    return line.with_context(lang=line.order_id._get_lang())._get_sale_order_line_multiline_description_sale()


def snapshot(tmpl, fields_):
    out = {}
    for f in fields_:
        if f in tmpl._fields:
            v = tmpl[f]
            out[f] = sorted(v.ids) if hasattr(v, 'ids') else v
    return out


try:
    assert 'sipanel_spec_text' in env['product.attribute.value']._fields, \
        'sipanel_quotation_lines 19.0.1.4.0 is not installed'
    Product = env['product.product'].with_context(active_test=False)
    Tmpl = env['product.template'].with_context(active_test=False, lang='en_US')
    prods = {code: Product.search([('default_code', '=', code)]) for code in (ROOF_CODE, FLASH_CODE, GUTTER_CODE,
                                                                             INSTALL_CODE)}
    check('products_found', all(len(p) == 1 for p in prods.values()), {c: p.ids for c, p in prods.items()})
    roof_p, flash_p, gutter_p, install_p = (prods[c] for c in (ROOF_CODE, FLASH_CODE, GUTTER_CODE, INSTALL_CODE))
    for p in prods.values():
        p.ensure_one()
    R['before'] = {'names': {c: stored(p.product_tmpl_id, 'name') for c, p in prods.items()},
                   'list_prices': {c: p.list_price for c, p in prods.items()}}
    attr = env['product.attribute'].with_context(lang='en_US').search([('name', '=', MATERIAL_EN)])
    check('material_attribute', len(attr) == 1, attr.ids)
    attr.ensure_one()

    # ---- item 1: names (fa_IR exact, en_US translation) and list prices
    for code in (ROOF_CODE, FLASH_CODE, GUTTER_CODE):
        tmpl = prods[code].product_tmpl_id
        names = stored(tmpl, 'name')
        if {k: names.get(k) for k in ('en_US', 'fa_IR')} != NAMES[code]:
            set_name(tmpl, NAMES[code])
            changed(f'{code} name fa_IR / en_US')
    if not close(flash_p.list_price, FLASH58_PRICE):
        flash_p.product_tmpl_id.list_price = FLASH58_PRICE
        changed(f'{FLASH_CODE} list price {FLASH58_PRICE:,}')

    # ---- item 1: the 20 cm flashing, a product of its own
    flash_t = flash_p.product_tmpl_id
    flash20_t = Tmpl.search([('name', '=', NAMES['flash20']['en_US'])])
    check('flash20_at_most_one', len(flash20_t) <= 1, flash20_t.ids)
    if not flash20_t:
        codes = Product.search([('default_code', '=like', 'SIP-%')]).mapped('default_code')
        numbers = [int(c[4:]) for c in codes if re.fullmatch(r'SIP-\d{6}', c)]
        seqs = env['ir.sequence'].search([('prefix', '=', 'SIP-')])
        R['code_source'] = {'sip_codes': len(codes), 'max': max(numbers) if numbers else None,
                            'sequences_with_prefix_SIP': [(s.id, s.code, s.number_next_actual) for s in seqs]}
        # no SIPANEL sequence is known for product codes: next number after the highest SIP-nnnnnn code
        check('no_product_code_sequence', not seqs, R['code_source']['sequences_with_prefix_SIP'])
        new_code = f'SIP-{max(numbers) + 1:06d}'
        check('new_code_free', not Product.search_count([('default_code', '=', new_code)]), new_code)
        vals = {'name': NAMES['flash20']['en_US'], 'default_code': new_code, 'list_price': FLASH20_PRICE,
                'description_sale': False,
                'attribute_line_ids': [(0, 0, {'attribute_id': ptal.attribute_id.id,
                                               'value_ids': [(6, 0, ptal.value_ids.ids)]})
                                       for ptal in flash_t.attribute_line_ids]}
        for f in SAME_AS_FLASH + OPTIONAL_SAME:
            if f in flash_t._fields:
                v = flash_t[f]
                vals[f] = [(6, 0, v.ids)] if getattr(flash_t._fields[f], 'type', '') == 'many2many' else (
                    v.id if hasattr(v, 'id') and hasattr(v, '_name') else v)
        flash20_t = Tmpl.create(vals)
        flash20_t.update_field_translations('name', dict(NAMES['flash20']))
        changed(f'product {new_code} created (20 cm flashing, copy of {FLASH_CODE} settings)')
    flash20_t.ensure_one()
    flash20_p = flash20_t.product_variant_ids
    check('flash20_single_variant', len(flash20_p) == 1, flash20_p.ids)
    flash20_p.ensure_one()
    R['flash20'] = {'id': flash20_p.id, 'code': flash20_p.default_code, 'name': stored(flash20_t, 'name'),
                    'list_price': flash20_t.list_price, 'same_as_flash': snapshot(flash20_t, SAME_AS_FLASH + OPTIONAL_SAME),
                    'flash': snapshot(flash_t, SAME_AS_FLASH + OPTIONAL_SAME)}
    check('flash20_settings_as_flash', R['flash20']['same_as_flash'] == R['flash20']['flash']
          and close(flash20_t.list_price, FLASH20_PRICE) and not flash20_t.description_sale, R['flash20'])
    flash_ptal = flash_t.attribute_line_ids.filtered(lambda l: l.attribute_id == attr)
    f20_ptal = flash20_t.attribute_line_ids.filtered(lambda l: l.attribute_id == attr)
    check('flash20_material_option', len(f20_ptal) == 1 and f20_ptal.value_ids == flash_ptal.value_ids
          and all(p.price_extra == 0.0 for p in f20_ptal.product_template_value_ids)
          and [l.attribute_id for l in flash20_t.attribute_line_ids] == [l.attribute_id for l in flash_t.attribute_line_ids],
          [(p.name, p.price_extra) for p in f20_ptal.product_template_value_ids])

    # ---- every product carries its title (fa_IR + en_US); installation + shop drawings: fa_IR present
    for code, p in ((ROOF_CODE, roof_p), (FLASH_CODE, flash_p), ('flash20', flash20_p), (GUTTER_CODE, gutter_p)):
        names = stored(p.product_tmpl_id, 'name')
        check(f'name_{code}', {k: names.get(k) for k in ('en_US', 'fa_IR')} == NAMES[code], names)
    check('flash58_list_price', close(flash_p.list_price, FLASH58_PRICE), flash_p.list_price)
    plan = env['sipanel.config'].system_plan()
    seam = env['account.analytic.account'].with_context(lang='en_US').search(
        [('plan_id', '=', plan.id), ('name', '=', 'Standing Seam'), ('active', '=', True)])
    check('standing_seam_system', len(seam) == 1 and seam.sipanel_installation_product_id == install_p
          and bool(seam.sipanel_shop_drawing_product_id), seam.ids)
    seam.ensure_one()
    for label, p in (('installation', install_p), ('shop_drawings', seam.sipanel_shop_drawing_product_id)):
        names = stored(p.product_tmpl_id, 'name')
        R.setdefault('service_names', {})[label] = names
        check(f'{label}_product_fa_name', bool(PERSIAN.search(names.get('fa_IR') or '')), names)

    # ---- SI-26/2546: the same products, the native descriptions
    ref = env['sale.order'].search([('name', '=', 'SI-26/2546')])
    check('si26_2546_quotation_not_sent', len(ref) == 1 and never_sent(ref), [len(ref), ref.state])
    ref.ensure_one()
    check('si26_2546_customer_fa', ref._get_lang() == 'fa_IR', ref._get_lang())
    check('si26_2546_totals_before', close(ref.amount_untaxed, UNTAXED) and close(ref.amount_total, TOTAL), totals(ref))
    supply = ref.order_line.filtered(lambda l: not l.display_type and not l.sipanel_is_installation_line)
    R['si26_before'] = [(l.id, l.product_id.default_code, l.name, l.product_uom_qty, l.price_unit, l.tax_ids.ids,
                         l.product_no_variant_attribute_value_ids.mapped('name')) for l in supply.sorted('sequence')]
    flash_lines = supply.filtered(lambda l: l.product_id in flash_p | flash20_p)
    l20 = flash_lines.filtered(lambda l: close(l.price_unit, FLASH20_PRICE) and close(l.product_uom_qty * 100, FLASH20_QTY * 100))
    check('si26_2546_flash20_line', len(flash_lines) == 2 and len(l20) == 1, R['si26_before'])
    l20.ensure_one()
    galv_value = attr.value_ids.sorted(lambda v: (v.sequence, v.id))[:1]
    if l20.product_id != flash20_p:
        taxes, qty, uom = l20.tax_ids, l20.product_uom_qty, l20.product_uom_id
        material = l20.product_no_variant_attribute_value_ids.filtered(lambda p: p.attribute_id == attr)
        check('si26_2546_flash20_galvanized_before', material.product_attribute_value_id == galv_value,
              material.mapped('name'))
        l20.product_id = flash20_p
        l20.write({'product_uom_qty': qty, 'product_uom_id': uom.id, 'tax_ids': [(6, 0, taxes.ids)]})
        l20.price_unit = FLASH20_PRICE     # written last: a manual price (Odoo 19 technical_price_unit)
        changed(f'SI-26/2546 line {l20.id}: 20 cm flashing -> {flash20_p.default_code}')
    for line in supply:
        tmpl_ptavs = line.product_id.product_tmpl_id.attribute_line_ids.filtered(
            lambda l: l.attribute_id == attr).product_template_value_ids
        if tmpl_ptavs:
            want = tmpl_ptavs.filtered(lambda p: p.product_attribute_value_id == galv_value)
            current = line.product_no_variant_attribute_value_ids
            if current != want:
                line.product_no_variant_attribute_value_ids = [(6, 0, want.ids)]
                changed(f'SI-26/2546 line {line.id}: material Galvanized ({line.product_id.default_code})')
    for line in supply.sorted('sequence'):
        name = native_name(line)
        if line.name != name:
            line.name = name
            changed(f'SI-26/2546 line {line.id} ({line.product_id.default_code}): native description')
    ref.invalidate_recordset()
    supply = ref.order_line.filtered(lambda l: not l.display_type and not l.sipanel_is_installation_line)
    R['si26_after'] = [(l.id, l.product_id.default_code, l.name, l.product_uom_qty, l.price_unit, l.tax_ids.ids,
                        l.product_no_variant_attribute_value_ids.mapped('name')) for l in supply.sorted('sequence')]
    check('si26_2546_products', sorted(supply.product_id.mapped('default_code'))
          == sorted([ROOF_CODE, FLASH_CODE, flash20_p.default_code, GUTTER_CODE]) and len(supply) == 4, R['si26_after'])
    check('si26_2546_native_descriptions', all(l.name == native_name(l) for l in supply), R['si26_after'])
    printed = {l.product_id.default_code: l._sipanel_report_name_lines()[0] for l in supply}
    R['printed_titles'] = printed
    check('si26_2546_printed_titles', printed == {ROOF_CODE: NAMES[ROOF_CODE]['fa_IR'], FLASH_CODE: NAMES[FLASH_CODE]['fa_IR'],
                                                 flash20_p.default_code: NAMES['flash20']['fa_IR'],
                                                 GUTTER_CODE: NAMES[GUTTER_CODE]['fa_IR']}, printed)
    check('si26_2546_material_galvanized', all(
        l.product_no_variant_attribute_value_ids.product_attribute_value_id == galv_value
        for l in supply if l.product_id != gutter_p), R['si26_after'])
    l20 = supply.filtered(lambda l: l.product_id == flash20_p)
    check('si26_2546_flash20_moved', len(l20) == 1 and close(l20.price_unit, FLASH20_PRICE)
          and close(l20.product_uom_qty * 100, FLASH20_QTY * 100)
          and l20.tax_ids == supply.filtered(lambda l: l.product_id == flash_p).tax_ids, R['si26_after'])
    check('si26_2546_totals', close(ref.amount_untaxed, UNTAXED) and close(ref.amount_tax, TAX)
          and close(ref.amount_total, TOTAL), totals(ref))
    check('si26_2546_printable', ref._sipanel_customer_document_problems() == [],
          ref._sipanel_customer_document_problems())

    # ---- item 3: default contact language
    langs_before = dict(env['res.partner'].with_context(active_test=False)._read_group([], ['lang'], ['__count']))
    lang_field = env['ir.model.fields']._get('res.partner', 'lang')
    defaults = env['ir.default'].search([('field_id', '=', lang_field.id)])
    R['lang_defaults_before'] = [(d.id, d.json_value, d.user_id.id, d.company_id.id, d.condition) for d in defaults]
    glob = defaults.filtered(lambda d: not d.user_id and not d.company_id and not d.condition)
    check('partner_lang_default_expected_before', len(glob) == 1 and len(defaults) == 1
          and json.loads(glob.json_value) in (PARTNER_LANG_OLD, PARTNER_LANG_NEW), R['lang_defaults_before'])
    if len(glob) == 1 and json.loads(glob.json_value) == PARTNER_LANG_OLD:
        env['ir.default'].set('res.partner', 'lang', PARTNER_LANG_NEW)
        changed(f'ir.default {glob.id} res.partner.lang {PARTNER_LANG_OLD} -> {PARTNER_LANG_NEW}')
    defaults = env['ir.default'].search([('field_id', '=', lang_field.id)])
    R['lang_defaults_after'] = [(d.id, d.json_value, d.user_id.id, d.company_id.id, d.condition) for d in defaults]
    check('partner_lang_default_fa', len(defaults) == 1 and defaults == glob
          and env['ir.default']._get('res.partner', 'lang') == PARTNER_LANG_NEW
          and env['res.partner'].default_get(['lang'])['lang'] == PARTNER_LANG_NEW, R['lang_defaults_after'])
    # the owner decides which existing customers switch: listed, none changed
    customers = env['res.partner'].with_context(active_test=False).search(
        [('customer_rank', '>', 0)], order='name, id')
    orders = env['sale.order'].with_context(active_test=False)
    R['customers_by_lang'] = {}
    for p in customers:
        R['customers_by_lang'][p.lang or ''] = R['customers_by_lang'].get(p.lang or '', 0) + 1
    R['en_us_customers'] = [{'id': p.id, 'name': p.name, 'company': p.is_company, 'parent': p.parent_id.name or '',
                             'active': p.active, 'city': p.city or '', 'quotations': orders.search_count(
                                 [('partner_id', 'child_of', p.commercial_partner_id.id)]) if p.is_company else
                             orders.search_count([('partner_id', '=', p.id)]),
                             'created': str(p.create_date.date())}
                            for p in customers if p.lang == 'en_US']
    langs_after = dict(env['res.partner'].with_context(active_test=False)._read_group([], ['lang'], ['__count']))
    check('existing_partner_languages_untouched', langs_after == langs_before, [langs_before, langs_after])

    # ---- item 5: default quotation validity
    company = ref.company_id
    companies = env['res.company'].search([])
    R['validity_before'] = {c.name: c.quotation_validity_days for c in companies}
    check('validity_expected_before', company.quotation_validity_days in (VALIDITY_OLD, VALIDITY_NEW),
          company.quotation_validity_days)
    if company.quotation_validity_days == VALIDITY_OLD:
        company.quotation_validity_days = VALIDITY_NEW
        changed(f'res.company {company.id} quotation_validity_days {VALIDITY_OLD} -> {VALIDITY_NEW}')
    check('validity_8_days', company.quotation_validity_days == VALIDITY_NEW, company.quotation_validity_days)
    R['validity_after'] = {c.name: c.quotation_validity_days for c in companies}
except (AssertionError, UserError, ValueError) as exc:
    import traceback
    R['error'] = traceback.format_exc()

R['all_ok'] = all(c['ok'] for c in R['checks'].values()) and 'error' not in R
commit = os.environ.get('SIPANEL_PRODUCTS_COMMIT') == '1'
print('SIPANEL_PRODUCTS ' + json.dumps({'all_ok': R['all_ok'], 'failed': [k for k, c in R['checks'].items() if not c['ok']],
                                        'changed': R['changed'], 'error': R.get('error', '')[-600:]},
                                       ensure_ascii=False, default=str))
print('SIPANEL_PRODUCTS_DETAIL ' + json.dumps(R, ensure_ascii=False, default=str))
if commit and R['all_ok']:
    env.cr.commit()
    print('SIPANEL_PRODUCTS COMMITTED')
else:
    env.cr.rollback()
    print('SIPANEL_PRODUCTS ROLLED_BACK')
