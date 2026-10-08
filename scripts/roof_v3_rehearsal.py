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
   SENT    - whether SI-26/2546 was sent to the customer (state, e-mails, portal link, signature, printed PDFs).
   NATIVE  - installed modules / fields that could cover installation execution, cost and analytics natively.
   M4      - SIP-000075 unit of measure m² -> Units (master data, clone only), so the line prints "1.00 Units".
3. A       - directly on SI-26/2546 (owner decision 2026-10-08: never sent, no duplicate): installation 10 %,
             supply lines unchanged. Confirmation is rehearsed inside a rolled-back savepoint: what the
             installation line creates. (Way B was not chosen and is no longer rehearsed.)
PDFs (fa_IR / en_US) for A. Everything is committed on the clone only.
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
    # ---- SENT: was SI-26/2546 sent to the customer?
    msgs = env['mail.message'].search([('model', '=', 'sale.order'), ('res_id', '=', ref.id)], order='id')
    comment = env.ref('mail.mt_comment')
    sent_mails = msgs.filtered(lambda m: m.message_type == 'email' or (m.subtype_id == comment and m.partner_ids))
    atts = env['ir.attachment'].search([('res_model', '=', 'sale.order'), ('res_id', '=', ref.id)])
    R['si26_2546_sent_status'] = {
        'state': ref.state, 'date_order': str(ref.date_order), 'validity_date': str(ref.validity_date),
        'write_date': str(ref.write_date),
        'emails_or_partner_comments': [(str(m.date), m.message_type, m.subtype_id.name, m.author_id.name,
                                        m.partner_ids.mapped('name'), (m.subject or '')[:60]) for m in sent_mails],
        'all_messages': [(str(m.date), m.message_type, m.subtype_id.name, ' '.join((m.body or '').split())[:80])
                         for m in msgs],
        'portal_access_token': bool(opt(ref, 'access_token')) if 'access_token' in ref._fields else '<n/a>',
        'signed_by': opt(ref, 'signed_by') or None, 'signed_on': str(opt(ref, 'signed_on') or '') or None,
        'pdf_attachments': atts.filtered(lambda a: (a.mimetype or '').endswith('pdf')).mapped('name'),
    }
    R['si26_2546_sent_verdict'] = ('SENT' if ref.state == 'sent' or sent_mails else
                                   'NOT_SENT_IN_ODOO (no e-mail, state draft; a PDF printed and sent outside '
                                   'Odoo cannot be seen here)')
    # ---- NATIVE: what Odoo could cover without code (M1-M3)
    Mod = env['ir.module.module']
    R['native_capabilities'] = {
        'modules': {m: Mod.search([('name', '=', m)]).state or 'absent' for m in (
            'sale_project', 'project', 'sale_timesheet', 'hr_timesheet', 'sale_purchase', 'purchase',
            'sale_margin', 'sale_stock', 'account_budget', 'analytic')},
        'service_tracking_values': [v for v, _l in tmpl._fields['service_tracking'].selection]
        if 'service_tracking' in tmpl._fields and isinstance(tmpl._fields['service_tracking'].selection, list) else '<n/a>',
        'product_has_service_to_purchase': 'service_to_purchase' in tmpl._fields,
        'sale_line_has_purchase_price': 'purchase_price' in env['sale.order.line']._fields,
        'analytic_distribution_model': 'account.analytic.distribution.model' in env,
        'distribution_models_for_sip_000075': env['account.analytic.distribution.model'].search_count(
            ['|', ('product_id', '=', install.id), ('product_categ_id', '=', tmpl.categ_id.id)])
        if 'account.analytic.distribution.model' in env else '<n/a>',
        'sip_000075_standard_price': install.standard_price,
    }
    # ---- M4: SIP-000075 unit -> Units (master data; clone only)
    unit = env.ref('uom.product_uom_unit')
    R['M4'] = {'before': tmpl.uom_id.name}
    try:
        with env.cr.savepoint():
            tmpl.write({'uom_id': unit.id})
        R['M4']['after'] = tmpl.uom_id.name
    except Exception as exc:                                   # noqa: BLE001 - recorded, the rest goes on
        R['M4']['refused'] = str(exc)
    check('M4_sip_000075_in_units', tmpl.uom_id == unit, R['M4'])
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

    # ------------------------------------------------------------------ 3. A: directly on SI-26/2546, 10 %
    # Owner decision 2026-10-08: SI-26/2546 was never sent - way A is applied to it directly, no duplicate.
    check('si26_2546_not_sent', R['si26_2546_sent_verdict'].startswith('NOT_SENT'), R['si26_2546_sent_verdict'])
    check('si26_2546_is_quotation', ref.state == 'draft', ref.state)
    seam = env['account.analytic.account'].search([('name', '=', 'Standing Seam'), ('active', '=', True)])
    check('standing_seam_system_maps_sip_000075', len(seam) == 1 and seam.sipanel_installation_product_id == install,
          seam.mapped('name'))
    R['A_requested_system_before'] = ref.sipanel_requested_system_id.name or None
    supply_before = ref.order_line.filtered(lambda l: not l.display_type)
    supply_before = [(l.id, l.product_id.default_code, l.product_uom_qty, l.price_unit, l.price_subtotal)
                     for l in supply_before.sorted('id')]
    if not ref.sipanel_requested_system_id:
        ref.sipanel_requested_system_id = seam
    try:
        ref.sipanel_installation_pct = 10.0
        refused = None
    except UserError as exc:
        refused = str(exc)
    ref.invalidate_recordset()
    il = ref.order_line.filtered(lambda l: l.sipanel_is_installation_line and not l.display_type)
    ordered = ref.order_line.sorted(lambda l: (l.sequence, l.id))
    check('A_no_double_charge_refusal', refused is None, refused)
    check('A_installation_10pct', len(il) == 1 and close(il.price_unit, INSTALL_10) and il.product_id == install,
          [il.mapped('price_unit'), il.product_id.default_code])
    check('A_installation_qty_1', len(il) == 1 and il.product_uom_qty == 1.0, il.mapped('product_uom_qty'))
    check('A_installation_line_in_units', il.product_uom_id == unit, il.product_uom_id.name)
    check('A_untaxed_27352380000', close(ref.amount_untaxed, UNTAXED), totals(ref))
    check('A_total_30087618000', close(ref.amount_tax, TAX) and close(ref.amount_total, TOTAL), totals(ref))
    check('A_installation_last', bool(il) and ordered[-1] == il)
    supply_after = ref.order_line.filtered(lambda l: not l.display_type and not l.sipanel_is_installation_line)
    supply_after = [(l.id, l.product_id.default_code, l.product_uom_qty, l.price_unit, l.price_subtotal)
                    for l in supply_after.sorted('id')]
    check('A_supply_lines_unchanged', supply_after == supply_before, [supply_before, supply_after])
    R['A'] = {'order': ref.name, 'lines': lines_of(ref), 'totals': totals(ref),
              'unit_name': {lang: unit.with_context(lang=lang).name for lang in ('en_US', 'fa_IR')},
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
                         'invoice_status': il.invoice_status, 'qty_to_invoice': il.qty_to_invoice,
                         'purchase_price': opt(il, 'purchase_price')})
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
    check('A_still_quotation_after_rehearsal', ref.state == 'draft', ref.state)
    check('A_totals_after_rehearsal', close(ref.amount_untaxed, UNTAXED) and close(ref.amount_total, TOTAL),
          totals(ref))
except Exception:
    R['error'] = traceback.format_exc()
    env.cr.rollback()

R['all_ok'] = all(c['ok'] for c in R['checks'].values()) and 'error' not in R
with open(os.path.join(OUT, 'rehearsal_summary.json'), 'w') as f:
    json.dump(R, f, ensure_ascii=False, indent=1, default=str)
print('QLINES_REHEARSAL ' + json.dumps({'all_ok': R['all_ok'], 'failed': [k for k, c in R['checks'].items() if not c['ok']],
                                        'error': R.get('error', '')[-600:]}, ensure_ascii=False))
