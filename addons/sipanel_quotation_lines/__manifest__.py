# -*- coding: utf-8 -*-
{
    'name': 'SIPANEL Quotation Lines',
    'summary': 'Quotation lines: technical description under the item title, Installation / Execution '
               'percentage line, amount in words under the totals',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'author': 'SIPANEL',
    'license': 'LGPL-3',
    # sipanel_sale_scope owns the Scope projection whose line text this module completes and the Scope
    # components the installation guard inspects; sipanel_quotation_project_info owns the Requested System;
    # sale_shamsi_report owns the quotation layout these report extensions sit in.
    'depends': ['sale_management', 'analytic', 'sipanel_sale_scope', 'sipanel_quotation_project_info',
                'sale_shamsi_report'],
    'data': [
        'views/product_template_views.xml',
        'views/account_analytic_account_views.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'report/sale_report_templates.xml',
    ],
    # v1 master data (documented in the implementation report): installation base flag on the
    # Standing Seam supply products and the Standing Seam -> installation product mapping.
    # Quotations are never touched: no installation line is added to an existing order.
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'application': False,
}
