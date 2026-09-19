# -*- coding: utf-8 -*-
"""Approved SIPANEL configuration (run once through `odoo shell -d sipanel`):
   analytic plans, UoM families, stock-issue operation type, default project, policy approval, initial roles.
   Idempotent. No numeric threshold is set (TBE). Login of the initial role holder is a parameter, not module data.
   Usage: docker exec -i odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d sipanel --no-http < scripts/sipanel_configure.py
"""
import json
import os

LOGIN = os.environ.get('SIPANEL_ROLE_LOGIN', 'amirmousa1983@gmail.com')
SOURCE = 'Management authorization 2026-09-19 (SIPANEL_IMPLEMENTATION_POLICY_APPROVAL_RECORD.md); statutory tax/accounting validation still required'
log = {}
company = env.company
ICP = env['ir.config_parameter'].sudo()

# 1. System / Activity analytic plans (B-03)
Plan = env['account.analytic.plan']
plans = {}
for key, name in (('sipanel_scope.system_plan_id', 'SIPANEL System'), ('sipanel_scope.activity_plan_id', 'SIPANEL Activity')):
    pid = ICP.get_param(key)
    plan = Plan.browse(int(pid)) if pid and str(pid).isdigit() and Plan.browse(int(pid)).exists() else Plan.search([('name', '=', name)], limit=1)
    if not plan:
        plan = Plan.create({'name': name})
    ICP.set_param(key, plan.id)
    plans[key] = plan
    log[key] = f'{plan.id}:{plan.name}'

# 2. UoM families (C1-D04)
Family = env['sipanel.uom.family']
mapping = {'uom.product_uom_meter': 'length', 'uom.product_uom_cm': 'length', 'uom.product_uom_km': 'length', 'uom.product_uom_millimeter': 'length',
           'uom.product_uom_unit': 'count', 'uom.product_uom_dozen': 'count', 'uom.product_uom_hour': 'time', 'uom.product_uom_day': 'time',
           'uom.product_uom_kgm': 'mass', 'uom.product_uom_gram': 'mass', 'uom.product_uom_ton': 'mass', 'uom.product_uom_litre': 'volume',
           'uom.product_uom_cubic_meter': 'volume', 'uom.product_uom_square_meter': 'area'}
fam_log = []
for xid, fam in mapping.items():
    uom = env.ref(xid, raise_if_not_found=False)
    if uom and not Family.search([('uom_id', '=', uom.id)]):
        Family.create({'uom_id': uom.id, 'family': fam, 'note': 'approved configuration 2026-09-19'})
        fam_log.append(f'{uom.name}={fam}')
log['uom_families_added'] = fam_log

# 3. Stock-issue operation type (internal type from the company warehouse, or a dedicated one)
PT = env['stock.picking.type']
pid = ICP.get_param('sipanel_scope.stock_issue_picking_type_id')
ptype = PT.browse(int(pid)) if pid and str(pid).isdigit() and PT.browse(int(pid)).exists() else PT.search([('name', '=', 'SIPANEL Site Issue'), ('company_id', '=', company.id)], limit=1)
if not ptype:
    wh = env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
    site = env['stock.location'].search([('name', '=', 'SIPANEL Site'), ('usage', '=', 'customer')], limit=1) or env['stock.location'].create(
        {'name': 'SIPANEL Site', 'usage': 'customer', 'company_id': company.id})
    ptype = PT.create({'name': 'SIPANEL Site Issue', 'code': 'internal', 'sequence_code': 'SIPI', 'warehouse_id': wh.id,
                       'default_location_src_id': wh.lot_stock_id.id, 'default_location_dest_id': site.id, 'company_id': company.id})
ICP.set_param('sipanel_scope.stock_issue_picking_type_id', ptype.id)
log['stock_issue_picking_type'] = f'{ptype.id}:{ptype.name}'

# 4. Default execution project
Project = env['project.project']
pid = ICP.get_param('sipanel_scope.default_project_id')
project = Project.browse(int(pid)) if pid and str(pid).isdigit() and Project.browse(int(pid)).exists() else Project.search([('name', '=', 'SIPANEL Execution (default)')], limit=1)
if not project:
    project = Project.create({'name': 'SIPANEL Execution (default)', 'company_id': company.id})
ICP.set_param('sipanel_scope.default_project_id', project.id)
log['default_project'] = f'{project.id}:{project.name}'

# 5. Recognition policies: approve the nine shipped rows with the recorded source (Finance role required)
user = env['res.users'].search([('login', '=', LOGIN)], limit=1)
if not user:
    raise SystemExit(f'role holder login {LOGIN} not found; nothing else changed')
groups = ['sipanel_commercial_scope_core.group_scope_steward', 'sipanel_commercial_scope_core.group_scope_estimator',
          'sipanel_commercial_scope_core.group_scope_cost_viewer', 'sipanel_sale_scope.group_scope_sales',
          'sipanel_sale_scope.group_scope_waiver_sales', 'sipanel_sale_scope.group_scope_waiver_finance',
          'sipanel_scope_execution.group_scope_execution_owner', 'sipanel_scope_costing.group_scope_finance']
added = []
for xid in groups:
    g = env.ref(xid)
    if g not in user.group_ids:
        user.write({'group_ids': [(4, g.id)]})
        added.append(xid)
log['role_holder'] = f'{user.id}:{user.name} share={user.share} active={user.active}'
log['groups_added'] = added
Policy = env['sipanel.cost.recognition.policy']
approved = []
for p in Policy.search([('company_id', '=', company.id), ('state', '=', 'draft')]):
    p.with_user(user).action_approve(source=SOURCE)
    approved.append(f'{p.route} v{p.version}')
log['policies_approved'] = approved
log['policies_state'] = dict(Policy.read_group([('company_id', '=', company.id)], ['route:count'], ['state'])[0] and
                             [(r['state'], r['state_count']) for r in Policy.read_group([('company_id', '=', company.id)], ['route:count'], ['state'])])
env.cr.commit()
print('SIPANEL_CONFIGURE_OK ' + json.dumps(log, ensure_ascii=False, default=str))
