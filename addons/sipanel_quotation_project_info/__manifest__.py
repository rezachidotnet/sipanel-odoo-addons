# -*- coding: utf-8 -*-
{
    'name': 'SIPANEL Quotation Project Information',
    'summary': 'Quotation Page 1: Project Name / Requested System snapshots from the CRM Opportunity, '
               'Project Site from the Delivery Address (fiscal-position safe), Customer / Contact Person',
    'version': '19.0.1.1.0',
    'category': 'Sales/Sales',
    'author': 'SIPANEL',
    'license': 'LGPL-3',
    # sale_shamsi_report owns the quotation cover (Page 1) this module fills in;
    # sipanel_commercial_scope_core owns the configured SIPANEL System analytic plan and the guard token;
    # sipanel_sale_scope owns the Scope seals the controlled fiscal change must respect.
    'depends': ['sale_crm', 'analytic', 'sipanel_commercial_scope_core', 'sipanel_sale_scope', 'sale_shamsi_report'],
    'data': [
        'security/ir.model.access.csv',
        'wizards/project_site_fiscal_change_views.xml',
        'views/crm_lead_views.xml',
        'views/sale_order_views.xml',
        'report/sale_report_templates.xml',
    ],
    # No pre/post-init hook and no migration script on purpose: existing quotations
    # are never backfilled (policy E of the 2026-10-04 work order).
    'installable': True,
    'auto_install': False,
    'application': False,
}
