# -*- coding: utf-8 -*-
{
    'name': 'SIPANEL Quotation Lines',
    'summary': 'Quotation lines: technical description under the item title, Installation / Execution '
               'percentage line, amount in words under the totals; commercial terms (payment terms, delivery '
               'time, bank account, validity) required before a quotation is printed or sent; System technical sheet '
               '(schematic + specification rows) printed on its own page; Shop Drawings percentage line; quotation options as '
               'native no_variant attributes (top-sheet material)',
    'version': '19.0.1.4.0',
    'category': 'Sales/Sales',
    'author': 'SIPANEL',
    'license': 'LGPL-3',
    # sipanel_sale_scope owns the Scope projection whose line text this module completes and the Scope
    # components the installation guard inspects; sipanel_quotation_project_info owns the Requested System;
    # sale_shamsi_report owns the quotation layout these report extensions sit in; sale_stock prints the Incoterm
    # column this module removes from the header box (installed: sipanel_scope_execution depends on it).
    # sale_pdf_quote_builder (installed with sale_management) owns the "Quote Builder" tab this module labels in Persian.
    'depends': ['sale_management', 'sale_stock', 'analytic', 'sipanel_sale_scope', 'sipanel_quotation_project_info',
                'sale_shamsi_report', 'sale_pdf_quote_builder'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/account_analytic_account_views.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/res_users_views.xml',
        'views/product_attribute_views.xml',
        'report/sale_report_templates.xml',
    ],
    # v1 master data (documented in the implementation report): installation base flag on the
    # Standing Seam supply products and the Standing Seam -> installation product mapping.
    # Quotations are never touched: no installation line is added to an existing order.
    # data/standing_seam_schematic.png is not loaded by the module: the Production data step
    # scripts/sipanel_tech_sheet_data.py puts it on the Standing Seam System (owner requirements 2026-10-14).
    # v4 (owner 2026-10-16) was delivered as SVG (data/standing_seam_schematic_v4.svg, the source); the PNG is its
    # rendering at native size (Odoo lets only admins store SVG, and every quotation copies the image).
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'application': False,
}
