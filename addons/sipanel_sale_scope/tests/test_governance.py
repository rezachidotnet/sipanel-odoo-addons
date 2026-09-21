# -*- coding: utf-8 -*-
"""PT-10 (optional scope, governed transition, section guard), PT-22 partial (price-only amendment), PT-32 (roundtrip), seal/accept flow."""
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx

from .common import SipanelSaleCase


@tagged('post_install', '-at_install', 'sipanel')
class TestGovernance(SipanelSaleCase):

    def test_seal_accept_flow_and_mismatch(self):
        order, scope = self._make_order(85.0)
        scope.anchor_line_id.write({'price_unit': 200.0})
        with self.assertRaises(UserError):
            order.action_confirm()  # never sent (C3-D03)
        order.action_quotation_sent()
        rev = scope.current_revision_id
        self.assertEqual(rev.state, 'sent_sealed')
        self.assertTrue(rev.sealed_hash)
        self.assertTrue(order.sipanel_current_seal_hash)
        kinds = set(rev.artifact_ids.mapped('kind'))
        self.assertIn('text', kinds)
        # sealed revision is immutable through any channel (PT-24)
        with self.assertRaises(UserError):
            rev.write({'final_note': 'x'})
        with self.assertRaises(UserError):
            rev.component_ids[0].write({'rate': 9})
        with self.assertRaises(UserError):
            rev.sudo().component_ids[0].write({'rate': 9})
        with self.assertRaises(UserError):
            scope.anchor_line_id.write({'product_uom_qty': 90})
        with self.assertRaises(UserError):
            scope.anchor_line_id.write({'price_unit': 5})
        with self.assertRaises(UserError):
            scope.anchor_line_id.unlink()
        with self.assertRaises(UserError):
            rev.artifact_ids[0].unlink()
        # confirm accepts the sealed revision
        order.action_confirm()
        self.assertEqual(rev.state, 'accepted_sealed')
        self.assertEqual(scope.accepted_revision_id, rev)
        self.assertEqual(scope.state, 'accepted')
        self.assertEqual(scope.anchor_line_id.sipanel_guard_state, 'accepted')

    def test_mismatch_after_send_blocks_confirm(self):
        order, scope = self._make_order(85.0)
        scope.anchor_line_id.write({'price_unit': 200.0})
        order.action_quotation_sent()
        rev = scope.current_revision_id
        # unrelated commercial change on the order after send => hash mismatch
        self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.p_bracket.id, 'product_uom_qty': 1, 'price_unit': 50})
        with self.assertRaises(UserError):
            order.action_confirm()
        self.assertEqual(rev.state, 'sent_sealed')
        # re-send creates an amendment revision and seals it; then confirm works
        order.action_quotation_send()
        new_rev = scope.current_revision_id
        self.assertNotEqual(new_rev, rev)
        self.assertEqual(new_rev.state, 'sent_sealed')
        self.assertEqual(new_rev.prior_revision_id, rev)
        self.assertEqual(rev.state, 'sent_sealed', 'old revision is never unsealed')
        order.action_confirm()
        self.assertEqual(new_rev.state, 'accepted_sealed')

    def test_pt10_optional_scope_transitions(self):
        order, scope = self._make_order(85.0, optional=True)
        line = scope.anchor_line_id
        self.assertTrue(scope.is_optional)
        self.assertEqual(scope.acceptance_state, 'offered')
        self.assertEqual(line.product_uom_qty, 0.0)
        self.assertTrue(line._is_line_optional())
        rev = scope.current_revision_id.sudo()
        self.assertEqual(rev.scope_qty, 85.0)
        self.assertAlmostEqual(rev.offered_cost_total, 10734.0, places=4)
        self.assertEqual(rev.eligible_cost_total, 0.0, 'OFFERED cost excluded from baseline')
        # portal edit is impossible before send
        self.assertFalse(line._can_be_edited_on_portal())
        with self.assertRaises(UserError):
            scope._transition_acceptance('accepted', actor='operator')
        order.action_quotation_sent()
        self.assertTrue(line._can_be_edited_on_portal())
        # stale/replay portal call refused
        with self.assertRaises(UserError):
            scope._transition_acceptance('accepted', actor='portal', revision_id=rev.id, seal_hash='deadbeef')
        with self.assertRaises(UserError):
            scope._transition_acceptance('accepted', actor='portal', revision_id=None, seal_hash=rev.sealed_hash)
        # raw qty write on the sealed optional anchor is refused (operator must use the transition)
        with self.assertRaises(UserError):
            line.write({'product_uom_qty': 85})
        # governed portal acceptance
        scope._transition_acceptance('accepted', actor='portal', revision_id=rev.id, seal_hash=rev.sealed_hash)
        self.assertEqual(scope.acceptance_state, 'accepted')
        self.assertEqual(line.product_uom_qty, 85.0)
        self.assertAlmostEqual(rev.eligible_cost_total, 10734.0, places=4)
        # idempotent repeat
        scope._transition_acceptance('accepted', actor='portal', revision_id=rev.id, seal_hash=rev.sealed_hash)
        audits = self.env['sipanel.scope.audit.event'].search([('res_model', '=', scope._name), ('res_id', '=', scope.id), ('action', '=', 'acceptance_transition')])
        self.assertEqual(len(audits), 1)
        # section reorder/delete cannot detach a sealed scope (IF-03 guard)
        section = scope.optional_section_line_id
        self.assertTrue(section.sipanel_is_scoped_section)
        with self.assertRaises(UserError):
            section.unlink()
        with self.assertRaises(UserError):
            section.write({'sequence': 1})
        with self.assertRaises(UserError):
            section.write({'is_optional': False})
        self.assertEqual(scope.anchor_line_id, line)
        # accepting keeps the hash consistent (qty is part of the projection, so re-seal happens on next send)
        self.assertNotEqual(rev._current_seal_hash(), rev.sealed_hash)
        order.action_quotation_send()
        self.assertEqual(scope.current_revision_id.state, 'sent_sealed')
        order.action_confirm()
        self.assertEqual(scope.state, 'accepted')
        # decline path on a fresh optional scope
        order2, scope2 = self._make_order(10.0, optional=True)
        order2.action_quotation_sent()
        r2 = scope2.current_revision_id
        scope2._transition_acceptance('declined', actor='portal', revision_id=r2.id, seal_hash=r2.sealed_hash)
        self.assertEqual(scope2.acceptance_state, 'declined')
        self.assertEqual(scope2.anchor_line_id.product_uom_qty, 0.0)

    def test_pt22_price_only_amendment_keeps_baseline(self):
        order, scope = self._make_order(85.0)
        scope.anchor_line_id.write({'price_unit': 200.0})
        order.action_quotation_sent()
        order.action_confirm()
        base = scope.accepted_revision_id
        new = scope.current_revision_id.action_amend()
        self.assertEqual(scope.state, 'amending')
        self.assertEqual(new.state, 'working')
        self.assertEqual(len(new.component_ids), 8)
        self.assertEqual(set(new.component_ids.mapped('occurrence_uid')), set(base.component_ids.mapped('occurrence_uid')))
        scope.anchor_line_id.with_context(**guard_ctx('sipanel_apply_price')).write({'price_unit': 210.0})
        scope.action_accept_change_order('CO-SIPANEL-PT-001')
        self.assertEqual(scope.accepted_revision_id, new)
        self.assertEqual(new.change_order_ref, 'CO-SIPANEL-PT-001')
        self.assertEqual(base.state, 'accepted_sealed')
        for c_new in new.component_ids:
            c_old = base.component_ids.filtered(lambda c: c.occurrence_uid == c_new.occurrence_uid)
            self.assertEqual(c_new.final_qty, c_old.final_qty, 'price-only amendment has no quantity delta')

    def test_pt32_snapshot_roundtrip_language(self):
        self.partner.write({'lang': 'en_US'})
        order, scope = self._make_order(85.0)
        rev = scope.current_revision_id
        self.assertEqual(rev.language, 'en_US')
        self.assertIn('Gutter accessories', rev.final_note)
        order.action_quotation_sent()
        text_art = rev.artifact_ids.filtered(lambda a: a.kind == 'text')
        self.assertTrue(text_art)
        # live master translation change never touches the sealed artifact
        v2 = self.env['sipanel.scope.version'].browse(self.v1.action_new_version()['res_id'])
        v2.write({'customer_label': 'RENAMED'})
        v2.action_release()
        self.assertNotIn('RENAMED', text_art.content_text)
        self.assertIn('Gutter accessories', text_art.content_text)
        from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import sha256_of
        self.assertEqual(text_art.content_hash, sha256_of(text_art.content_text))
        # nothing internal leaks into the customer payload
        for token in ('standard_price', 'unit_cost', 'cost_amount', 'margin', 'allowance', 'contingency'):
            self.assertNotIn(token, text_art.content_text.lower())
