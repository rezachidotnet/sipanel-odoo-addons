# -*- coding: utf-8 -*-
"""Shared fixture for Slice B/C tests: C9 synthetic master + a synthetic quotation (SIPANEL-PT prefix, no real contacts)."""
from odoo.tests import new_test_user

from odoo.addons.sipanel_commercial_scope_core.tests.common import SipanelCoreCase, TEST_BATCH


class SipanelSaleCase(SipanelCoreCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.sales = new_test_user(env, login='sipanel_pt_sales', name='SIPANEL-PT Sales',
                                  groups='sales_team.group_sale_salesman,sipanel_sale_scope.group_scope_sales,base.group_allow_export')
        cls.sales_mgr = new_test_user(env, login='sipanel_pt_sales_mgr', name='SIPANEL-PT Sales Manager',
                                      groups='sales_team.group_sale_manager,sipanel_sale_scope.group_scope_sales,sipanel_sale_scope.group_scope_waiver_sales')
        cls.finance = new_test_user(env, login='sipanel_pt_finance', name='SIPANEL-PT Finance',
                                    groups='account.group_account_manager,sipanel_sale_scope.group_scope_waiver_finance,sipanel_commercial_scope_core.group_scope_cost_viewer')
        cls.estimator.write({'group_ids': [(4, env.ref('sipanel_sale_scope.group_scope_sales').id), (4, env.ref('sales_team.group_sale_manager').id)]})
        cls.partner = env['res.partner'].create({'name': f'{TEST_BATCH} Synthetic Customer', 'lang': 'en_US', 'email': False, 'phone': False})
        cls.scope, cls.v1 = cls._make_master()
        cls.p_anchor.write({'list_price': 0.0})

    @classmethod
    def _make_order(cls, qty=85.0, optional=False, uom=None, user=None):
        env = cls.env
        order = env['sale.order'].with_user(user or cls.estimator).create({'partner_id': cls.partner.id, 'origin': TEST_BATCH})
        scope = env['sipanel.quote.scope'].with_user(user or cls.estimator)._create_from_version(
            order, cls.v1, qty, uom or cls.uom_m, optional=optional,
            section_line=(env['sale.order.line'].create({'order_id': order.id, 'display_type': 'line_section', 'name': 'Options', 'is_optional': True, 'sequence': 100}) if optional else None))
        return order, scope

    @staticmethod
    def _comp(scope, product=None, basis=None):
        comps = scope.current_revision_id.component_ids.filtered(lambda c: c.active_state == 'active')
        if product is not None:
            comps = comps.filtered(lambda c: c.product_id == product)
        if basis is not None:
            comps = comps.filtered(lambda c: c.basis == basis)
        return comps
