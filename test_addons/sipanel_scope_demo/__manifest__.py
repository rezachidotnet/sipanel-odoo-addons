# -*- coding: utf-8 -*-
{
    'name': 'SIPANEL Scope Demo (C9 synthetic fixture) — TEST ONLY',
    'summary': 'Synthetic "متعلقات آبرو" fixture: test users, master V1/V2, quotation qty 85 m. NEVER a Production dependency.',
    'version': '19.0.1.0.0',
    'category': 'Hidden/Tests',
    'author': 'SIPANEL',
    'license': 'LGPL-3',
    'depends': ['sipanel_commercial_scope_core', 'sipanel_sale_scope', 'sipanel_scope_execution', 'sipanel_scope_costing'],
    'data': [
        'data/fixture_master.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'application': False,
}
