# -*- coding: utf-8 -*-
from odoo.tests import new_test_user

from odoo.addons.sipanel_sale_scope.tests.common import SipanelSaleCase, TEST_BATCH


class SipanelExecutionCase(SipanelSaleCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.exec_owner = new_test_user(env, login='sipanel_pt_exec', name='SIPANEL-PT Execution Owner',
                                       groups='base.group_user,sipanel_scope_execution.group_scope_execution_owner,stock.group_stock_user,purchase.group_purchase_user,mrp.group_mrp_user,project.group_project_user,sales_team.group_sale_manager,sipanel_sale_scope.group_scope_sales,sipanel_commercial_scope_core.group_scope_cost_viewer')
        cls.project = env['project.project'].create({'name': f'{TEST_BATCH} Project'})
        env['ir.config_parameter'].sudo().set_param('sipanel_scope.default_project_id', cls.project.id)
        env['ir.config_parameter'].sudo().set_param('sipanel_scope.release_retry_count', '3')
        wh = env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        ptype = env['stock.picking.type'].create({
            'name': f'{TEST_BATCH} Site issue', 'code': 'internal', 'sequence_code': 'SIPT', 'warehouse_id': wh.id,
            'default_location_src_id': wh.lot_stock_id.id,
            'default_location_dest_id': env['stock.location'].create({'name': f'{TEST_BATCH} Site', 'usage': 'customer'}).id,
            'company_id': cls.company.id,
        })
        env['ir.config_parameter'].sudo().set_param('sipanel_scope.stock_issue_picking_type_id', ptype.id)
        cls.picking_type = ptype
        vendor = env['res.partner'].create({'name': f'{TEST_BATCH} Synthetic Vendor', 'email': False, 'phone': False})
        cls.vendor = vendor
        for p, price in ((cls.p_crane, 400.0), (cls.p_screw, 1.0)):
            env['product.supplierinfo'].create({'partner_id': vendor.id, 'product_tmpl_id': p.product_tmpl_id.id, 'price': price, 'min_qty': 0})
        # BoM for the gutter (manufacture route)
        cls.p_coil = env['product.product'].create({'name': f'{TEST_BATCH} Coil', 'type': 'consu', 'is_storable': True, 'uom_id': cls.uom_m.id, 'standard_price': 60.0})
        cls.bom = env['mrp.bom'].create({'product_tmpl_id': cls.p_gutter.product_tmpl_id.id, 'product_qty': 1.0, 'type': 'normal',
                                         'bom_line_ids': [(0, 0, {'product_id': cls.p_coil.id, 'product_qty': 1.0})]})

    @classmethod
    def _confirmed_order(cls, qty=85.0):
        order, scope = cls._make_order(qty)
        scope.write({'project_id': cls.project.id, 'system_id': cls.system_a.id})
        scope.anchor_line_id.write({'price_unit': 12000.0 / qty, 'tax_ids': [(5, 0, 0)]})
        order.action_quotation_sent()
        order.action_confirm()
        return order, scope
