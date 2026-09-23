# -*- coding: utf-8 -*-
"""STEP 2C-CLOSEOUT-HARDENING: the seal service must check the INITIATING uid in a non-sudo
environment. A pre-sudoed recordset (rev.with_user(x).sudo()) carries env.su=True, under
which check_access() is a no-op in Odoo - so the permission gate must rebuild a non-sudo
environment for env.uid before any elevated write."""
import re

from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard_ctx

from .common import SipanelSaleCase

COST_GROUPS = ('sipanel_commercial_scope_core.group_scope_cost_viewer', 'sipanel_sale_scope.group_scope_waiver_finance',
               'sipanel_scope_execution.group_scope_execution_owner', 'account.group_account_manager', 'sales_team.group_sale_manager')


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sales_seal', 'sipanel_sales_seal_sudo')
class TestSealPermissionUnderSudo(SipanelSaleCase):

    def _quotation(self, owner=None, qty=85.0):
        order, scope = self._make_order(qty)
        scope.current_revision_id.action_generate_note(accept=True)
        scope.anchor_line_id.write({'price_unit': 12000.0 / qty, 'tax_ids': [(5, 0, 0)]})
        if owner is not None:
            order.write({'user_id': owner.id})
        return order, scope, scope.current_revision_id

    def _snapshot(self, rev):
        rs = rev.sudo()
        return (rs.state, rs.sealed_hash, rs.sealed_by_id.id, len(rs.artifact_ids), rs.net_revenue_projection, rs.commercial_projection_json,
                rs.order_id.state)

    def _assert_refused_and_unchanged(self, rev, fn, msg):
        before = self._snapshot(rev)
        with self.assertRaises(AccessError, msg=msg):
            fn()
        self.env.invalidate_all()
        self.assertEqual(self._snapshot(rev), before, f'{msg}: stored state changed after a refused attempt')
        self.assertEqual(rev.sudo().state, 'working')

    # ------------------------------------------------------------------ A. authorised paths
    def test_plain_sales_user_seals_own_quotation(self):
        order, scope, rev = self._quotation(owner=self.sales)
        for g in COST_GROUPS:
            self.assertFalse(self.sales.has_group(g), g)
        order.with_user(self.sales).action_quotation_sent()
        self.assertEqual(rev.state, 'sent_sealed')
        self.assertEqual(rev.sealed_by_id, self.sales)
        ev = self.env['sipanel.scope.audit.event'].sudo().search([('res_model', '=', rev._name), ('res_id', '=', rev.id), ('action', '=', 'seal')])
        self.assertEqual(ev.actor_user_id, self.sales)
        self.assertEqual(rev._current_seal_hash(), rev.sealed_hash)

    def test_estimator_and_sales_manager_paths_succeed(self):
        order, scope, rev = self._quotation()
        order.with_user(self.estimator).action_quotation_sent()
        self.assertEqual(rev.state, 'sent_sealed')
        self.assertEqual(rev.sealed_by_id, self.estimator)
        order2, scope2, rev2 = self._quotation(owner=self.sales)
        order2.with_user(self.sales_mgr).action_quotation_sent()
        self.assertEqual(rev2.state, 'sent_sealed')
        self.assertEqual(rev2.sealed_by_id, self.sales_mgr)
        self.assertEqual(rev2._current_seal_hash(), rev2.sealed_hash)
        order2.with_user(self.sales_mgr).action_confirm()
        self.assertEqual(rev2.state, 'accepted_sealed')

    def test_root_uid_is_superuser_by_odoo_design(self):
        """Odoo forces su=True for SUPERUSER_ID in Environment.__new__ (orm/environments.py),
        so uid 1 is the only uid whose permission check cannot be made non-sudo. No explicit
        bypass exists in SIPANEL code; this test documents the inherent behaviour."""
        order, scope, rev = self._quotation()
        root = self.env.ref('base.user_root')
        env_root = self.env(user=root.id, su=False)
        self.assertTrue(env_root.su, 'Odoo itself makes uid 1 superuser')
        rev.with_user(root).action_seal()
        self.assertEqual(rev.state, 'sent_sealed')
        self.assertEqual(rev.sealed_by_id, root)

    # ------------------------------------------------------------------ B. unauthorised pre-sudoed paths
    def test_unauthorized_user_sudo_action_seal_is_refused(self):
        order, scope, rev = self._quotation(owner=self.sales)
        with self.assertRaises(AccessError):
            rev.with_user(self.plain_user).action_seal()                 # plain, no su
        self._assert_refused_and_unchanged(rev, lambda: rev.with_user(self.plain_user).sudo().action_seal(),
                                           'unauthorized_user.sudo().action_seal()')
        self._assert_refused_and_unchanged(rev, lambda: rev.with_user(self.steward).sudo().action_seal(),
                                           'steward (no sales rights) sudo action_seal')

    def test_inaccessible_revision_with_sales_sudo_is_refused(self):
        order, scope, rev = self._quotation()                            # the estimator's order, not the Sales user's
        self.assertFalse(order.with_user(self.sales).has_access('write'))
        self._assert_refused_and_unchanged(rev, lambda: rev.with_user(self.sales).sudo().action_seal(),
                                           'inaccessible_revision.with_user(sales).sudo().action_seal()')

    def test_inaccessible_order_with_sales_sudo_send_is_refused(self):
        order, scope, rev = self._quotation()
        self._assert_refused_and_unchanged(rev, lambda: order.with_user(self.sales).sudo().action_quotation_sent(),
                                           'inaccessible_order.with_user(sales).sudo().action_quotation_sent()')
        self.assertEqual(order.state, 'draft')
        self._assert_refused_and_unchanged(rev, lambda: order.with_user(self.sales).sudo().action_quotation_send(),
                                           'inaccessible_order.with_user(sales).sudo().action_quotation_send()')

    def test_sudo_with_raw_context_flags_is_refused(self):
        order, scope, rev = self._quotation()
        self._assert_refused_and_unchanged(
            rev, lambda: rev.with_user(self.sales).sudo().with_context(sipanel_seal_projection_service=True, sipanel_seal_transaction=True).action_seal(),
            'sudo + raw context flags')

    def test_sudo_with_guessed_token_is_refused(self):
        order, scope, rev = self._quotation()
        self._assert_refused_and_unchanged(
            rev, lambda: rev.with_user(self.sales).sudo().with_context(sipanel_seal_projection_service=True, sipanel_seal_transaction=True,
                                                                      sipanel_guard_token='guess').action_seal(),
            'sudo + guessed token')

    def test_sudo_with_import_context_is_refused(self):
        order, scope, rev = self._quotation()
        self._assert_refused_and_unchanged(rev, lambda: rev.with_user(self.sales).sudo().with_context(import_file=True).action_seal(),
                                           'sudo + import_file')
        self._assert_refused_and_unchanged(rev, lambda: rev.with_user(self.plain_user).sudo().with_context(import_file=True, active_test=False).action_seal(),
                                           'sudo + import_file (plain user)')

    def test_sudo_with_genuine_transaction_flag_but_no_service_token_is_refused(self):
        order, scope, rev = self._quotation()
        # the genuine seal-transaction flag (real token) opened by unrelated code does not confer the seal permission
        self._assert_refused_and_unchanged(rev, lambda: rev.with_user(self.sales).sudo().with_context(**guard_ctx('sipanel_seal_transaction')).action_seal(),
                                           'sudo + genuine seal_transaction flag, no service token, no permission')
        # and a direct projection write under that flag alone is refused (service token missing)
        with self.assertRaises(AccessError):
            rev.sudo().with_context(**guard_ctx('sipanel_seal_transaction')).write({'net_revenue_projection': 1.0})
        # server-action-like context (active_model/active_id) confers nothing either
        self._assert_refused_and_unchanged(
            rev, lambda: rev.with_user(self.plain_user).sudo().with_context(active_model=rev._name, active_id=rev.id, active_ids=rev.ids).action_seal(),
            'sudo + server action context')

    # ------------------------------------------------------------------ C. leakage after the authorised seal
    def test_sales_still_cannot_read_protected_fields_and_outputs_stay_clean(self):
        order, scope, rev = self._quotation(owner=self.sales)
        order.with_user(self.sales).action_quotation_sent()
        as_sales = rev.with_user(self.sales)
        for f in ('net_revenue_projection', 'commercial_projection_json', 'margin_amount', 'margin_percent', 'eligible_cost_total', 'direct_cost_total'):
            if f == 'commercial_projection_json':
                continue      # not a COST_GROUP field (anchor line projection); its write is service-only
            with self.assertRaises(AccessError, msg=f):
                as_sales.read([f])
        report = self.env.ref('sale.action_report_saleorder')
        html = report.with_user(self.sales)._render_qweb_html(report.report_name, order.ids)[0]
        raw = html.decode() if isinstance(html, bytes) else html
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw, flags=re.S | re.I)))
        for token in ('net_revenue', 'Net revenue', 'margin_amount', 'Margin', 'eligible_cost', 'unit_cost', 'Cost'):
            self.assertNotIn(token, text)
        self.assertEqual(set(scope.anchor_line_id._sipanel_portal_binding()), {'revision_id', 'seal_hash'})
        for art in rev.artifact_ids:
            self.assertFalse(any(t in (art.content_text or '') for t in ('cost', 'margin', 'net_revenue')))
