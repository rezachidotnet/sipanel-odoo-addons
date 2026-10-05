# -*- coding: utf-8 -*-
"""Quotation lines (work order 2026-10-05) - acceptance + PDF evidence on a CLONE database (never on sipanel).
Run: docker exec -i -e PHASE=pre|post -e OUT=/tmp/qlines odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d <clone> --no-http < this

PHASE=pre : SI-26/2546 as restored (module not installed): totals + fa_IR / en_US PDFs.
PHASE=post: (module installed) SI-26/2546 unchanged; product / System inventory; then, inside ONE rolled-back
            savepoint: old-version refusal (B3), the Standing Seam v3 creation (scripts/sipanel_standing_seam_v3.py),
            the synthetic copy of SI-26/2546 on the NEW scope version at 40 % and 10 %, crane exclusion, recompute,
            Scope regeneration, costing exclusion, frozen after confirmation, amount in words, PDFs.
The script ends with a rollback: the clone keeps exactly what was restored + the installed module.
"""
import json
import os
import traceback

from odoo.exceptions import UserError

PHASE = os.environ.get('PHASE', 'post')
OUT = os.environ.get('OUT', '/tmp/qlines')
os.makedirs(OUT, exist_ok=True)
assert env.cr.dbname != 'sipanel', 'refusing to run on the Production database'
Report = env['ir.actions.report']
summary = {'db': env.cr.dbname, 'phase': PHASE, 'checks': {}}
WORDS_27 = 'بیست و هفت میلیارد و سیصد و پنجاه و دو میلیون و سیصد و هشتاد هزار ریال'
WORDS_38 = 'سی و هشت میلیارد و دویست و نود و سه میلیون و سیصد و سی و دو هزار ریال'


def check(name, ok, detail=None):
    summary['checks'][name] = {'ok': bool(ok), 'detail': detail}


def norm(s):
    return ' '.join((s or '').split())


def render(order, tag, lang=None):
    if lang:
        order.partner_id.lang = lang
    pdf, _ = Report._render_qweb_pdf('sale.report_saleorder', order.ids)
    path = os.path.join(OUT, f'{PHASE}_{tag}.pdf')
    with open(path, 'wb') as f:
        f.write(pdf)
    return path


def commercial(order):
    return {
        'state': order.state,
        'lines': [(l.sequence, l.display_type or l.product_id.default_code, norm(l.name)[:70], l.product_uom_qty,
                   l.price_unit, l.price_subtotal, l.tax_ids.mapped('name'),
                   getattr(l, 'sipanel_is_installation_line', None)) for l in order.order_line.sorted(lambda l: (l.sequence, l.id))],
        'untaxed': order.amount_untaxed, 'tax': order.amount_tax, 'total': order.amount_total,
    }


def close(a, b):
    return abs((a or 0.0) - b) < 0.5


ref = env['sale.order'].search([('name', '=', 'SI-26/2546')])
assert len(ref) == 1, 'SI-26/2546 not found exactly once'
ref_lang = ref.partner_id.lang
summary['si26_2546'] = commercial(ref)
check('si26_2546_totals_unchanged', close(ref.amount_untaxed, 24865800000) and close(ref.amount_tax, 2486580000)
      and close(ref.amount_total, 27352380000), [ref.amount_untaxed, ref.amount_tax, ref.amount_total])

with env.cr.savepoint(flush=True):
    for lang in ('fa_IR', 'en_US'):
        summary['si26_2546'][f'pdf_{lang}'] = render(ref, f'SI-26-2546_{lang}', lang)
    ref.partner_id.lang = ref_lang
env.cr.rollback()

if PHASE == 'post':
    installed = env['ir.module.module'].search([('name', '=', 'sipanel_quotation_lines')]).state
    check('module_installed', installed == 'installed', installed)
    check('si26_2546_no_installation', ref.sipanel_installation_pct == 0
          and not ref.order_line.filtered('sipanel_is_installation_line'),
          [ref.sipanel_installation_pct, len(ref.order_line.filtered('sipanel_is_installation_line'))])
    check('si26_2546_words_fa', norm(ref.with_context(lang='fa_IR')._sipanel_amount_total_in_words()) == WORDS_27,
          ref.with_context(lang='fa_IR')._sipanel_amount_total_in_words())
    summary['si26_2546_words_en'] = ref.with_context(lang='en_US')._sipanel_amount_total_in_words()
    # ---------------- inventory: products used on quotation lines (B1 flag, A description_sale)
    used = env['sale.order.line'].search([('display_type', '=', False), ('product_id', '!=', False)]).mapped('product_id')
    env.cr.execute("SELECT id, description_sale FROM product_template WHERE id = ANY(%s)", [used.product_tmpl_id.ids])
    stored = dict(env.cr.fetchall())                      # raw jsonb: no language fallback
    inventory = []
    for p in used.sorted(lambda p: (p.default_code or 'zz', p.id)):
        terms = stored.get(p.product_tmpl_id.id) or {}
        inventory.append({'product_id': p.id, 'code': p.default_code, 'name_en': p.with_context(lang='en_US').name,
                          'name_fa': p.with_context(lang='fa_IR').name, 'active': p.active, 'type': p.type,
                          'installation_base': p.sipanel_installation_base,
                          'desc_en': bool((terms.get('en_US') or '').strip()), 'desc_fa': bool((terms.get('fa_IR') or '').strip())})
    summary['products_on_quotation_lines'] = inventory
    flagged = sorted(env['product.template'].with_context(active_test=False).search(
        [('sipanel_installation_base', '=', True)]).mapped(lambda t: t.default_code or str(t.id)))
    check('b1_flags_exactly_074_076_077', flagged == ['SIP-000074', 'SIP-000076', 'SIP-000077'], flagged)
    plan = env['sipanel.config'].resolve_system_plan()
    systems = env['account.analytic.account'].with_context(active_test=False).search([('plan_id', '=', plan.id)])
    summary['systems'] = [(s.id, s.name, s.active, s.sipanel_installation_product_id.default_code) for s in systems]
    seam = systems.filtered(lambda s: s.with_context(lang='en_US').name == 'Standing Seam' and s.active)
    check('b2_standing_seam_maps_sip_000075', len(seam) == 1 and seam.sipanel_installation_product_id.default_code == 'SIP-000075',
          summary['systems'])
    install = seam.sipanel_installation_product_id
    summary['sip_000075'] = {'type': install.type, 'sale_ok': install.sale_ok, 'uom': install.uom_id.name,
                             'taxes': install.taxes_id.mapped('name'), 'list_price': install.list_price,
                             'service_tracking': getattr(install, 'service_tracking', None),
                             'invoice_policy': install.invoice_policy, 'installation_base': install.sipanel_installation_base}
    company = ref.company_id
    summary['company_default_pct'] = company.sipanel_installation_pct_default
    Scope = env['sipanel.scope']
    roof_scope = Scope.search([('code', '=', 'CS-STANDING-SEAM')])
    flash_v = Scope.search([('code', '=', 'CS-STANDING-SEAM-FLASHING')]).current_version_id
    gut_v = Scope.search([('code', '=', 'CS-STANDING-SEAM-GUTTER')]).current_version_id
    QS = env['sipanel.quote.scope']

    def fixture(version_roof, lang):
        """Synthetic copy of SI-26/2546 with Commercial Scopes (Roof / Flashing / Gutter)."""
        order = env['sale.order'].create({
            'partner_id': ref.partner_id.id, 'pricelist_id': ref.pricelist_id.id, 'origin': 'SIPANEL-QLINES-ACCEPTANCE',
            'sipanel_project_name': ref.sipanel_project_name, 'sipanel_requested_system_id': seam.id,
            'partner_shipping_id': ref.partner_shipping_id.id, 'fiscal_position_id': ref.fiscal_position_id.id})
        order.partner_id.lang = lang
        Line = env['sale.order.line']
        Line.create({'order_id': order.id, 'display_type': 'line_section', 'name': 'Standing Seam Roof System', 'sequence': 1})
        for version, code, seq in ((version_roof, 'SIP-000074', 20), (flash_v, 'SIP-000076', 50), (gut_v, 'SIP-000077', 60)):
            src = ref.order_line.filtered(lambda l: l.product_id.default_code == code)
            uom = src.product_uom_id if src.product_uom_id == version.base_uom_id else version.base_uom_id
            scope = QS._create_from_version(order, version, src.product_uom_qty, uom, system=seam, sequence=seq)
            scope.anchor_line_id.write({'price_unit': src.price_unit})
            if seq == 20:
                Line.create({'order_id': order.id, 'display_type': 'line_section', 'name': 'Accessories', 'sequence': 40})
        return order

    def inst_line(order):
        return order.order_line.filtered(lambda l: l.sipanel_is_installation_line and not l.display_type)

    def is_last(order):
        ordered = order.order_line.sorted(lambda l: (l.sequence, l.id))
        return bool(ordered) and ordered[-1] == inst_line(order) and ordered[-2].display_type == 'line_section' \
            and ordered[-2].sipanel_is_installation_line

    try:
        with env.cr.savepoint(flush=True):
            # ---------------- B3: an order on the OLD released version refuses a percentage
            old_v = roof_scope.current_version_id
            summary['old_version'] = {'name': old_v.name, 'install_lines': [
                (l.sequence, l.placement) for l in old_v.recipe_line_ids if l.product_id == install]}
            old = fixture(old_v, 'fa_IR')
            try:
                with env.cr.savepoint():
                    old.sipanel_installation_pct = 40.0
                check('b3_old_version_refused', False, 'no error')
            except UserError as exc:
                check('b3_old_version_refused', 'twice' in str(exc) or 'دو بار' in str(exc), str(exc))
            check('b3_old_version_no_line', not old.order_line.filtered('sipanel_is_installation_line'))
            # ---------------- Standing Seam v3 (the corrected commercial model)
            v3ns = {'SIPANEL_V3_LIBRARY': True}
            # first without a corrected description: the customer-text gate must refuse (nothing created)
            os.environ.pop('SIPANEL_V3_DESCRIPTION_EN', None)
            exec(open(os.environ.get('V3_SCRIPT', '/tmp/qlines_src/sipanel_standing_seam_v3.py')).read(), v3ns)
            gate = v3ns['create_standing_seam_v3'](env)
            check('v3_description_gate_blocks', gate.get('result') == 'BLOCKED_CUSTOMER_DESCRIPTION'
                  and roof_scope.current_version_id == old_v, gate)
            # then with the PROPOSED text (clone only; the owner approves the real wording)
            os.environ['SIPANEL_V3_DESCRIPTION_EN'] = v3ns['PROPOSED_DESCRIPTION_EN']
            summary['standing_seam_v3'] = v3ns['create_standing_seam_v3'](env)
            new_v = roof_scope.current_version_id
            check('v3_released_v2_preserved', summary['standing_seam_v3'].get('result') == 'RELEASED'
                  and summary['standing_seam_v3'].get('previous_checksum_unchanged')
                  and summary['standing_seam_v3'].get('previous_checksum_verified_after')
                  and summary['standing_seam_v3'].get('previous_lines_after') == summary['standing_seam_v3'].get('previous_lines'),
                  summary['standing_seam_v3'])
            check('v3_has_no_installation_line', not new_v.recipe_line_ids.filtered(lambda l: l.product_id == install))
            # ---------------- synthetic copy on the NEW version
            for lang in ('fa_IR', 'en_US'):
                so = fixture(new_v, lang)
                supply = sum(so.order_line.filtered(lambda l: l.product_id.sipanel_installation_base).mapped('price_subtotal'))
                check(f'{lang}_supply_24865800000', close(supply, 24865800000) and close(so.amount_untaxed, 24865800000),
                      [supply, so.amount_untaxed])
                check(f'{lang}_pct0_no_line', so.sipanel_installation_pct == 0 and not so.order_line.filtered('sipanel_is_installation_line'))
                summary[f'synthetic_{lang}_no_install'] = dict(commercial(so), pdf=render(so, f'synthetic_{lang}_no_install'))
                so.sipanel_installation_pct = 40.0
                il = inst_line(so)
                check(f'{lang}_40pct_values', len(il) == 1 and il.product_id == install and il.product_uom_qty == 1
                      and close(il.price_unit, 9946320000) and close(so.amount_untaxed, 34812120000)
                      and close(so.amount_tax, 3481212000) and close(so.amount_total, 38293332000),
                      [il.price_unit, so.amount_untaxed, so.amount_tax, so.amount_total, il.tax_ids.mapped('name')])
                check(f'{lang}_40pct_last', is_last(so))
                expected = 'نصب و اجرا (40٪ مبلغ اقلام)' if lang == 'fa_IR' else 'Installation & Execution (40% of item subtotal)'
                check(f'{lang}_40pct_label', inst_line(so).name.split('\n')[0] == expected, inst_line(so).name)
                words = norm(so.with_context(lang=lang)._sipanel_amount_total_in_words())
                if lang == 'fa_IR':
                    check('fa_words_38293332000', words == WORDS_38, words)
                else:
                    summary['en_words_38293332000'] = words
                summary[f'synthetic_{lang}_install40'] = dict(commercial(so), pdf=render(so, f'synthetic_{lang}_install40'))
                if lang == 'en_US':
                    continue
                # crane line (not flagged) leaves the amount unchanged
                crane = env['product.product'].search([('default_code', '=', 'SIP-000031')])
                env['sale.order.line'].create({'order_id': so.id, 'product_id': crane.id, 'product_uom_qty': 1.0,
                                               'price_unit': 500000000.0, 'sequence': 70})
                check('crane_not_in_base', close(inst_line(so).price_unit, 9946320000) and is_last(so),
                      [inst_line(so).price_unit, is_last(so)])
                # quantity change recomputes (draft)
                gutter = so.order_line.filtered(lambda l: l.product_id.default_code == 'SIP-000077')
                gutter.product_uom_qty = 28.0
                check('qty_change_recomputes', close(inst_line(so).price_unit, 10214320000), inst_line(so).price_unit)
                gutter.product_uom_qty = 18.0
                # Scope regeneration: projections resynced, notes regenerated
                revs = so.sipanel_quote_scope_ids.mapped('current_revision_id')
                cost_before = [r.sudo().eligible_cost_total for r in revs]
                for r in revs:
                    r._sync_separately_billable_lines()
                    r.action_generate_note()
                check('scope_regeneration_keeps_single_last_line', is_last(so) and len(so.order_line.filtered('sipanel_is_installation_line')) == 2)
                comps = revs.sudo().mapped('component_ids')
                check('not_a_scope_component', install not in comps.mapped('product_id')
                      and not inst_line(so).sipanel_quote_scope_id and not inst_line(so).sipanel_is_generated)
                revs.invalidate_recordset()
                check('scope_costing_base_unchanged', [r.sudo().eligible_cost_total for r in revs] == cost_before, cost_before)
                # 10 % (the first-version acceptance values)
                so.order_line.filtered(lambda l: l.product_id == crane).unlink()
                so.sipanel_installation_pct = 10.0
                check('10pct_values', close(inst_line(so).price_unit, 2486580000) and close(so.amount_untaxed, 27352380000),
                      [inst_line(so).price_unit, so.amount_untaxed, so.amount_tax, so.amount_total])
            # ---------------- frozen after confirmation: synthetic copy of SI-26/2546 (manual lines, no Scope)
            cp = ref.copy({'sipanel_requested_system_id': seam.id, 'origin': 'SIPANEL-QLINES-ACCEPTANCE'})
            cp.sipanel_installation_pct = 40.0
            check('copy_40pct', close(inst_line(cp).price_unit, 9946320000) and close(cp.amount_total, 38293332000),
                  commercial(cp))
            cp.action_confirm()
            roof = cp.order_line.filtered(lambda l: l.product_id.default_code == 'SIP-000074')
            roof.product_uom_qty = 300.0
            check('confirmed_frozen', cp.state == 'sale' and close(inst_line(cp).price_unit, 9946320000),
                  [cp.state, inst_line(cp).price_unit])
            try:
                with env.cr.savepoint():
                    cp.sipanel_installation_pct = 50.0
                check('confirmed_pct_write_refused', False)
            except UserError as exc:
                check('confirmed_pct_write_refused', True, str(exc))
            # ---------------- A: description_sale under the title (synthetic placeholder text, rolled back)
            roof_t = env['product.product'].search([('default_code', '=', 'SIP-000074')]).product_tmpl_id
            roof_t.update_field_translations('description_sale', {
                'en_US': '[synthetic test description line 1]\n[synthetic test description line 2]',
                'fa_IR': '[شرح آزمایشی ۱]\n[شرح آزمایشی ۲]'})
            for lang in ('fa_IR', 'en_US'):
                d = env['sale.order'].create({'partner_id': ref.partner_id.id, 'pricelist_id': ref.pricelist_id.id,
                                              'sipanel_requested_system_id': seam.id})
                d.partner_id.lang = lang
                line = env['sale.order.line'].create({'order_id': d.id, 'product_id': roof_t.product_variant_id.id,
                                                      'product_uom_qty': 206.0, 'price_unit': 88000000.0})
                check(f'desc_native_{lang}', len(line.name.split('\n')) == 3, line.name)
                summary[f'desc_{lang}'] = {'name': line.name, 'pdf': render(d, f'description_{lang}')}
            raise RuntimeError('ROLLBACK')
    except RuntimeError as exc:
        if str(exc) != 'ROLLBACK':
            raise
    except Exception:
        summary['error'] = traceback.format_exc()
env.cr.rollback()
summary['all_ok'] = all(c['ok'] for c in summary['checks'].values()) and 'error' not in summary
with open(os.path.join(OUT, f'{PHASE}_summary.json'), 'w') as f:
    json.dump(summary, f, ensure_ascii=False, indent=1, default=str)
print('QLINES_' + PHASE.upper() + ' ' + json.dumps({'all_ok': summary['all_ok'], 'failed': [k for k, c in summary['checks'].items() if not c['ok']],
                                                    'error': summary.get('error', '')[-600:]}, ensure_ascii=False))
