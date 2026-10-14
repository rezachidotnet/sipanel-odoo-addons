# -*- coding: utf-8 -*-
"""Production step P8b of the quotation-lines deployment: System technical sheet, shop drawings product and the
SI-26/2546 data of the owner requirements of 2026-10-14 (items 2-5). Runs after P8 (way A: SI-26/2546 has its
10 % installation line, which is part of the shop drawings base).

  item 2/4  SIPANEL System "Standing Seam" (account 2316): technical sheet = the schematic
            (sipanel_quotation_lines/data/standing_seam_schematic.png, sha256 below; callouts 2-8 = rows 2-8) and the
            specification rows below (fa_IR as given by the owner, en_US translation).
  item 5    product "Shop Drawings" (service, Units, taxes as the installation product SIP-000075, no purchase) mapped
            as the System's shop drawings product.
  item 5, on SI-26/2546 only (never sent, still a draft):
            first section «سیستم پوشش سقف و دیوار استندینگ سیم» (206 m² = roof + wall);
            the flashing line (162.70 m × 34,000,000) split 2:1 into «… تا ۵۸ سانتی‌متر» 108.47 m and «… تا ۲۰ سانتی‌متر»
            54.23 m at the same price (supply subtotal unchanged);
            shop drawings 2 % of the installation base + the installation line, discount 100 % (net 0);
            liner thickness 0.7 mm; its technical sheet copied from the System.
  item 6    the terms text is in P6b (scripts/sipanel_quotation_terms_data.py).

Run (odoo shell):
  docker exec -i [-e SIPANEL_TECH_SHEET_COMMIT=1] odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d sipanel --no-http < this
Without SIPANEL_TECH_SHEET_COMMIT=1 everything is rolled back (dry run). With it, the transaction is committed only
when EVERY check passes; otherwise it is rolled back and nothing changes. Idempotent: a second run finds everything in
the "after" state and changes nothing. Every record is found by a business key and must be in the expected "before" or
"after" state; anything else is refused (fail closed). Totals of SI-26/2546 must not move (the shop line is net 0).
"""
import base64
import hashlib
import json
import os

from odoo.exceptions import UserError
from odoo.tools.misc import file_path

R = {'db': env.cr.dbname, 'checks': {}, 'changed': []}
env = env(su=True)
UNTAXED, TAX, TOTAL = 27_352_380_000, 2_735_238_000, 30_087_618_000
INSTALL_10 = 2_486_580_000
SHOP_PCT, SHOP_DISCOUNT, SHOP_PRICE = 2.0, 100.0, 547_047_600          # 2 % of 27,352,380,000
FLASH_CODE, FLASH_PRICE, FLASH_QTY = 'SIP-000076', 34_000_000, 162.7
FLASH_OLD_NAME = 'فلاشینگ و فیلر بلوک هم‌جنس ورق رویه (فقط تأمین)'
FLASH_LINES = (('فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۵۸ سانتی‌متر', 108.47),     # owner 2026-10-14, 2:1
               ('فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۲۰ سانتی‌متر', 54.23))
SECTION_OLD, SECTION_NEW = 'سیستم پوشش سقف استندینگ سیم', 'سیستم پوشش سقف و دیوار استندینگ سیم'
SYSTEM_EN = 'Standing Seam'
INSTALL_CODE = 'SIP-000075'
SHOP_NAME = {'en_US': 'Shop Drawings', 'fa_IR': 'تهیه‌ی نقشه‌های اجرایی (شاپ)'}
LINER = '0.7'
IMAGE = 'sipanel_quotation_lines/data/standing_seam_schematic.png'
IMAGE_SHA256 = 'e64859f0257b42676a2a8d910d503e827759047b3ebe2bb9c7dee569c478dfbc'
# (number, title fa, description fa, title en, description en); {liner_thickness} = the quotation's 0.5 / 0.7
ROWS = [
    (1, 'نقشه‌های اجرایی', 'تهیه‌ی نقشه‌های شاپ و جزئیات اجرایی پوشش سقف و دیوار',
     'Shop drawings', 'Preparation of the shop drawings and execution details of the roof and wall cladding'),
    (2, 'ورق زیرین', 'ورق گالوانیزه با پروفیل ذوزنقه‌ای یا موج‌دار کم‌ارتفاع، ضخامت {liner_thickness} میلیمتر، اتصال با '
                    'پیچ خودکار گالوانیزه؛ فاصله‌ی تکیه‌گاه‌های زیرسازی حداکثر ۲ متر',
     'Liner sheet', 'Galvanized steel sheet with a low trapezoidal or corrugated profile, {liner_thickness} mm thick, '
                    'fixed with galvanized self-drilling screws; substructure supports at most 2 m apart'),
    (3, 'لایه‌ی بخاربند', 'لایه‌ی چهارلایه‌ی کامپوزیت فویل آلومینیوم، پلی‌اتیلن و الیاف پلی‌استر، ضخامت ۲۲۰ میکرون',
     'Vapour barrier', 'Four-layer composite membrane of aluminium foil, polyethylene and polyester fibres, '
                       '220 microns thick'),
    (4, 'فاصله‌انداز امگا', 'پروفیل امگای گالوانیزه، ضخامت ۱.۲۵ و ارتفاع ۳۰ میلیمتر، با فاصله‌ی حدود ۲ متر؛ در لبه‌ها و '
                           'گوشه‌هایی که مکش باد بیشتر است، پروفیل ۱.۵ میلیمتری با فاصله‌ی کمتر',
     'Omega spacer', 'Galvanized omega profile, 1.25 mm thick and 30 mm high, at about 2 m spacing; at the edges and '
                     'corners with higher wind suction, 1.5 mm profiles at a closer spacing'),
    (5, 'کلیپس نگهدارنده', 'کلیپس آلومینیومی به ارتفاع ۱۰۰ میلیمتر روی پد عایق PVC به ضخامت ۵ میلیمتر (قطع پل حرارتی)، '
                          'با پیچ‌های گالوانیزه',
     'Holding clip', 'Aluminium clip, 100 mm high, on a 5 mm PVC insulating pad (thermal break), fixed with '
                     'galvanized screws'),
    (6, 'عایق حرارتی و صوتی', 'پشم سنگ تخته‌ای بدون روکش، دانسیته‌ی ۵۰ کیلوگرم بر مترمکعب، دو لایه‌ی ۵۰ میلیمتری '
                             '(مجموع ۱۰۰ میلیمتر)',
     'Thermal and acoustic insulation', 'Unfaced rock wool boards, density 50 kg/m³, two 50 mm layers '
                                        '(100 mm in total)'),
    # rows 7 and 8: text pending owner confirmation (2026-10-14) - None refuses the whole step
    (7, 'ورق رویه‌ی استندینگ سیم', None, 'Standing seam top sheet', None),
    (8, None, None, None, None),
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
    return [(r.number, stored(r, 'title'), stored(r, 'description')) for r in records.sorted(lambda r: (r.sequence, r.number, r.id))]


def expected_rows():
    return [(n, {'en_US': te, 'fa_IR': tf}, {'en_US': de, 'fa_IR': df}) for n, tf, df, te, de in ROWS]


def totals(order):
    return [order.amount_untaxed, order.amount_tax, order.amount_total]


def never_sent(order):
    msgs = env['mail.message'].search([('model', '=', 'sale.order'), ('res_id', '=', order.id)])
    comment = env.ref('mail.mt_comment')
    return order.state == 'draft' and not order.signed_by and not msgs.filtered(
        lambda m: m.message_type == 'email' or (m.subtype_id == comment and m.partner_ids))


try:
    assert 'sipanel_tech_spec_ids' in env['sale.order']._fields, 'sipanel_quotation_lines 19.0.1.3.0 is not installed'
    check('rows_7_8_confirmed', all(all(v for v in row[1:]) for row in ROWS),
          [row[0] for row in ROWS if not all(v for v in row[1:])])
    ROWS = [row for row in ROWS if all(v for v in row[1:])]

    # ---- master data: System, shop drawings product, technical sheet
    plan = env['sipanel.config'].system_plan()
    seam = env['account.analytic.account'].with_context(lang='en_US').search(
        [('plan_id', '=', plan.id), ('name', '=', SYSTEM_EN), ('active', '=', True)])
    install = env['product.product'].with_context(active_test=False).search([('default_code', '=', INSTALL_CODE)])
    check('standing_seam_system', len(seam) == 1 and len(install) == 1
          and seam.sipanel_installation_product_id == install, [seam.ids, install.ids])
    seam.ensure_one()

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
                         'install_taxes': install.taxes_id.mapped('name'), 'purchase_ok': shop.purchase_ok,
                         'service_tracking': shop.product_tmpl_id['service_tracking']
                         if 'service_tracking' in shop.product_tmpl_id._fields else None}
    check('shop_product', shop.type == 'service' and shop.sale_ok and not shop.purchase_ok
          and shop.uom_id == env.ref('uom.product_uom_unit') and shop.taxes_id == install.taxes_id
          and stored(shop.product_tmpl_id, 'name') == SHOP_NAME
          and not shop.sipanel_installation_base and not shop.sipanel_installation_work, R['shop_product'])

    with open(file_path(IMAGE), 'rb') as f:
        image_bytes = f.read()
    check('schematic_file', hashlib.sha256(image_bytes).hexdigest() == IMAGE_SHA256, len(image_bytes))
    image_b64 = base64.b64encode(image_bytes)
    if not seam.sipanel_tech_image:
        seam.sipanel_tech_image = image_b64
        changed('System schematic set')
    check('system_schematic', hashlib.sha256(base64.b64decode(seam.sipanel_tech_image)).hexdigest() == IMAGE_SHA256)
    if not seam.sipanel_tech_spec_ids:
        Row = env['sipanel.system.spec.line'].with_context(lang='en_US')
        for number, title_fa, desc_fa, title_en, desc_en in ROWS:
            row = Row.create({'system_id': seam.id, 'sequence': number * 10, 'number': number,
                              'title': title_en, 'description': desc_en})
            row.update_field_translations('title', {'en_US': title_en, 'fa_IR': title_fa})
            row.update_field_translations('description', {'en_US': desc_en, 'fa_IR': desc_fa})
        changed(f'System technical sheet: {len(ROWS)} rows')
    sheet = rows_of(seam.sipanel_tech_spec_ids)
    check('system_rows', sheet == expected_rows()[:len(ROWS)] and len(ROWS) == 8, sheet)

    # ---- SI-26/2546
    ref = env['sale.order'].search([('name', '=', 'SI-26/2546')])
    check('si26_2546_quotation_not_sent', len(ref) == 1 and never_sent(ref), [len(ref), ref.state])
    ref.ensure_one()
    R['before'] = {'totals': totals(ref), 'lines': [(l.sequence, l.display_type or l.product_id.default_code, l.name,
                                                     l.product_uom_qty, l.price_unit) for l in ref.order_line.sorted(
                                                         lambda l: (l.sequence, l.id))]}
    check('si26_2546_totals_before', close(ref.amount_untaxed, UNTAXED) and close(ref.amount_total, TOTAL), totals(ref))
    check('si26_2546_installation_before', close(ref.sipanel_installation_pct, 10.0)
          and close(ref.sipanel_installation_amount, INSTALL_10), ref.sipanel_installation_amount)
    check('si26_2546_requested_system', ref.sipanel_requested_system_id == seam, ref.sipanel_requested_system_id.ids)

    sections = ref.order_line.filtered(lambda l: l.display_type == 'line_section' and not l.sipanel_is_installation_line)
    first = sections.sorted(lambda l: (l.sequence, l.id))[:1]
    check('first_section_expected_before', first.name in (SECTION_OLD, SECTION_NEW), first.name)
    if first.name == SECTION_OLD:
        first.name = SECTION_NEW
        changed('SI-26/2546 first section renamed')

    flash = ref.order_line.filtered(lambda l: not l.display_type and l.product_id.default_code == FLASH_CODE)
    split_done = sorted((l.name, l.product_uom_qty) for l in flash) == sorted(FLASH_LINES)
    single = len(flash) == 1 and flash.name == FLASH_OLD_NAME and close(flash.product_uom_qty * 100, FLASH_QTY * 100)
    check('flashing_expected_before', split_done or single, [(l.name, l.product_uom_qty, l.price_unit) for l in flash])
    check('flashing_price', all(close(l.price_unit, FLASH_PRICE) for l in flash), flash.mapped('price_unit'))
    if single and not split_done:
        taxes, seq = flash.tax_ids, flash.sequence
        (name_58, qty_58), (name_20, qty_20) = FLASH_LINES
        # every later line moves one step down, so the second flashing line sits right after the first
        for line in ref.order_line.filtered(lambda l: l.sequence > seq).sorted(lambda l: (-l.sequence, -l.id)):
            line.sequence += 1
        flash.write({'name': name_58, 'product_uom_qty': qty_58})
        flash.price_unit = FLASH_PRICE          # a quantity change re-prices a create-time price from the product
        second = env['sale.order.line'].create({'order_id': ref.id, 'product_id': flash.product_id.id,
                                                'product_uom_qty': qty_20, 'product_uom_id': flash.product_uom_id.id,
                                                'name': name_20, 'sequence': seq + 1})
        second.price_unit = FLASH_PRICE         # written after create: a manual price (Odoo 19 technical_price_unit)
        check('flashing_second_line_taxes', second.tax_ids == taxes, [second.tax_ids.ids, taxes.ids])
        changed('SI-26/2546 flashing split 2:1')
    flash = ref.order_line.filtered(lambda l: not l.display_type and l.product_id.default_code == FLASH_CODE)
    check('flashing_split', sorted((l.name, l.product_uom_qty, l.price_unit) for l in flash)
          == sorted((n, q, float(FLASH_PRICE)) for n, q in FLASH_LINES)
          and close(sum(flash.mapped('price_subtotal')), FLASH_PRICE * FLASH_QTY), [(l.name, l.price_subtotal) for l in flash])

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

    # ---- after
    ordered = ref.order_line.sorted(lambda l: (l.sequence, l.id))
    shop_lines = ref._sipanel_managed_lines('shop_drawing')
    shop_line = shop_lines.filtered(lambda l: not l.display_type)
    inst_line = ref._sipanel_managed_lines('installation').filtered(lambda l: not l.display_type)
    R['after'] = {'totals': totals(ref), 'lines': [(l.sequence, l.display_type or l.product_id.default_code, l.name,
                                                    l.product_uom_qty, l.price_unit, l.discount, l.price_subtotal,
                                                    l.price_tax, l.sipanel_managed_role) for l in ordered]}
    check('si26_2546_totals_unchanged', close(ref.amount_untaxed, UNTAXED) and close(ref.amount_tax, TAX)
          and close(ref.amount_total, TOTAL), totals(ref))
    check('installation_unchanged', len(inst_line) == 1 and close(inst_line.price_subtotal, INSTALL_10))
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
    printed = ref.with_context(lang='fa_IR')._sipanel_tech_sheet_rows()
    R['printed_rows_fa'] = printed
    check('row2_prints_0_7_fa', len(printed) >= 2 and 'ضخامت ۰.۷ میلیمتر' in printed[1][2], printed[1:2])
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
