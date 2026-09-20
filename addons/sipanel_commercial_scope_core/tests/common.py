# -*- coding: utf-8 -*-
"""Shared synthetic fixture for Slice A tests. All records are prefixed SIPANEL-PT (test discipline)."""
import uuid

from odoo.tests import TransactionCase, new_test_user

TEST_BATCH = 'SIPANEL-PT-CORE'


class SipanelCoreCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        cls.steward = new_test_user(env, login='sipanel_pt_steward', name='SIPANEL-PT Steward',
                                    groups='base.group_user,sipanel_commercial_scope_core.group_scope_steward')
        cls.estimator = new_test_user(env, login='sipanel_pt_estimator', name='SIPANEL-PT Estimator',
                                      groups='base.group_user,sipanel_commercial_scope_core.group_scope_estimator')
        cls.plain_user = new_test_user(env, login='sipanel_pt_plain', name='SIPANEL-PT Plain User',
                                       groups='base.group_user')
        cls.uom_m = env.ref('uom.product_uom_meter')
        cls.uom_unit = env.ref('uom.product_uom_unit')
        cls.uom_hour = env.ref('uom.product_uom_hour')
        cls.uom_cm = env.ref('uom.product_uom_cm')
        Family = env['sipanel.uom.family']
        for uom, fam in ((cls.uom_m, 'length'), (cls.uom_cm, 'length'), (cls.uom_unit, 'count'), (cls.uom_hour, 'time')):
            if not Family.search([('uom_id', '=', uom.id)]):
                Family.create({'uom_id': uom.id, 'family': fam})
        cls.plan_system = env['account.analytic.plan'].create({'name': f'{TEST_BATCH} System'})
        cls.plan_activity = env['account.analytic.plan'].create({'name': f'{TEST_BATCH} Activity'})
        env['ir.config_parameter'].sudo().set_param('sipanel_scope.system_plan_id', cls.plan_system.id)
        env['ir.config_parameter'].sudo().set_param('sipanel_scope.activity_plan_id', cls.plan_activity.id)
        cls.system_a = env['account.analytic.account'].create({'name': f'{TEST_BATCH} System A', 'plan_id': cls.plan_system.id})
        cls.act_mfg = env['account.analytic.account'].create({'name': f'{TEST_BATCH} MFG', 'plan_id': cls.plan_activity.id})
        cls.act_ins = env['account.analytic.account'].create({'name': f'{TEST_BATCH} INS', 'plan_id': cls.plan_activity.id})
        cls.act_eqp = env['account.analytic.account'].create({'name': f'{TEST_BATCH} EQP', 'plan_id': cls.plan_activity.id})
        cls.act_gen = env['account.analytic.account'].create({'name': f'{TEST_BATCH} GEN', 'plan_id': cls.plan_activity.id})
        Product = env['product.product']

        def mk(name, uom, cost, ptype='consu'):
            vals = {'name': f'{TEST_BATCH} {name}', 'type': ptype, 'uom_id': uom.id,
                    'standard_price': cost, 'sale_ok': True, 'purchase_ok': True, 'list_price': 0.0}
            if ptype == 'consu' and 'is_storable' in Product._fields:
                vals['is_storable'] = True
            return Product.create(vals)
        cls.p_anchor = mk('Gutter run (anchor)', cls.uom_m, 0.0, 'service')
        cls.p_gutter = mk('Gutter', cls.uom_m, 100.0)
        cls.p_bracket = mk('Bracket', cls.uom_unit, 5.0)
        cls.p_screw = mk('Screw', cls.uom_unit, 1.0)
        cls.p_sealant = mk('Sealant cartridge', cls.uom_unit, 20.0)
        cls.p_labour = mk('Installation labour', cls.uom_hour, 30.0, 'service')
        cls.p_crane = mk('Base crane service', cls.uom_unit, 400.0, 'service')

    @classmethod
    def _make_master(cls, code='SIPANEL-PT-GUTTER', release=True):
        """C9 'متعلقات آبرو' synthetic master V1 (8 occurrences)."""
        env = cls.env
        # unique per run: an archived leftover with the same code (unique per company, archived included) must not break the suite
        scope = env['sipanel.scope'].create({'code': f'{code}-{uuid.uuid4().hex[:8]}', 'name': f'{TEST_BATCH} Gutter accessories', 'owner_user_id': cls.steward.id})
        v1 = env['sipanel.scope.version'].create({
            'scope_id': scope.id, 'label_fa': 'متعلقات آبرو', 'label_en': 'Gutter accessories',
            'base_uom_id': cls.uom_m.id, 'dimension_family': 'length',
            'anchor_product_id': cls.p_anchor.id, 'anchor_owner_mode': 'component_bridge_owner',
            'all_systems': True,
        })
        L = env['sipanel.scope.recipe.line']
        common = {'version_id': v1.id, 'customer_eligible': True}
        holder = cls if code == 'SIPANEL-PT-GUTTER' else type('Lines', (), {})()
        cls_ = holder
        cls_.l_gutter = L.create(dict(common, sequence=10, product_id=cls.p_gutter.id, uom_id=cls.uom_m.id, dimension_family='length',
                                     basis='per_scope_qty', rate=1.0, activity_id=cls.act_mfg.id, execution_mode='manufacture',
                                     customer_label_fa='ناودان', customer_label_en='Gutter'))
        cls_.l_bracket = L.create(dict(common, sequence=20, product_id=cls.p_bracket.id, uom_id=cls.uom_unit.id, dimension_family='count',
                                      basis='per_scope_qty', rate=2.0, activity_id=cls.act_ins.id, execution_mode='stock_issue',
                                      customer_label_fa='بست', customer_label_en='Bracket'))
        cls_.l_screw = L.create(dict(common, sequence=30, product_id=cls.p_screw.id, uom_id=cls.uom_unit.id, dimension_family='count',
                                    basis='per_scope_qty', rate=4.0, activity_id=cls.act_ins.id, execution_mode='stock_issue',
                                    customer_label_fa='پیچ', customer_label_en='Screw'))
        cls_.l_sealant = L.create(dict(common, sequence=40, product_id=cls.p_sealant.id, uom_id=cls.uom_unit.id, dimension_family='count',
                                      basis='manual', manual_qty_default=10.0, activity_id=cls.act_ins.id, execution_mode='stock_issue',
                                      customer_label_fa='درزگیر', customer_label_en='Sealant'))
        cls_.l_labour = L.create(dict(common, sequence=50, product_id=cls.p_labour.id, uom_id=cls.uom_hour.id, dimension_family='time',
                                     basis='fixed', fixed_qty=8.0, activity_id=cls.act_ins.id, execution_mode='labour',
                                     customer_label_fa='نصب', customer_label_en='Installation'))
        cls_.l_crane = L.create(dict(common, sequence=60, product_id=cls.p_crane.id, uom_id=cls.uom_unit.id, dimension_family='count',
                                    basis='fixed', fixed_qty=1.0, activity_id=cls.act_eqp.id, execution_mode='equipment_service',
                                    customer_label_fa='جرثقیل', customer_label_en='Crane'))
        cls_.l_allow = L.create(dict(common, sequence=70, product_id=cls.p_screw.id, uom_id=cls.uom_unit.id, dimension_family='count',
                                    basis='percent_of_quantity', percent=5.0, base_line_ids=[(6, 0, [cls_.l_screw.id])],
                                    activity_id=cls.act_ins.id, execution_mode='stock_issue', customer_eligible=False,
                                    disclosure='internal_only'))
        cls_.l_cont = L.create(dict(common, sequence=80, kind='product', product_id=cls.p_gutter.id, uom_id=cls.uom_m.id, dimension_family='length',
                                   basis='percent_of_cost', percent=2.0, base_line_ids=[(6, 0, [cls_.l_gutter.id, cls_.l_bracket.id])],
                                   cost_policy='derived', activity_id=cls.act_gen.id, execution_mode='no_action',
                                   no_action_reason='allowance', customer_eligible=False, disclosure='internal_only'))
        if release:
            v1.action_release()
        return scope, v1
