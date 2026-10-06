# -*- coding: utf-8 -*-
"""Standing Seam supply-only rehearsal (business decision 2026-10-06) - CLONE ONLY, COMMITS on the clone.

Run: docker exec -i -e OUT=/tmp/qlines -e V3_SCRIPT=... odoo-sipanel odoo shell -c ... -d <clone> --no-http < this
(scripts/sipanel_qlines_clone_validate.sh rehearsal). Refuses any database that is not a neutralized
sipanel_qlines_clone_* database.

1. BEFORE  - what the installation-work component of the Standing Seam versions feeds today: recipes, every
             quotation Scope made on them (cost / margin / installation-work components), execution demands;
             SIP-000075 as a product (what confirming an order line of it creates natively); SI-26/2546 structure.
2. v3      - releases the next version of Roof / Flashing / Gutter (supply-only wording, installation work removed)
             through scripts/sipanel_standing_seam_v3.py; previous versions SUPERSEDED; no release warning.
3. A       - SI-26/2546 itself (manual lines from the native template, no Scope): installation 10 %.
             Confirmation is rehearsed inside a rolled-back savepoint: what the installation line creates.
4. B       - a copy of SI-26/2546 rebuilt on the v3 Scopes (same quantities and prices), installation 10 %.
PDFs (fa_IR / en_US) for A and B. Everything is committed on the clone only.
"""
import json
import os
import traceback

from odoo.exceptions import UserError, ValidationError

OUT = os.environ.get('OUT', '/tmp/qlines')
os.makedirs(OUT, exist_ok=True)
DB = env.cr.dbname
assert DB.startswith('sipanel_qlines_clone_'), f'refusing: {DB} is not a sipanel_qlines_clone_* database'
assert (env['ir.config_parameter'].sudo().get_param('database.is_neutralized') or '').lower() == 'true', \
    f'refusing: {DB} is not neutralized'
env = env(su=True)
R = {'db': DB, 'checks': {}}
SUPPLY, INSTALL_10, UNTAXED, TAX, TOTAL = 24_865_800_000, 2_486_580_000, 27_352_380_000, 2_735_238_000, 30_087_618_000


def check(name, ok, detail=None):
    R['checks'][name] = {'ok': bool(ok), 'detail': detail}


def close(a, b):
    return abs((a or 0.0) - b) < 0.5


def opt(record, field):
    return record[field] if field in record._fields else '<field not installed>'


def render(order, tag):
    lang0 = order.partner_id.lang
    paths = {}
    for lang in ('fa_IR', 'en_US'):
        order.partner_id.lang = lang
        pdf, _ = env['ir.actions.report']._render_qweb_pdf('sale.report_saleorder', order.ids)
        paths[lang] = os.path.join(OUT, f'rehearsal_{tag}_{lang}.pdf')
        with open(paths[lang], 'wb') as f:
            f.write(pdf)
    order.partner_id.lang = lang0
    return paths


def lines_of(order):
    return [(l.sequence, l.display_type or l.product_id.default_code, ' '.join((l.name or '').split())[:60],
             l.product_uom_qty, l.product_uom_id.name, l.price_unit, l.price_subtotal,
             l.sipanel_is_installation_line, bool(l.sipanel_quote_scope_id))
            for l in order.order_line.sorted(lambda l: (l.sequence, l.id))]


def totals(order):
    return {'untaxed': order.amount_untaxed, 'tax': order.amount_tax, 'total': order.amount_total,
            'pct': order.sipanel_installation_pct, 'installation_amount': order.sipanel_installation_amount}


v3ns = {'SIPANEL_V3_LIBRARY': True}
exec(open(os.environ.get('V3_SCRIPT', '/tmp/qlines_src/sipanel_standing_seam_v3.py')).read(), v3ns)
Scope, QS = env['sipanel.scope'], env['sipanel.quote.scope'].with_context(active_test=False)
Demand = env['sipanel.execution.demand'] if 'sipanel.execution.demand' in env else None
install = env['product.product'].with_context(active_test=False).search([('default_code', '=', v3ns['INSTALL_CODE'])])
work = env['product.product']._sipanel_installation_work_products() | install
scopes = Scope.search([('code', 'in', list(v3ns['SCOPE_CODES']))])
ref = env['sale.order'].search([('name', '=', 'SI-26/2546')])
assert len(ref) == 1 and len(scopes) == 3 and len(install) == 1

try:
    # ------------------------------------------------------------------ 1. BEFORE
    before = R['before'] = {'versions': {}, 'quote_scopes': [], 'demands': []}
    for sc in scopes:
        for v in sc.version_ids.sorted('id'):
            issues = [i for i in v._release_validations() if i['rule'] in ('QL1', 'QL2')]
            before['versions'][v.name] = {
                'state': v.state, 'anchor': v.anchor_product_id.default_code,
                'anchor_in_installation_base': v.anchor_product_id.product_tmpl_id.sipanel_installation_base,
                'label': v3ns['_stored_terms'](env, v, 'customer_label'),
                'description': v3ns['_stored_terms'](env, v, 'customer_description'),
                'ql_rules_if_released_today': issues,
                'recipe': [{'seq': l.sequence, 'product': l.product_id.default_code, 'placement': l.placement,
                            'responsibility': l.responsibility, 'execution_mode': l.execution_mode, 'basis': l.basis,
                            'cost_policy': l.cost_policy, 'manual_qty_default': l.manual_qty_default,
                            'manual_cost_default': l.manual_cost_default, 'activity': l.activity_id.name,
                            'customer_eligible': l.customer_eligible, 'installation_work': l.product_id in work}
                           for l in v.recipe_line_ids.sorted('sequence')]}
    for qs in QS.search([('source_scope_id', 'in', scopes.ids)]):
        rev = qs.current_revision_id
        comps = rev.component_ids.filtered(lambda c: c.product_id in work)
        before['quote_scopes'].append({
            'order': qs.order_id.name, 'order_state': qs.order_id.state, 'scope': qs.source_scope_id.code,
            'version': qs.source_version_id.name, 'active': qs.active, 'revision': rev.display_name,
            'revision_state': rev.state, 'net_revenue_projection': rev.net_revenue_projection,
            'eligible_cost_total': rev.eligible_cost_total, 'margin_amount': rev.margin_amount,
            'margin_percent': rev.margin_percent, 'missing_cost_count': rev.missing_cost_count,
            'installation_work_components': [{
                'product': c.product_id.default_code, 'active_state': c.active_state, 'placement': c.placement,
                'execution_mode': c.execution_mode, 'final_qty': c.final_qty, 'unit_cost': c.unit_cost,
                'cost_amount': c.cost_amount, 'eligible_for_rollup': c.eligible_for_rollup,
                'sell_amount': c.sell_amount} for c in comps]})
        if Demand is not None:
            for d in Demand.search([('quote_scope_id', '=', qs.id)]):
                before['demands'].append({'order': qs.order_id.name, 'component': d.component_id.display_name,
                                          'product': d.product_id.default_code, 'mode': d.execution_mode,
                                          'state': d.state, 'installation_work': d.product_id in work})
    tmpl = install.product_tmpl_id
    R['sip_000075'] = {f: str(opt(tmpl, f)) for f in (
        'type', 'service_tracking', 'invoice_policy', 'service_to_purchase', 'expense_policy', 'project_id',
        'project_template_id', 'sipanel_installation_base', 'sipanel_installation_work')}
    R['sip_000075'].update({'taxes': tmpl.taxes_id.mapped('name'), 'uom': tmpl.uom_id.name,
                            'routes': tmpl.route_ids.mapped('name') if 'route_ids' in tmpl._fields else [],
                            'vendors': len(tmpl.seller_ids) if 'seller_ids' in tmpl._fields else '<n/a>'})
    R['si26_2546_before'] = {'state': ref.state, 'lines': lines_of(ref), 'totals': totals(ref),
                             'quote_scopes': len(ref.sipanel_quote_scope_ids)}
    check('si26_2546_has_no_scope', not ref.sipanel_quote_scope_ids, len(ref.sipanel_quote_scope_ids))
    check('si26_2546_supply_unchanged', close(ref.amount_untaxed, SUPPLY), totals(ref))

    # ------------------------------------------------------------------ 2. v3 release (supply only)
    v3 = R['v3'] = v3ns['create_standing_seam_v3'](env, v3ns['APPROVED_WORDING'])
    check('v3_released', v3.get('result') == 'RELEASED', v3.get('result'))
    for code in v3ns['SCOPE_CODES']:
        r = v3['scopes'].get(code, {})
        sc = scopes.filtered(lambda s: s.code == code)
        check(f'{code}_no_release_warning', r.get('result') in ('RELEASED', 'ALREADY_CORRECTED')
              and not r.get('release_warnings'), r.get('release_warnings'))
        if r.get('result') == 'RELEASED':
            check(f'{code}_previous_superseded', r.get('previous_state_after') == 'superseded'
                  and r.get('previous_checksum_unchanged'), r.get('previous_state_after'))
        check(f'{code}_current_has_no_installation_work',
              not sc.current_version_id.recipe_line_ids.filtered(lambda l: l.responsibility == 'sipanel'
                                                                  and l.product_id in work),
              sc.current_version_id.name)
    env.cr.commit()

    # ------------------------------------------------------------------ 3. A: SI-26/2546 itself, 10 %
    seam = env['account.analytic.account'].search([('name', '=', 'Standing Seam'), ('active', '=', True)])
    check('standing_seam_system_maps_sip_000075', len(seam) == 1 and seam.sipanel_installation_product_id == install,
          seam.mapped('name'))
    # the percentage needs the order's SIPANEL System (B2); SI-26/2546 has no Scope, so its Requested System
    R['A_requested_system_before'] = ref.sipanel_requested_system_id.name or None
    if not ref.sipanel_requested_system_id:
        ref.sipanel_requested_system_id = seam
    try:
        ref.sipanel_installation_pct = 10.0
        refused = None
    except UserError as exc:
        refused = str(exc)
    il = ref.order_line.filtered(lambda l: l.sipanel_is_installation_line and not l.display_type)
    ordered = ref.order_line.sorted(lambda l: (l.sequence, l.id))
    check('A_no_double_charge_refusal', refused is None, refused)
    check('A_installation_10pct', len(il) == 1 and close(il.price_unit, INSTALL_10) and il.product_id == install,
          [il.mapped('price_unit'), il.product_id.default_code])
    check('A_untaxed_27352380000', close(ref.amount_untaxed, UNTAXED), totals(ref))
    check('A_total_30087618000', close(ref.amount_tax, TAX) and close(ref.amount_total, TOTAL), totals(ref))
    check('A_installation_last', bool(il) and ordered[-1] == il)
    R['A'] = {'lines': lines_of(ref), 'totals': totals(ref),
              'words_fa': ref.with_context(lang='fa_IR')._sipanel_amount_total_in_words(),
              'words_en': ref.with_context(lang='en_US')._sipanel_amount_total_in_words(),
              'pdf': render(ref, 'A_SI-26-2546')}
    check('A_words_en_rials_only', R['A']['words_en'].endswith('Rials only'), R['A']['words_en'])
    env.cr.commit()
    # what confirming creates for the installation line (rolled back: SI-26/2546 stays a quotation)
    conf = R['A_confirmation_rehearsal'] = {}
    try:
        with env.cr.savepoint():
            ref.action_confirm()
            il = ref.order_line.filtered(lambda l: l.sipanel_is_installation_line and not l.display_type)
            conf.update({'state': ref.state, 'analytic_distribution': il.analytic_distribution,
                         'invoice_status': il.invoice_status, 'qty_to_invoice': il.qty_to_invoice})
            if Demand is not None:
                conf['sipanel_demands'] = Demand.search_count([('order_id', '=', ref.id)])
            if 'project.task' in env and 'sale_line_id' in env['project.task']._fields:
                conf['tasks_for_installation_line'] = env['project.task'].search_count([('sale_line_id', '=', il.id)])
            conf['projects'] = len(ref.project_ids) if 'project_ids' in ref._fields else '<n/a>'
            if 'purchase.order.line' in env and 'sale_line_id' in env['purchase.order.line']._fields:
                conf['purchase_lines_for_installation_line'] = env['purchase.order.line'].search_count(
                    [('sale_line_id', '=', il.id)])
            conf['pickings'] = len(ref.picking_ids) if 'picking_ids' in ref._fields else '<n/a>'
            raise ValidationError('ROLLBACK_CONFIRMATION_REHEARSAL')
    except (UserError, ValidationError) as exc:
        if str(exc) != 'ROLLBACK_CONFIRMATION_REHEARSAL':
            conf['confirmation_refused'] = str(exc)
    ref.invalidate_recordset()
    check('A_still_quotation_after_rehearsal', ref.state in ('draft', 'sent'), ref.state)

    # ------------------------------------------------------------------ 4. B: copy rebuilt on the v3 Scopes
    cp = ref.copy({'origin': 'SIPANEL-ROOFV3-REHEARSAL (copy of SI-26/2546)', 'sipanel_installation_pct': 0.0})
    by_anchor = {sc.current_version_id.anchor_product_id: sc.current_version_id for sc in scopes}
    rebuilt = []
    for line in cp.order_line.filtered(lambda l: not l.display_type and l.product_id in by_anchor).sorted('sequence'):
        version = by_anchor[line.product_id]
        qty, price, seq, uom = line.product_uom_qty, line.price_unit, line.sequence, line.product_uom_id
        uom = uom if uom == version.base_uom_id else version.base_uom_id
        line.unlink()
        qs = QS._create_from_version(cp, version, qty, uom, system=seam, sequence=seq)
        qs.anchor_line_id.write({'price_unit': price})
        rebuilt.append((version.name, qty, uom.name, price))
    try:
        cp.sipanel_installation_pct = 10.0
        refused_b = None
    except UserError as exc:
        refused_b = str(exc)
    ilb = cp.order_line.filtered(lambda l: l.sipanel_is_installation_line and not l.display_type)
    check('B_rebuilt_three_scopes_on_v3', len(rebuilt) == 3, rebuilt)
    check('B_no_double_charge_refusal', refused_b is None, refused_b)
    check('B_untaxed_27352380000', close(cp.amount_untaxed, UNTAXED) and len(ilb) == 1
          and close(ilb.price_unit, INSTALL_10), totals(cp))
    check('B_total_30087618000', close(cp.amount_total, TOTAL), totals(cp))
    R['B'] = {'order': cp.name, 'rebuilt': rebuilt, 'lines': lines_of(cp), 'totals': totals(cp),
              'pdf': render(cp, 'B_copy_on_v3')}
    env.cr.commit()
except Exception:
    R['error'] = traceback.format_exc()
    env.cr.rollback()

R['all_ok'] = all(c['ok'] for c in R['checks'].values()) and 'error' not in R
with open(os.path.join(OUT, 'rehearsal_summary.json'), 'w') as f:
    json.dump(R, f, ensure_ascii=False, indent=1, default=str)
print('QLINES_REHEARSAL ' + json.dumps({'all_ok': R['all_ok'], 'failed': [k for k, c in R['checks'].items() if not c['ok']],
                                        'error': R.get('error', '')[-600:]}, ensure_ascii=False))
