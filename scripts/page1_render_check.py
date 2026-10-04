# -*- coding: utf-8 -*-
"""Page 1 Project Information — PDF evidence on a CLONE database (never on sipanel).
Run: docker exec -i -e PHASE=pre|post -e OUT=/tmp/page1 odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d <clone> --no-http < scripts/page1_render_check.py

PHASE=pre : render SI-26/2546 as it is (before the module is installed on the clone).
PHASE=post: render SI-26/2546 as it is (= what Production would print after deployment, no data change),
            then build a synthetic copy with Opportunity / Requested System / distinct Project Site and render it
            in en_US and fa_IR. Everything written in PHASE=post is rolled back; the clone keeps SI-26/2546 as restored.
PDFs + a JSON summary land in $OUT inside the container (copy them out with docker cp).
"""
import json
import os

PHASE = os.environ.get('PHASE', 'post')
OUT = os.environ.get('OUT', '/tmp/page1')
os.makedirs(OUT, exist_ok=True)
assert env.cr.dbname != 'sipanel', 'refusing to run on the Production database'
Report = env['ir.actions.report']
summary = {'db': env.cr.dbname, 'phase': PHASE}


def render(order, tag):
    pdf, _ = Report._render_qweb_pdf('sale.report_saleorder', order.ids)
    path = os.path.join(OUT, f'{PHASE}_{tag}.pdf')
    with open(path, 'wb') as f:
        f.write(pdf)
    return path


def commercial(order):
    return {
        'lines': [(l.product_id.default_code, l.product_uom_qty, l.product_uom_id.name, l.price_unit, l.price_subtotal)
                  for l in order.order_line if not l.display_type],
        'untaxed': order.amount_untaxed, 'tax': order.amount_tax, 'total': order.amount_total,
        'fiscal_position': order.fiscal_position_id.display_name, 'shipping_is_partner': order.partner_shipping_id == order.partner_id,
    }


ref = env['sale.order'].search([('name', '=', 'SI-26/2546')])
assert len(ref) == 1, 'SI-26/2546 not found exactly once'
summary['si26_2546'] = {'pdf': render(ref, 'SI-26-2546_partner_lang'), 'partner_lang': ref.partner_id.lang, **commercial(ref)}
oracle = {'untaxed': 24865800000.0, 'tax': 2486580000.0, 'total': 27352380000.0}
summary['si26_2546']['oracle_ok'] = all(abs(summary['si26_2546'][k] - v) < 0.5 for k, v in oracle.items())

if PHASE == 'post':
    customer, contact = ref._sipanel_page1_parties()
    summary['si26_2546'].update({
        'page1_customer': customer.name, 'page1_contact': contact.name or None,
        'page1_project_name': ref.sipanel_project_name or None,
        'page1_project_site': ref._sipanel_page1_project_site().display_name or None,
        'page1_requested_system': ref.sipanel_requested_system_name_snapshot or None,
    })
    with env.cr.savepoint(flush=True) as sp:
        plan = env['sipanel.config'].resolve_system_plan()
        summary['system_plan'] = plan.name
        system = env['account.analytic.account'].search([('plan_id', '=', plan.id), ('name', '=', 'Standing Seam')], limit=1)
        lead = env['crm.lead'].create({'name': 'پروژه طالقان', 'type': 'opportunity', 'partner_id': ref.partner_id.id,
                                       'sipanel_requested_system_id': system.id})
        fixture = ref.copy({'opportunity_id': lead.id})
        fixture._sipanel_init_from_opportunity()
        site = env['res.partner'].create({'name': 'Taleghan Site', 'parent_id': ref.partner_id.commercial_partner_id.id,
                                          'type': 'delivery', 'street': 'Taleghan Road', 'city': 'Taleghan',
                                          'country_id': ref.partner_id.country_id.id or env.ref('base.ir').id})
        before = commercial(fixture)
        fixture.write({'partner_shipping_id': site.id})          # fiscal guard runs here
        after = commercial(fixture)
        summary['fixture'] = {'name': fixture.name, 'before': before, 'after': after,
                              'fiscal_unchanged': (before['fiscal_position'], before['tax'], before['total'])
                                                  == (after['fiscal_position'], after['tax'], after['total'])}
        for lang in ('en_US', 'fa_IR'):
            fixture.partner_id.lang = lang
            summary['fixture'][f'pdf_{lang}'] = render(fixture, f'fixture_{lang}')
        lead.write({'name': 'renamed opportunity'})
        system.write({'name': 'Standing Seam RENAMED'})
        fixture.invalidate_recordset()
        summary['fixture']['snapshot_after_renames'] = (fixture.sipanel_project_name, fixture.sipanel_requested_system_name_snapshot)
        sp.rollback()

with open(os.path.join(OUT, f'{PHASE}_summary.json'), 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
print(json.dumps(summary, ensure_ascii=False, default=str))
env.cr.rollback()
