# -*- coding: utf-8 -*-
"""UI acceptance re-test (owner 2026-10-17): READ-ONLY check of the quotations the salesperson made in the web UI
(CLONE ONLY; everything is rolled back). Run by `sipanel_qlines_clone_validate.sh uirun` after the browser.

The quotations are compared with SI-26/2546 as the Production data steps leave it: same products, same native
descriptions (product name in the customer's language + the material option line, nothing typed), same printed
titles, quantities, prices and totals; the customer of the fa quotation got Persian by default (ir.default), the
validity is the quotation date + 8 days (company setting). Prints "SIPANEL_UI_VERIFY {json}".
"""
import datetime
import json

import pytz

assert env.cr.dbname.startswith('sipanel_qlines_clone_'), f'refused: {env.cr.dbname} is not a clone'
R = {'checks': {}}
su = env(su=True)
CUSTOMER_FA, CUSTOMER_EN = 'شرکت آزمون رابط کاربری', 'UI Test English Customer'
TEHRAN = pytz.timezone('Asia/Tehran')


def check(name, ok, detail=None):
    R['checks'][name] = {'ok': bool(ok), 'detail': detail}


def native(line):
    return line.with_context(lang=line.order_id._get_lang())._get_sale_order_line_multiline_description_sale()


def summary(order):
    supply = order.order_line.filtered(lambda l: not l.display_type and not l.sipanel_is_installation_line)
    return {'name': order.name, 'lang': order.partner_id.lang, 'state': order.state,
            'date_order': str(order.date_order), 'validity_date': str(order.validity_date),
            'totals': [order.amount_untaxed, order.amount_tax, order.amount_total],
            'supply': sorted((l.product_id.default_code, l.product_uom_qty, l.price_unit) for l in supply),
            'titles': [l._sipanel_report_name_lines() for l in supply.sorted(lambda l: (l.sequence, l.id))],
            'native_names': all(l.name == native(l) for l in supply),
            'managed': [(l.sipanel_managed_role, l.price_unit, l.discount, l.price_subtotal)
                        for l in order._sipanel_managed_lines('installation') | order._sipanel_managed_lines('shop_drawing')
                        if not l.display_type],
            'sheet_rows': len(order.sipanel_tech_spec_ids), 'liner': order.sipanel_liner_thickness,
            'material': sorted(set(supply.product_no_variant_attribute_value_ids.mapped(
                lambda p: p.product_attribute_value_id.with_context(lang='en_US').name))),
            'user': order.user_id.login}


try:
    user = su['res.users'].search([('login', '=', 'ui_sales')])
    ref = su['sale.order'].search([('name', '=', 'SI-26/2546')])
    R['SI-26/2546'] = summary(ref)
    for key, customer, lang in (('fa', CUSTOMER_FA, 'fa_IR'), ('en', CUSTOMER_EN, 'en_US')):
        orders = su['sale.order'].search([('partner_id.name', '=', customer), ('user_id', '=', user.id)],
                                         order='id desc')
        check(f'{key}_quotation_found', len(orders) >= 1, orders.mapped('name'))
        order = orders[:1]
        if not order:
            continue
        R[key] = summary(order)
        day = order.date_order.replace(tzinfo=pytz.utc).astimezone(TEHRAN).date()
        check(f'{key}_customer_language', order.partner_id.lang == lang, order.partner_id.lang)
        check(f'{key}_validity_8_days', order.validity_date == day + datetime.timedelta(days=8),
              [str(day), str(order.validity_date)])
        check(f'{key}_same_products_quantities_prices', R[key]['supply'] == R['SI-26/2546']['supply'],
              [R[key]['supply'], R['SI-26/2546']['supply']])
        check(f'{key}_native_descriptions', R[key]['native_names'])
        check(f'{key}_titles_one_line_product_name', all(len(t) == 1 for t in R[key]['titles']), R[key]['titles'])
        check(f'{key}_totals_as_si26_2546', all(abs(a - b) < 0.5 for a, b in zip(R[key]['totals'],
                                                                              R['SI-26/2546']['totals'])),
              [R[key]['totals'], R['SI-26/2546']['totals']])
        check(f'{key}_installation_shop_lines', R[key]['managed'] == R['SI-26/2546']['managed'],
              [R[key]['managed'], R['SI-26/2546']['managed']])
        check(f'{key}_material_galvanized', R[key]['material'] == ['Galvanized'], R[key]['material'])
        check(f'{key}_tech_sheet', R[key]['sheet_rows'] == 7 and R[key]['liner'] == '0.7',
              [R[key]['sheet_rows'], R[key]['liner']])
        expected = [[l.product_id.with_context(lang=lang).name] for l in order.order_line.filtered(
            lambda l: not l.display_type and not l.sipanel_is_installation_line).sorted(lambda l: (l.sequence, l.id))]
        check(f'{key}_titles_in_{lang}', R[key]['titles'] == expected, [R[key]['titles'], expected])
        check(f'{key}_still_a_draft', order.state == 'draft', order.state)
    if 'fa' in R:
        check('fa_titles_identical_to_si26_2546', R['fa']['titles'] == R['SI-26/2546']['titles'],
              [R['fa']['titles'], R['SI-26/2546']['titles']])
except Exception:                                    # noqa: BLE001 - reported
    import traceback
    R['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
R['all_ok'] = all(c['ok'] for c in R['checks'].values()) and 'error' not in R
print('SIPANEL_UI_VERIFY ' + json.dumps(R, ensure_ascii=False, default=str))
