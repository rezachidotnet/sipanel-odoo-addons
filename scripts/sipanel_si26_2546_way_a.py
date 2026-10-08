# -*- coding: utf-8 -*-
"""Production step after the quotation-lines deployment (owner decisions 2026-10-06 / 2026-10-08):

  M4     SIP-000075 "Standing Seam Installation Service": unit of measure -> Units (approved).
  WAY A  SI-26/2546 (never sent, still a quotation): Installation % = 10 directly on it, no duplicate.
         Supply lines and prices are not touched; the engine adds the section + installation line last.

Run (odoo shell):
  docker exec -i [-e SIPANEL_WAY_A_COMMIT=1] odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d sipanel --no-http < this
Without SIPANEL_WAY_A_COMMIT=1 everything is rolled back (dry run). With it, the transaction is committed only
when EVERY check passes; otherwise it is rolled back and nothing changes. Idempotent: a second commit run finds
the unit already Units and the percentage already 10 and changes nothing.
Same checks as the clone rehearsal (scripts/roof_v3_rehearsal.py, section 3).
"""
import json
import os

from odoo.exceptions import UserError

SUPPLY, INSTALL_10, UNTAXED, TAX, TOTAL = 24_865_800_000, 2_486_580_000, 27_352_380_000, 2_735_238_000, 30_087_618_000
R = {'db': env.cr.dbname, 'checks': {}}
env = env(su=True)


def check(name, ok, detail=None):
    R['checks'][name] = {'ok': bool(ok), 'detail': detail}


def close(a, b):
    return abs((a or 0.0) - b) < 0.5


def totals(order):
    return {'untaxed': order.amount_untaxed, 'tax': order.amount_tax, 'total': order.amount_total,
            'pct': order.sipanel_installation_pct, 'installation_amount': order.sipanel_installation_amount}


def supply_lines(order):
    return [(l.id, l.product_id.default_code, l.product_uom_qty, l.product_uom_id.id, l.price_unit, l.price_subtotal)
            for l in order.order_line.filtered(lambda l: not l.display_type and not l.sipanel_is_installation_line)
            .sorted('id')]


install = env['product.product'].with_context(active_test=False).search([('default_code', '=', 'SIP-000075')])
unit = env.ref('uom.product_uom_unit')
ref = env['sale.order'].search([('name', '=', 'SI-26/2546')])
assert len(install) == 1 and len(ref) == 1, (len(install), len(ref))
assert 'sipanel_installation_pct' in ref._fields, 'sipanel_quotation_lines is not installed'

# ---- preconditions
msgs = env['mail.message'].search([('model', '=', 'sale.order'), ('res_id', '=', ref.id)])
sent = msgs.filtered(lambda m: m.message_type == 'email'
                     or (m.subtype_id == env.ref('mail.mt_comment') and m.partner_ids))
check('si26_2546_quotation_not_sent', ref.state == 'draft' and not sent, [ref.state, len(sent)])
check('si26_2546_has_no_scope', not ref.sipanel_quote_scope_ids, len(ref.sipanel_quote_scope_ids))
already = close(ref.sipanel_installation_pct, 10.0)
check('si26_2546_supply_before', close(ref.amount_untaxed, UNTAXED if already else SUPPLY), totals(ref))
R['before'] = {'totals': totals(ref), 'uom': install.uom_id.name, 'write_date': str(ref.write_date),
               'requested_system': ref.sipanel_requested_system_id.name or None}
supply0 = supply_lines(ref)

# ---- M4
tmpl = install.product_tmpl_id
if tmpl.uom_id != unit:
    tmpl.write({'uom_id': unit.id})
check('M4_sip_000075_in_units', tmpl.uom_id == unit, tmpl.uom_id.name)

# ---- WAY A
seam = env['account.analytic.account'].with_context(lang='en_US').search(
    [('name', '=', 'Standing Seam'), ('active', '=', True)])
check('standing_seam_system_maps_sip_000075', len(seam) == 1 and seam.sipanel_installation_product_id == install,
      seam.mapped('id'))
if not ref.sipanel_requested_system_id and len(seam) == 1:
    ref.sipanel_requested_system_id = seam
refused = None
if not already:
    try:
        ref.sipanel_installation_pct = 10.0
    except UserError as exc:
        refused = str(exc)
ref.invalidate_recordset()
il = ref.order_line.filtered(lambda l: l.sipanel_is_installation_line and not l.display_type)
ordered = ref.order_line.sorted(lambda l: (l.sequence, l.id))
check('A_no_double_charge_refusal', refused is None, refused)
check('A_installation_10pct', len(il) == 1 and close(il.price_unit, INSTALL_10) and il.product_id == install,
      [il.mapped('price_unit'), il.product_id.default_code])
check('A_installation_qty_1_units', len(il) == 1 and il.product_uom_qty == 1.0 and il.product_uom_id == unit,
      [il.mapped('product_uom_qty'), il.product_uom_id.name])
check('A_installation_last', bool(il) and ordered[-1] == il)
check('A_untaxed_27352380000', close(ref.amount_untaxed, UNTAXED), totals(ref))
check('A_total_30087618000', close(ref.amount_tax, TAX) and close(ref.amount_total, TOTAL), totals(ref))
check('A_supply_lines_unchanged', supply_lines(ref) == supply0)
R['after'] = {'totals': totals(ref), 'state': ref.state,
              'words_en': ref.with_context(lang='en_US')._sipanel_amount_total_in_words(),
              'words_fa': ref.with_context(lang='fa_IR')._sipanel_amount_total_in_words(),
              'installation_line': [(l.sequence, l.name, l.product_uom_qty, l.product_uom_id.name, l.price_unit)
                                    for l in il]}
check('A_words_en_rials_only', R['after']['words_en'].endswith('Rials only'), R['after']['words_en'])

R['all_ok'] = all(c['ok'] for c in R['checks'].values())
print('SIPANEL_WAY_A ' + json.dumps(R, ensure_ascii=False, default=str))
if os.environ.get('SIPANEL_WAY_A_COMMIT') == '1' and R['all_ok']:
    env.cr.commit()
    print('SIPANEL_WAY_A COMMITTED')
else:
    env.cr.rollback()
    print('SIPANEL_WAY_A ROLLED_BACK' + ('' if R['all_ok'] else ' (checks failed: '
          + ', '.join(k for k, c in R['checks'].items() if not c['ok']) + ')'))
