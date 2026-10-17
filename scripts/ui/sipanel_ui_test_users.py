# -*- coding: utf-8 -*-
"""UI acceptance test (owner 2026-10-16): the two test users of the clone - CLONE ONLY, refused on any other database.

  ui_sales    a normal salesperson: Sales / User: Own Documents Only (sales_team.group_sale_salesman), nothing else
              beyond the internal user group Odoo gives every employee; Persian UI (fa_IR, Asia/Tehran)
  ui_manager  a Sales Manager: Sales / Administrator (sales_team.group_sale_manager), not Settings / admin

This is test set-up, not the quotation: the quotation and the manager tasks are done in the web UI
(scripts/ui/sipanel_ui_acceptance.py). Passwords come from UI_PASSWORD (random per run, never stored).
Prints "SIPANEL_UI_USERS {json}" with the groups of both users and of the Production salespeople for comparison.

Run (odoo shell on the clone): ... odoo shell -d <clone> < this, with -e UI_PASSWORD=...
"""
import json
import os

assert env.cr.dbname.startswith('sipanel_qlines_clone_'), f'refused: {env.cr.dbname} is not a clone'
password = os.environ['UI_PASSWORD']
assert len(password) >= 16

Users = env['res.users'].with_context(no_reset_password=True, active_test=False)
company = env.ref('base.main_company')
R = {}
for login, name, group in (('ui_sales', 'UI Test Salesperson', 'sales_team.group_sale_salesman'),
                           ('ui_manager', 'UI Test Sales Manager', 'sales_team.group_sale_manager')):
    user = Users.search([('login', '=', login)])
    vals = {'name': name, 'login': login, 'lang': 'fa_IR', 'tz': 'Asia/Tehran', 'active': True,
            'company_id': company.id, 'company_ids': [(6, 0, company.ids)],
            'group_ids': [(6, 0, (env.ref('base.group_user') | env.ref(group)).ids)]}
    user = user.write(vals) and user if user else Users.create(vals)
    user.password = password
    R[login] = {'id': user.id, 'groups': sorted(user.all_group_ids.mapped('full_name'))}
assert not env['res.users'].browse(R['ui_sales']['id']).has_group('sales_team.group_sale_manager')
assert not env['res.users'].browse(R['ui_manager']['id']).has_group('base.group_system')
# for comparison: the groups of the Production users that already issue quotations
sellers = env['sale.order'].search([('user_id', '!=', False)]).mapped('user_id')
R['production_sellers'] = {u.login: {'sales_manager': u.has_group('sales_team.group_sale_manager'),
                                     'settings_admin': u.has_group('base.group_system'),
                                     'lang': u.lang} for u in sellers}
# the quotation products as a salesperson finds them (owner 2026-10-17: the 20 cm flashing has its own SIP- code)
Product = env['product.product'].with_context(active_test=False)
flash20 = env['product.template'].with_context(lang='en_US', active_test=False).search(
    [('name', '=', 'Flashing in the top-sheet material, developed width up to 20 cm (supply only)')]).product_variant_ids
R['products'] = {code: {'id': p.id, 'code': p.default_code, 'list_price': p.list_price,
                        'fa_IR': p.with_context(lang='fa_IR').name, 'en_US': p.with_context(lang='en_US').name}
                 for code, p in (('SIP-000074', Product.search([('default_code', '=', 'SIP-000074')])),
                                 ('SIP-000076', Product.search([('default_code', '=', 'SIP-000076')])),
                                 ('FLASH20', flash20),
                                 ('SIP-000077', Product.search([('default_code', '=', 'SIP-000077')])))
                 if len(p) == 1}
env.cr.commit()
print('SIPANEL_UI_USERS ' + json.dumps(R, ensure_ascii=False))
