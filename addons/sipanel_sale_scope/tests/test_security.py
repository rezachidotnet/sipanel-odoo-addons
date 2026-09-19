# -*- coding: utf-8 -*-
"""PT-23 (cost/leakage/company/portal denial), PT-24 (ORM/RPC/import bypass), S-01..S-10 subset."""
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged, new_test_user

from .common import SipanelSaleCase


@tagged('post_install', '-at_install', 'sipanel')
class TestSecurity(SipanelSaleCase):

    def test_s07_cost_fields_hidden_without_group(self):
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id
        comp = rev.component_ids[0]
        as_sales = rev.with_user(self.sales)
        self.assertTrue(as_sales.read(['name']))
        with self.assertRaises(AccessError):
            as_sales.read(['eligible_cost_total'])
        with self.assertRaises(AccessError):
            comp.with_user(self.sales).read(['unit_cost'])
        with self.assertRaises(AccessError):
            comp.with_user(self.sales).export_data(['product_id', 'cost_amount'])
        data = comp.with_user(self.sales).export_data(['product_id', 'final_qty'])
        self.assertTrue(data['datas'])
        # search_read with a cost field is refused too
        with self.assertRaises(AccessError):
            self.env['sipanel.quote.scope.component'].with_user(self.sales).search_read([('id', '=', comp.id)], ['cost_amount'])
        # cost viewer can read
        self.assertTrue(rev.with_user(self.finance).read(['eligible_cost_total']))

    def test_s02_company_isolation(self):
        company2 = self.env['res.company'].create({'name': 'SIPANEL-PT Other Co'})
        other_user = new_test_user(self.env, login='sipanel_pt_other_co', name='SIPANEL-PT Other',
                                   groups='sales_team.group_sale_manager,sipanel_sale_scope.group_scope_sales,sipanel_commercial_scope_core.group_scope_steward',
                                   company_id=company2.id, company_ids=[(6, 0, [company2.id])])
        order, scope = self._make_order(85.0)
        self.assertFalse(self.env['sipanel.quote.scope'].with_user(other_user).search([('id', '=', scope.id)]))
        self.assertFalse(self.env['sipanel.scope'].with_user(other_user).search([('id', '=', self.scope.id)]))
        self.assertEqual(self.scope.with_user(other_user).usage_count, 0)
        with self.assertRaises(AccessError):
            scope.with_user(other_user).read(['name'])

    def test_s04_portal_denied_on_internal_models(self):
        portal_user = new_test_user(self.env, login='sipanel_pt_portal', name='SIPANEL-PT Portal', groups='base.group_portal')
        portal_user.partner_id.write({'parent_id': self.partner.id})
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id
        for model in ('sipanel.quote.scope', 'sipanel.quote.scope.revision', 'sipanel.quote.scope.component', 'sipanel.scope', 'sipanel.scope.version', 'sipanel.quote.waiver'):
            with self.assertRaises(AccessError, msg=model):
                self.env[model].with_user(portal_user).search([])
        # artifacts: none before send, own sealed only after
        self.assertFalse(self.env['sipanel.quote.scope.artifact'].with_user(portal_user).search([]))
        order.action_quotation_sent()
        arts = self.env['sipanel.quote.scope.artifact'].with_user(portal_user).search([])
        self.assertTrue(arts)
        self.assertTrue(all(a.order_id == order for a in arts))
        self.assertTrue(arts[0].with_user(portal_user).read(['content_hash']))
        with self.assertRaises(AccessError):
            self.env['sipanel.quote.scope.revision'].with_user(portal_user).browse(rev.id).read(['sealed_hash'])
        # another partner's portal user sees nothing
        stranger = new_test_user(self.env, login='sipanel_pt_stranger', name='SIPANEL-PT Stranger', groups='base.group_portal')
        self.assertFalse(self.env['sipanel.quote.scope.artifact'].with_user(stranger).search([]))
        with self.assertRaises(AccessError):
            arts[0].with_user(stranger).read(['content_hash'])

    def test_s03_import_and_rpc_bypass_on_sealed(self):
        order, scope = self._make_order(85.0)
        order.action_quotation_sent()
        rev = scope.current_revision_id
        comp = rev.component_ids[0]
        xid = comp.export_data(['id'])['datas'][0][0]
        res = self.env['sipanel.quote.scope.component'].with_user(self.estimator).load(['id', 'rate'], [[xid, '77']])
        self.assertTrue(res.get('messages'))
        self.assertNotEqual(comp.rate, 77)
        with self.assertRaises(UserError):
            comp.with_user(self.estimator).write({'rate': 77})
        with self.assertRaises(UserError):
            rev.with_user(self.env.ref('base.user_admin')).write({'label_en': 'admin edit'})
        with self.assertRaises(UserError):
            rev.write({'state': 'working'})

    def test_s01_acl_matrix_subset(self):
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id
        # plain internal user: read only
        with self.assertRaises(AccessError):
            rev.with_user(self.plain_user).write({'final_note': 'x'})
        # steward cannot edit quotes (no sales group)
        with self.assertRaises(AccessError):
            rev.with_user(self.steward).write({'final_note': 'x'})
        # sales (own order) may edit the note of a working revision
        order.write({'user_id': self.sales.id})
        rev.with_user(self.sales).write({'final_note': 'sales note'})
        self.assertEqual(rev.final_note, 'sales note')
        # waiver approver fields are protected even from the record owner
        waiver = self.env['sipanel.quote.waiver'].create({'revision_id': rev.id, 'waiver_type': 'missing_estimate', 'reason': 'r'})
        with self.assertRaises(AccessError):
            waiver.with_user(self.sales).action_approve_finance()
        with self.assertRaises(UserError):
            waiver.sudo().write({'finance_approver_id': self.finance.id})

    def test_s10_privileged_actions_audited(self):
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id
        bracket = self._comp(scope, self.p_bracket)
        bracket.write({'qty_override': True, 'override_qty': 200, 'override_reason': 'audit test'})
        bracket.set_manual_cost(7.0, 'quote from supplier X')
        order.action_quotation_sent()
        events = self.env['sipanel.scope.audit.event'].search([('res_model', 'in', [bracket._name, rev._name]), ('res_id', 'in', [bracket.id, rev.id])])
        actions = set(events.mapped('action'))
        self.assertTrue({'override_qty', 'manual_cost', 'seal'} <= actions, actions)
        ev = events.filtered(lambda e: e.action == 'manual_cost')
        self.assertEqual(ev.reason, 'quote from supplier X')
        self.assertTrue(ev.correlation_uid)
        with self.assertRaises(UserError):
            ev.sudo().write({'reason': 'tamper'})
        # cost payload of audit events is invisible without the cost group
        with self.assertRaises(AccessError):
            ev.with_user(self.sales).read(['after_json'])
