# -*- coding: utf-8 -*-
"""Customer-output regression tests (validation run 2026-09-20): D-02 unit names in the quotation language,
D-03 portal-signature acceptance reference."""
from odoo import fields
from odoo.tests import tagged

from .common import SipanelSaleCase


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_customer_output')
class TestCustomerOutput(SipanelSaleCase):

    def _fa_order(self, qty=12.0):
        env = self.env
        env['res.lang'].sudo()._activate_lang('fa_IR')
        self.uom_unit.sudo().update_field_translations('name', {'fa_IR': 'عدد'})
        self.uom_hour.sudo().update_field_translations('name', {'fa_IR': 'ساعت'})
        partner = env['res.partner'].create({'name': 'SIPANEL-PT-CORE Synthetic Persian Customer', 'lang': 'fa_IR', 'email': False})
        order = env['sale.order'].with_user(self.estimator).create({'partner_id': partner.id, 'origin': 'SIPANEL-PT-CORE'})
        scope = env['sipanel.quote.scope'].with_user(self.estimator)._create_from_version(order, self.v1, qty, self.uom_m)
        return order, scope

    def test_co01_unit_names_follow_quotation_language(self):
        """D-02: a Persian quotation must not print English unit names when Persian translations exist."""
        order, scope = self._fa_order()
        rev = scope.current_revision_id
        self.assertEqual(rev.language, 'fa_IR')
        bracket = rev.component_ids.filtered(lambda c: c.product_id == self.p_bracket)
        labour = rev.component_ids.filtered(lambda c: c.product_id == self.p_labour)
        self.assertEqual(bracket.uom_name_snapshot, 'عدد')
        self.assertEqual(labour.uom_name_snapshot, 'ساعت')
        self.assertEqual(bracket._customer_payload('fa_IR')['uom'], 'عدد')
        self.assertIn('عدد', rev.final_note)
        self.assertIn('ساعت', rev.final_note)
        self.assertNotIn('Units', rev.final_note)
        self.assertNotIn('Hours', rev.final_note)
        # untranslated units fall back to the source name
        gutter = rev.component_ids.filtered(lambda c: c.product_id == self.p_gutter and c.basis == 'per_scope_qty')
        self.assertEqual(gutter.uom_name_snapshot, self.uom_m.with_context(lang='fa_IR').name)
        # the English quotation keeps English names (no regression)
        order_en, scope_en = self._make_order(10.0)
        self.assertIn('Units', scope_en.current_revision_id.final_note)

    def test_co02_portal_signature_is_the_acceptance_reference(self):
        """D-03: a customer signature through the portal (signed_by/signed_on) must be traceable on the accepted revision."""
        order, scope = self._make_order(85.0)
        order.action_quotation_sent()
        rev = scope.current_revision_id
        self.assertEqual(rev.state, 'sent_sealed')
        # the portal accept controller stores the signature, then confirms as superuser (sudo)
        order.sudo().write({'signed_by': 'SIPANEL-PT Synthetic Signer', 'signed_on': fields.Datetime.now()})
        order.sudo().action_confirm()
        self.assertEqual(rev.state, 'accepted_sealed')
        self.assertEqual(scope.accepted_revision_id, rev)
        self.assertTrue(rev.acceptance_reference, 'portal signature must be recorded as the acceptance reference')
        self.assertTrue(rev.acceptance_reference.startswith('portal_signature:SIPANEL-PT Synthetic Signer:'))
        audit = self.env['sipanel.scope.audit.event'].sudo().search([('res_model', '=', rev._name), ('res_id', '=', rev.id), ('action', '=', 'accept')])
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.after_json.get('sealed_hash'), rev.sealed_hash)
        self.assertEqual(audit.after_json.get('reference'), rev.acceptance_reference)

    def test_co03_explicit_reference_wins_over_signature(self):
        order, scope = self._make_order(85.0)
        order.action_quotation_sent()
        order.sudo().write({'signed_by': 'SIPANEL-PT Synthetic Signer', 'signed_on': fields.Datetime.now()})
        self.assertEqual(order._sipanel_acceptance_reference('change_order:CO-1'), 'change_order:CO-1')
        self.assertTrue(order._sipanel_acceptance_reference().startswith('portal_signature:'))
        order.sudo().write({'signed_by': False, 'signed_on': False})
        self.assertIsNone(order._sipanel_acceptance_reference())
