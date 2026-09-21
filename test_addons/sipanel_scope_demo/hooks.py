# -*- coding: utf-8 -*-
"""STEP 2A: load the demo's Persian terms.

An Odoo data file can only set the `en_US` source of a translatable field, so
the Persian demo text is stored here through the public translation API. The
en_US key is always passed explicitly: with only a non-English key Odoo copies
that term into the English source.
"""
FA_TERMS = {
    'sipanel_scope_demo.version_v1': [('customer_label', 'Gutter accessories', 'متعلقات آبرو')],
    'sipanel_scope_demo.rl_gutter': [('customer_label', 'Gutter', 'ناودان')],
    'sipanel_scope_demo.rl_bracket': [('customer_label', 'Bracket', 'بست')],
    'sipanel_scope_demo.rl_screw': [('customer_label', 'Screw', 'پیچ')],
    'sipanel_scope_demo.rl_sealant': [('customer_label', 'Sealant', 'درزگیر')],
    'sipanel_scope_demo.rl_labour': [('customer_label', 'Installation', 'نصب')],
    'sipanel_scope_demo.rl_crane': [('customer_label', 'Crane', 'جرثقیل')],
}


def post_init_hook(env):
    env['res.lang'].sudo()._activate_lang('fa_IR')
    for xmlid, terms in FA_TERMS.items():
        record = env.ref(xmlid, raise_if_not_found=False)
        if not record:
            continue
        for field_name, en, fa in terms:
            record.update_field_translations(field_name, {'en_US': en, 'fa_IR': fa})
