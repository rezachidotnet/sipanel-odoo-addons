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

    # ------------------------------------------------------------ STEP 2C fixtures (own-line components)
    def _bridge_order_with_own_line(self, qty=85.0, user=None):
        """PT master (bridge owner) whose bracket component is billed on its own line."""
        order, scope = self._make_order(qty, user=user)
        scope.write({'project_id': self.project.id, 'system_id': self.system_a.id})
        bracket = self._comp(scope, self.p_bracket)
        bracket.write({'placement': 'own_line'})
        bracket.action_set_manual_sell_price(5.0)
        scope.current_revision_id.action_generate_note(accept=True)
        scope.anchor_line_id.write({'price_unit': 12000.0 / qty, 'tax_ids': [(5, 0, 0)]})
        order.action_quotation_sent()
        order.action_confirm()
        return order, scope, bracket

    def _native_order_with_own_line(self, qty=85.0):
        """Anchor creates a task natively (NATIVE_LINE_OWNER); the bracket is billed on its own line."""
        self.p_anchor.write({'service_tracking': 'task_global_project', 'project_id': self.project.id})
        v2 = self.env['sipanel.scope.version'].browse(self.v1.action_new_version()['res_id'])
        v2.write({'anchor_owner_mode': 'native_line_owner'})
        for l in v2.recipe_line_ids.filtered(lambda l: l.execution_mode != 'no_action'):
            l.write({'execution_mode': 'native_anchor_covered'})
        v2.action_release()
        order = self.env['sale.order'].create({'partner_id': self.partner.id})
        scope = self.env['sipanel.quote.scope']._create_from_version(order, v2, qty, self.uom_m)
        scope.write({'project_id': self.project.id, 'system_id': self.system_a.id})
        bracket = self._comp(scope, self.p_bracket)
        bracket.write({'placement': 'own_line'})
        bracket.action_set_manual_sell_price(5.0)
        scope.current_revision_id.action_generate_note(accept=True)
        scope.anchor_line_id.write({'price_unit': 200, 'tax_ids': [(5, 0, 0)]})
        order.action_quotation_sent()
        order.action_confirm()
        return order, scope, bracket

    def _generated_line(self, comp):
        return self.env['sale.order.line'].search([('sipanel_is_generated', '=', True), ('sipanel_source_component_id', '=', comp.id)])

    def _release(self, order):
        res = order.with_user(self.exec_owner).action_sipanel_release_execution()
        return self.env['sipanel.execution.batch'].browse(res['res_id'])

    def _docs(self, order):
        return {
            'pickings': self.env['stock.picking'].search_count([('origin', '=', order.name)]),
            'moves': self.env['stock.move'].search_count([('origin', '=', order.name)]),
            'po_lines': self.env['purchase.order.line'].search_count([('order_id.origin', '=', order.name)]),
            'mos': self.env['mrp.production'].search_count([('origin', '=', order.name)]),
            'tasks': self.env['project.task'].search_count([('sale_line_id', 'in', order.order_line.ids)]),
            'targets': self.env['sipanel.execution.target'].search_count([('demand_id.order_id', '=', order.id)]),
        }
