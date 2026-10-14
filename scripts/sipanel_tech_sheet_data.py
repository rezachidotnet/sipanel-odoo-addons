# -*- coding: utf-8 -*-
"""Production step P8b of the quotation-lines deployment: System technical sheet, top-sheet material option, shop
drawings product and the SI-26/2546 data of the owner requirements of 2026-10-14. Runs after P8 (way A: SI-26/2546
has its 10 % installation line, which is part of the shop drawings base).

  sheet     SIPANEL System "Standing Seam" (account 2316): technical sheet = schematic v3
            (sipanel_quotation_lines/data/standing_seam_schematic.png, sha256 below; callouts 2-8 = rows 2-8, 8 = purlin)
            and rows 1-8 below (fa_IR as given by the owner, en_US translation). Row 7 is linked to the material
            attribute: it prints the text of the material chosen on the quotation.
  material  native product attribute «جنس ورق رویه» / "Top sheet material", create_variant = never, values
            «گالوانیزه» (first = default) and «آلومینیوم» (price extra required to print: undecided, 0 blocks printing),
            on the roof product SIP-000074 and the flashing product SIP-000076 (both flashing lines), price extra 0.
            No new products, no variants.
  shop      product "Shop Drawings" (service, Units, taxes as SIP-000075, no purchase), the System's shop drawings
            product.
  SI-26/2546 (never sent, still a draft): first section «سیستم پوشش سقف و دیوار استندینگ سیم»; roof line
            «سیستم پوشش سقف و دیوار استندینگ سیم (فقط تأمین)»; the flashing line (162.70 m) split 2:1 at 3:1 prices:
            58 cm 108.47 m × 43,800,000 and 20 cm 54.23 m × 14,600,000, both «… (فقط تأمین)»; material «گالوانیزه» on
            the roof and flashing lines; shop drawings 2 % discount 100 % (net 0); liner 0.7 mm; technical sheet copied
            from the System; System name captured per language (English PDF "Standing Seam").
            Expected: flashing 5,542,744,000; untaxed 27,364,418,400; total 30,100,860,240.

Run (odoo shell):
  docker exec -i [-e SIPANEL_TECH_SHEET_COMMIT=1] odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d sipanel --no-http < this
Without SIPANEL_TECH_SHEET_COMMIT=1 everything is rolled back (dry run). With it, the transaction is committed only
when EVERY check passes; otherwise it is rolled back and nothing changes. Idempotent: a second run finds everything in
the "after" state and changes nothing. Every record is found by a business key and must be in the expected "before" or
"after" state; anything else is refused (fail closed).
"""
import base64
import hashlib
import json
import os

from odoo.exceptions import UserError
from odoo.tools.misc import file_path

R = {'db': env.cr.dbname, 'checks': {}, 'changed': []}
env = env(su=True)
BEFORE_UNTAXED, BEFORE_TOTAL = 27_352_380_000, 30_087_618_000          # after P8 (way A)
UNTAXED, TAX, TOTAL = 27_364_418_400, 2_736_441_840, 30_100_860_240   # owner 2026-10-14
INSTALL_10, FLASH_TOTAL = 2_487_674_400, 5_542_744_000
SHOP_PCT, SHOP_DISCOUNT, SHOP_PRICE = 2.0, 100.0, 547_288_368          # 2 % of 27,364,418,400
ROOF_CODE, FLASH_CODE, INSTALL_CODE = 'SIP-000074', 'SIP-000076', 'SIP-000075'
ROOF_OLD_NAME = 'سیستم پوشش سقف استندینگ سیم (فقط تأمین)'
ROOF_NAME = 'سیستم پوشش سقف و دیوار استندینگ سیم (فقط تأمین)'
FLASH_QTY, FLASH_OLD_PRICE = 162.7, 34_000_000
FLASH_OLD_NAME = 'فلاشینگ و فیلر بلوک هم‌جنس ورق رویه (فقط تأمین)'
FLASH_LINES = (('فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۵۸ سانتی‌متر (فقط تأمین)', 108.47, 43_800_000),   # 2:1, 3:1
               ('فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۲۰ سانتی‌متر (فقط تأمین)', 54.23, 14_600_000))
SECTION_OLD, SECTION_NEW = 'سیستم پوشش سقف استندینگ سیم', 'سیستم پوشش سقف و دیوار استندینگ سیم'
SYSTEM_NAMES = {'en_US': 'Standing Seam', 'fa_IR': 'استندینگ سیم'}
SHOP_NAME = {'en_US': 'Shop Drawings', 'fa_IR': 'تهیه‌ی نقشه‌های اجرایی (شاپ)'}
LINER = '0.7'
IMAGE = 'sipanel_quotation_lines/data/standing_seam_schematic.png'
IMAGE_SHA256 = 'e64859f0257b42676a2a8d910d503e827759047b3ebe2bb9c7dee569c478dfbc'     # v3 (owner 2026-10-14)
MATERIAL = {'en_US': 'Top sheet material', 'fa_IR': 'جنس ورق رویه'}
MATERIAL_VALUES = [  # (en name, fa name, price extra required, spec text en, spec text fa) - first = default
    ('Galvanized', 'گالوانیزه', False,
     'Pre-painted galvanized steel sheet, 0.5 mm thick, standing seam profile; seam height 65 mm, effective width '
     '445 mm; colour from the RAL chart at the client\'s choice; no exposed fasteners, seams locked over the clips with '
     'a seaming machine',
     'ورق فولادی گالوانیزه‌ی پیش‌رنگ به ضخامت ۰.۵ میلیمتر با پروفیل درز ایستاده؛ ارتفاع درز ۶۵ میلیمتر، عرض مؤثر ۴۴۵ '
     'میلیمتر؛ رنگ از کاتالوگ RAL به انتخاب کارفرما؛ بدون پیچ رویه، با قفل درزها روی کلیپس توسط دستگاه سیمر'),
    ('Aluminium', 'آلومینیوم', True,
     'Pre-painted aluminium sheet, alloy 3105, 0.9 mm thick, standing seam profile; seam height 65 mm, effective width '
     '400 mm; colour from the RAL chart at the client\'s choice; no exposed fasteners, seams locked over the clips with '
     'a seaming machine',
     'ورق آلومینیوم پیش‌رنگ آلیاژ ۳۱۰۵ به ضخامت ۰.۹ میلیمتر با پروفیل درز ایستاده؛ ارتفاع درز ۶۵ میلیمتر، عرض مؤثر ۴۰۰ '
     'میلیمتر؛ رنگ از کاتالوگ RAL به انتخاب کارفرما؛ بدون پیچ رویه، با قفل درزها روی کلیپس توسط دستگاه سیمر'),
]
# (number, title fa, description fa, title en, description en, linked to the material attribute)
# {liner_thickness} = the quotation's 0.5 / 0.7; row 7 prints the chosen material's text (no own description)
ROWS = [
    (1, 'نقشه‌های اجرایی', 'تهیه‌ی نقشه‌های شاپ و جزئیات اجرایی پوشش سقف و دیوار',
     'Shop drawings', 'Preparation of the shop drawings and execution details of the roof and wall cladding', False),
    (2, 'ورق زیرین', 'ورق گالوانیزه با پروفیل ذوزنقه‌ای یا موج‌دار کم‌ارتفاع، ضخامت {liner_thickness} میلیمتر، اتصال با '
                    'پیچ خودکار گالوانیزه؛ فاصله‌ی تکیه‌گاه‌های زیرسازی حداکثر ۲ متر',
     'Liner sheet', 'Galvanized steel sheet with a low trapezoidal or corrugated profile, {liner_thickness} mm thick, '
                    'fixed with galvanized self-drilling screws; substructure supports at most 2 m apart', False),
    (3, 'لایه‌ی بخاربند', 'لایه‌ی چهارلایه‌ی کامپوزیت فویل آلومینیوم، پلی‌اتیلن و الیاف پلی‌استر، ضخامت ۲۲۰ میکرون',
     'Vapour barrier', 'Four-layer composite membrane of aluminium foil, polyethylene and polyester fibres, '
                       '220 microns thick', False),
    (4, 'فاصله‌انداز امگا', 'پروفیل امگای گالوانیزه، ضخامت ۱.۲۵ و ارتفاع ۳۰ میلیمتر، با فاصله‌ی حدود ۲ متر؛ در لبه‌ها و '
                           'گوشه‌هایی که مکش باد بیشتر است، پروفیل ۱.۵ میلیمتری با فاصله‌ی کمتر',
     'Omega spacer', 'Galvanized omega profile, 1.25 mm thick and 30 mm high, at about 2 m spacing; at the edges and '
                     'corners with higher wind suction, 1.5 mm profiles at a closer spacing', False),
    (5, 'کلیپس نگهدارنده', 'کلیپس آلومینیومی به ارتفاع ۱۰۰ میلیمتر روی پد عایق PVC به ضخامت ۵ میلیمتر (قطع پل حرارتی)، '
                          'با پیچ‌های گالوانیزه',
     'Holding clip', 'Aluminium clip, 100 mm high, on a 5 mm PVC insulating pad (thermal break), fixed with '
                     'galvanized screws', False),
    (6, 'عایق حرارتی و صوتی', 'پشم سنگ تخته‌ای بدون روکش، دانسیته‌ی ۵۰ کیلوگرم بر مترمکعب، دو لایه‌ی ۵۰ میلیمتری '
                             '(مجموع ۱۰۰ میلیمتر)',
     'Thermal and acoustic insulation', 'Unfaced rock wool boards, density 50 kg/m³, two 50 mm layers '
                                        '(100 mm in total)', False),
    (7, 'ورق رویه‌ی استندینگ سیم', None, 'Standing seam top sheet', None, True),
    (8, 'سازه‌ی نگهدارنده (پرلین)', 'پرلین فولادی سقف و دیوار با فاصله‌ی حداکثر ۲ متر؛ طراحی، تأمین و اجرای آن بر عهده‌ی '
                                   'کارفرما و خارج از محدوده‌ی این پیش‌فاکتور است.',
     'Supporting structure (purlins)', 'Steel roof and wall purlins at a maximum spacing of 2 m; their design, supply '
                                       'and installation are by the client and outside the scope of this quotation.',
     False),
]


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


def rows_of(records):
    return [(r.number, stored(r, 'title'), stored(r, 'description'), bool(r.attribute_id))
            for r in records.sorted(lambda r: (r.sequence, r.number, r.id))]


def expected_rows():
    return [(n, {'en_US': te, 'fa_IR': tf}, {'en_US': de, 'fa_IR': df} if de else {}, linked)
            for n, tf, df, te, de, linked in ROWS]


def totals(order):
    return [order.amount_untaxed, order.amount_tax, order.amount_total]


def never_sent(order):
    msgs = env['mail.message'].search([('model', '=', 'sale.order'), ('res_id', '=', order.id)])
    comment = env.ref('mail.mt_comment')
    return order.state == 'draft' and not order.signed_by and not msgs.filtered(
        lambda m: m.message_type == 'email' or (m.subtype_id == comment and m.partner_ids))


def set_terms(record, field, terms):
    record.with_context(lang='en_US').write({field: terms['en_US']})
    record.update_field_translations(field, dict(terms))


try:
    assert 'sipanel_spec_text' in env['product.attribute.value']._fields, \
        'sipanel_quotation_lines 19.0.1.3.0 (technical sheet + options) is not installed'

    # ---- master data: System, products
    plan = env['sipanel.config'].system_plan()
    seam = env['account.analytic.account'].with_context(lang='en_US').search(
        [('plan_id', '=', plan.id), ('name', '=', SYSTEM_NAMES['en_US']), ('active', '=', True)])
    Product = env['product.product'].with_context(active_test=False)
    install = Product.search([('default_code', '=', INSTALL_CODE)])
    roof_p = Product.search([('default_code', '=', ROOF_CODE)])
    flash_p = Product.search([('default_code', '=', FLASH_CODE)])
    check('standing_seam_system', len(seam) == 1 and len(install) == 1
          and seam.sipanel_installation_product_id == install, [seam.ids, install.ids])
    check('system_name_fa_en', len(seam) == 1 and stored(seam, 'name') == SYSTEM_NAMES, stored(seam, 'name') if seam else None)
    check('roof_flashing_products', len(roof_p) == 1 and len(flash_p) == 1, [roof_p.ids, flash_p.ids])
    seam.ensure_one()

    # ---- material attribute (native, no_variant)
    Attr = env['product.attribute'].with_context(lang='en_US')
    attr = Attr.search([('name', '=', MATERIAL['en_US'])])
    check('material_attribute_unique', len(attr) <= 1, attr.ids)
    if not attr:
        attr = Attr.create({'name': MATERIAL['en_US'], 'create_variant': 'no_variant', 'display_type': 'radio'})
        attr.update_field_translations('name', dict(MATERIAL))
        for seq, (name_en, name_fa, required, text_en, text_fa) in enumerate(MATERIAL_VALUES, start=1):
            value = env['product.attribute.value'].with_context(lang='en_US').create({
                'attribute_id': attr.id, 'name': name_en, 'sequence': seq, 'default_extra_price': 0.0,
                'sipanel_price_required': required, 'sipanel_spec_text': text_en})
            value.update_field_translations('name', {'en_US': name_en, 'fa_IR': name_fa})
            value.update_field_translations('sipanel_spec_text', {'en_US': text_en, 'fa_IR': text_fa})
        changed(f'product.attribute {attr.id} "{MATERIAL["en_US"]}" created (no_variant, 2 values)')
    values = attr.value_ids.sorted(lambda v: (v.sequence, v.id))
    R['material'] = {'attribute': stored(attr, 'name'), 'create_variant': attr.create_variant,
                     'values': [(stored(v, 'name'), v.sipanel_price_required, stored(v, 'sipanel_spec_text'))
                                for v in values]}
    check('material_attribute', attr.create_variant == 'no_variant' and stored(attr, 'name') == MATERIAL
          and [(stored(v, 'name'), v.sipanel_price_required, stored(v, 'sipanel_spec_text')) for v in values]
          == [({'en_US': e, 'fa_IR': f}, req, {'en_US': te, 'fa_IR': tf}) for e, f, req, te, tf in MATERIAL_VALUES],
          R['material'])
    galv = values[:1]
    variants_before = {p.product_tmpl_id.id: p.product_tmpl_id.with_context(active_test=False).product_variant_ids.ids
                       for p in roof_p | flash_p}
    for product in roof_p | flash_p:
        tmpl = product.product_tmpl_id
        ptal = tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == attr)
        if not ptal:
            tmpl.write({'attribute_line_ids': [(0, 0, {'attribute_id': attr.id, 'value_ids': [(6, 0, values.ids)]})]})
            changed(f'{product.default_code}: material attribute line added')
    for product in roof_p | flash_p:
        tmpl = product.product_tmpl_id
        ptal = tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == attr)
        ptavs = ptal.product_template_value_ids
        check(f'{product.default_code}_material_line', len(ptal) == 1 and ptal.value_ids == values
              and ptavs.product_attribute_value_id == values and all(p.price_extra == 0.0 for p in ptavs),
              [(p.name, p.price_extra) for p in ptavs])
        check(f'{product.default_code}_no_new_variant',
              tmpl.with_context(active_test=False).product_variant_ids.ids == variants_before[tmpl.id]
              and product.exists() and product.product_tmpl_id == tmpl, tmpl.with_context(active_test=False).product_variant_ids.ids)

    # ---- shop drawings product
    shop = seam.sipanel_shop_drawing_product_id
    if not shop:
        tmpl_src = install.product_tmpl_id
        vals = {'name': SHOP_NAME['en_US'], 'type': 'service', 'sale_ok': True, 'purchase_ok': False, 'list_price': 0.0,
                'uom_id': env.ref('uom.product_uom_unit').id, 'taxes_id': [(6, 0, tmpl_src.taxes_id.ids)],
                'categ_id': tmpl_src.categ_id.id, 'company_id': tmpl_src.company_id.id,
                'invoice_policy': tmpl_src.invoice_policy, 'sipanel_installation_base': False,
                'sipanel_installation_work': False}
        if 'service_tracking' in tmpl_src._fields:
            vals['service_tracking'] = 'no'
        shop = env['product.product'].with_context(lang='en_US').create(vals)
        shop.product_tmpl_id.update_field_translations('name', dict(SHOP_NAME))
        seam.sipanel_shop_drawing_product_id = shop
        changed(f'product {shop.id} "Shop Drawings" created and mapped on System {seam.id}')
    R['shop_product'] = {'id': shop.id, 'name': stored(shop.product_tmpl_id, 'name'), 'type': shop.type,
                         'uom': shop.uom_id.name, 'taxes': shop.taxes_id.mapped('name'),
                         'install_taxes': install.taxes_id.mapped('name'), 'purchase_ok': shop.purchase_ok}
    check('shop_product', shop.type == 'service' and shop.sale_ok and not shop.purchase_ok
          and shop.uom_id == env.ref('uom.product_uom_unit') and shop.taxes_id == install.taxes_id
          and stored(shop.product_tmpl_id, 'name') == SHOP_NAME
          and not shop.sipanel_installation_base and not shop.sipanel_installation_work, R['shop_product'])

    # ---- technical sheet of the System
    with open(file_path(IMAGE), 'rb') as f:
        image_bytes = f.read()
    check('schematic_file_v3', hashlib.sha256(image_bytes).hexdigest() == IMAGE_SHA256, len(image_bytes))
    if not seam.sipanel_tech_image:
        seam.sipanel_tech_image = base64.b64encode(image_bytes)
        changed('System schematic set')
    check('system_schematic', hashlib.sha256(base64.b64decode(seam.sipanel_tech_image)).hexdigest() == IMAGE_SHA256)
    if not seam.sipanel_tech_spec_ids:
        Row = env['sipanel.system.spec.line'].with_context(lang='en_US')
        for number, title_fa, desc_fa, title_en, desc_en, linked in ROWS:
            row = Row.create({'system_id': seam.id, 'sequence': number * 10, 'number': number, 'title': title_en,
                              'description': desc_en or False, 'attribute_id': attr.id if linked else False})
            row.update_field_translations('title', {'en_US': title_en, 'fa_IR': title_fa})
            if desc_en:
                row.update_field_translations('description', {'en_US': desc_en, 'fa_IR': desc_fa})
        changed(f'System technical sheet: {len(ROWS)} rows')
    sheet = rows_of(seam.sipanel_tech_spec_ids)
    check('system_rows', sheet == expected_rows() and seam.sipanel_tech_spec_ids.filtered('attribute_id').attribute_id
          == attr, sheet)

    # ---- SI-26/2546
    ref = env['sale.order'].search([('name', '=', 'SI-26/2546')])
    check('si26_2546_quotation_not_sent', len(ref) == 1 and never_sent(ref), [len(ref), ref.state])
    ref.ensure_one()
    R['before'] = {'totals': totals(ref), 'lines': [(l.sequence, l.display_type or l.product_id.default_code, l.name,
                                                     l.product_uom_qty, l.price_unit) for l in ref.order_line.sorted(
                                                         lambda l: (l.sequence, l.id))]}
    check('si26_2546_totals_before', (close(ref.amount_untaxed, BEFORE_UNTAXED) and close(ref.amount_total, BEFORE_TOTAL))
          or (close(ref.amount_untaxed, UNTAXED) and close(ref.amount_total, TOTAL)), totals(ref))
    check('si26_2546_installation_pct', close(ref.sipanel_installation_pct, 10.0), ref.sipanel_installation_pct)
    check('si26_2546_requested_system', ref.sipanel_requested_system_id == seam, ref.sipanel_requested_system_id.ids)

    sections = ref.order_line.filtered(lambda l: l.display_type == 'line_section' and not l.sipanel_is_installation_line)
    first = sections.sorted(lambda l: (l.sequence, l.id))[:1]
    check('first_section_expected_before', first.name in (SECTION_OLD, SECTION_NEW), first.name)
    if first.name == SECTION_OLD:
        first.name = SECTION_NEW
        changed('SI-26/2546 first section renamed')

    roof = ref.order_line.filtered(lambda l: not l.display_type and l.product_id == roof_p)
    check('roof_line_expected_before', len(roof) == 1 and roof.name.split('\n')[0] in (ROOF_OLD_NAME, ROOF_NAME),
          roof.mapped('name'))
    if len(roof) == 1 and roof.name == ROOF_OLD_NAME:
        roof.name = ROOF_NAME
        changed('SI-26/2546 roof line renamed (roof + wall)')

    flash = ref.order_line.filtered(lambda l: not l.display_type and l.product_id == flash_p)
    titles = lambda lines: sorted((l.name.split('\n')[0], l.product_uom_qty, l.price_unit) for l in lines)
    split_done = titles(flash) == sorted((n, q, float(p)) for n, q, p in FLASH_LINES)
    single = (len(flash) == 1 and flash.name == FLASH_OLD_NAME and close(flash.product_uom_qty * 100, FLASH_QTY * 100)
              and close(flash.price_unit, FLASH_OLD_PRICE))
    check('flashing_expected_before', split_done or single, [(l.name, l.product_uom_qty, l.price_unit) for l in flash])
    if single and not split_done:
        taxes, seq = flash.tax_ids, flash.sequence
        (name_58, qty_58, price_58), (name_20, qty_20, price_20) = FLASH_LINES
        # every later line moves one step down, so the second flashing line sits right after the first
        for line in ref.order_line.filtered(lambda l: l.sequence > seq).sorted(lambda l: (-l.sequence, -l.id)):
            line.sequence += 1
        flash.write({'name': name_58, 'product_uom_qty': qty_58})
        flash.price_unit = price_58           # written last: a quantity change re-prices a create-time price
        second = env['sale.order.line'].create({'order_id': ref.id, 'product_id': flash_p.id,
                                                'product_uom_qty': qty_20, 'product_uom_id': flash.product_uom_id.id,
                                                'name': name_20, 'sequence': seq + 1})
        second.price_unit = price_20          # written after create: a manual price (Odoo 19 technical_price_unit)
        check('flashing_second_line_taxes', second.tax_ids == taxes, [second.tax_ids.ids, taxes.ids])
        changed('SI-26/2546 flashing split 2:1 at 43,800,000 / 14,600,000')
    flash = ref.order_line.filtered(lambda l: not l.display_type and l.product_id == flash_p)

    # material «گالوانیزه» on the roof and both flashing lines (adds the native «جنس ورق رویه: گالوانیزه» line)
    for line in roof | flash:
        ptav = line.product_id.product_tmpl_id.attribute_line_ids.filtered(
            lambda l: l.attribute_id == attr).product_template_value_ids.filtered(lambda p: p.product_attribute_value_id == galv)
        current = line.product_no_variant_attribute_value_ids.filtered(lambda p: p.attribute_id == attr)
        if current != ptav:
            line.product_no_variant_attribute_value_ids = [(6, 0, (line.product_no_variant_attribute_value_ids - current
                                                                   | ptav).ids)]
            changed(f'SI-26/2546 line {line.id}: material Galvanized')
    material_text = '\n' + 'جنس ورق رویه: گالوانیزه'
    check('material_on_lines', all(l.product_no_variant_attribute_value_ids.product_attribute_value_id == galv
                                   for l in roof | flash), [(l.id, l.name) for l in roof | flash])
    check('roof_line', len(roof) == 1 and roof.name == ROOF_NAME + material_text and close(roof.price_unit, 88_000_000),
          roof.name)
    check('flashing_split', titles(flash) == sorted((n, q, float(p)) for n, q, p in FLASH_LINES)
          and all(l.name.endswith(material_text) for l in flash)
          and close(sum(flash.mapped('price_subtotal')), FLASH_TOTAL), [(l.name, l.price_unit, l.price_subtotal) for l in flash])

    if (ref.sipanel_shop_drawing_pct, ref.sipanel_shop_drawing_discount) != (SHOP_PCT, SHOP_DISCOUNT):
        check('shop_expected_before', (ref.sipanel_shop_drawing_pct, ref.sipanel_shop_drawing_discount) == (0.0, 0.0),
              [ref.sipanel_shop_drawing_pct, ref.sipanel_shop_drawing_discount])
        ref.write({'sipanel_shop_drawing_pct': SHOP_PCT, 'sipanel_shop_drawing_discount': SHOP_DISCOUNT})
        changed('SI-26/2546 shop drawings 2 %, discount 100 %')
    if ref.sipanel_liner_thickness != LINER:
        ref.sipanel_liner_thickness = LINER
        changed('SI-26/2546 liner thickness 0.7')
    if not ref.sipanel_tech_spec_ids and not ref.sipanel_tech_image:
        ref.action_sipanel_load_tech_sheet()
        changed('SI-26/2546 technical sheet copied from the System')
    if not ref.sipanel_system_print_name:
        ref._sipanel_capture_system_print_name()
        changed('SI-26/2546 System name captured per language')

    # ---- after
    ordered = ref.order_line.sorted(lambda l: (l.sequence, l.id))
    shop_lines = ref._sipanel_managed_lines('shop_drawing')
    shop_line = shop_lines.filtered(lambda l: not l.display_type)
    inst_line = ref._sipanel_managed_lines('installation').filtered(lambda l: not l.display_type)
    R['after'] = {'totals': totals(ref), 'lines': [(l.sequence, l.display_type or l.product_id.default_code, l.name,
                                                    l.product_uom_qty, l.price_unit, l.discount, l.price_subtotal,
                                                    l.price_tax, l.sipanel_managed_role) for l in ordered]}
    check('si26_2546_totals', close(ref.amount_untaxed, UNTAXED) and close(ref.amount_tax, TAX)
          and close(ref.amount_total, TOTAL), totals(ref))
    check('installation_line', len(inst_line) == 1 and close(inst_line.price_subtotal, INSTALL_10),
          inst_line.mapped('price_subtotal'))
    check('shop_line', len(shop_line) == 1 and shop_line.product_id == shop and shop_line.product_uom_qty == 1.0
          and close(shop_line.price_unit, SHOP_PRICE) and shop_line.discount == SHOP_DISCOUNT
          and close(shop_line.price_subtotal, 0) and close(shop_line.price_tax, 0),
          [shop_line.price_unit, shop_line.discount, shop_line.price_subtotal] if len(shop_line) == 1 else len(shop_line))
    check('shop_block_last', len(shop_lines) == 2 and list(ordered[-2:]) == list(
        shop_lines.sorted(lambda l: (l.sequence, l.id))) and ordered[-2].display_type == 'line_section')
    check('shop_line_label_fa', shop_line.name.split('\n')[0] == SHOP_NAME['fa_IR'] if len(shop_line) == 1 else False,
          shop_line.name if len(shop_line) == 1 else None)
    check('liner_thickness', ref.sipanel_liner_thickness == LINER)
    snapshot = rows_of(ref.sipanel_tech_spec_ids)
    check('si26_2546_sheet_snapshot', snapshot == sheet and bool(ref.sipanel_tech_image)
          and hashlib.sha256(base64.b64decode(ref.sipanel_tech_image)).hexdigest() == IMAGE_SHA256, snapshot)
    printed_fa = ref.with_context(lang='fa_IR')._sipanel_tech_sheet_rows()
    printed_en = ref.with_context(lang='en_US')._sipanel_tech_sheet_rows()
    R['printed_rows'] = {'fa_IR': printed_fa, 'en_US': printed_en}
    check('row2_prints_0_7', len(printed_fa) == 8 and 'ضخامت ۰.۷ میلیمتر' in printed_fa[1][2]
          and '0.7 mm thick' in printed_en[1][2], printed_fa[1:2])
    check('row7_prints_galvanized', len(printed_fa) == 8 and printed_fa[6][2] == MATERIAL_VALUES[0][4]
          and printed_en[6][2] == MATERIAL_VALUES[0][3], [printed_fa[6:7], printed_en[6:7]])
    check('system_print_name', stored(ref, 'sipanel_system_print_name') == SYSTEM_NAMES
          and ref.with_context(lang='en_US')._sipanel_system_print_label() == SYSTEM_NAMES['en_US']
          and ref.with_context(lang='fa_IR')._sipanel_system_print_label() == SYSTEM_NAMES['fa_IR'],
          stored(ref, 'sipanel_system_print_name'))
    check('si26_2546_printable', ref._sipanel_customer_document_problems() == [],
          ref._sipanel_customer_document_problems())
except (AssertionError, UserError, ValueError) as exc:
    import traceback
    R['error'] = traceback.format_exc()

R['all_ok'] = all(c['ok'] for c in R['checks'].values()) and 'error' not in R
commit = os.environ.get('SIPANEL_TECH_SHEET_COMMIT') == '1'
print('SIPANEL_TECH_SHEET ' + json.dumps({'all_ok': R['all_ok'], 'failed': [k for k, c in R['checks'].items() if not c['ok']],
                                          'changed': R['changed'], 'error': R.get('error', '')[-600:]},
                                         ensure_ascii=False, default=str))
print('SIPANEL_TECH_SHEET_DETAIL ' + json.dumps(R, ensure_ascii=False, default=str))
if commit and R['all_ok']:
    env.cr.commit()
    print('SIPANEL_TECH_SHEET COMMITTED')
else:
    env.cr.rollback()
    print('SIPANEL_TECH_SHEET ROLLED_BACK')
