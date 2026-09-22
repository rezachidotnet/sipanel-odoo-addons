# -*- coding: utf-8 -*-
"""OBS-2CH-01 (STEP 2C-CLOSEOUT): a plain Sales user who may edit/send their own quotation
can execute the governed Seal/Send workflow without Cost & Margin Viewer rights, while the
protected projection fields stay unreadable, unwritable and unforgeable."""
import re

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard_ctx

from .common import SipanelSaleCase

try:
    from odoo.addons.sipanel_sale_scope.models.quote_scope_revision import SEAL_SERVICE_GUARD, SEAL_PROJECTION_FIELDS
except ImportError:  # pre-fix source: lets the suite show per-test failures instead of an import error
    SEAL_SERVICE_GUARD = 'sipanel_seal_projection_service'
    SEAL_PROJECTION_FIELDS = ('commercial_projection_json', 'net_revenue_projection', 'fx_source_currency_id', 'fx_rate', 'fx_date', 'fx_source')

COST_GROUPS = ('sipanel_commercial_scope_core.group_scope_cost_viewer', 'sipanel_sale_scope.group_scope_waiver_finance',
               'sipanel_scope_execution.group_scope_execution_owner', 'account.group_account_manager')


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_sales_seal')
class TestSalesSealSend(SipanelSaleCase):

    def _sales_quotation(self, qty=85.0):
        """Prepared by the estimator (adding a Scope writes cost snapshots), owned by the Sales user."""
        order, scope = self._make_order(qty)
        scope.current_revision_id.action_generate_note(accept=True)
        scope.anchor_line_id.write({'price_unit': 12000.0 / qty, 'tax_ids': [(5, 0, 0)]})
        order.write({'user_id': self.sales.id})
        self.assertTrue(order.with_user(self.sales).has_access('write'), 'native permission on their own quotation')
        for g in COST_GROUPS:
            self.assertFalse(self.sales.has_group(g), g)
        return order, scope

    def _visible_text(self, html):
        raw = html.decode() if isinstance(html, bytes) else html
        body = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw, flags=re.S | re.I)
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', body))

    # ------------------------------------------------------------------ the governed path
    def test_plain_sales_user_seals_and_sends_own_quotation(self):
        order, scope = self._sales_quotation()
        rev = scope.current_revision_id
        order.with_user(self.sales).action_quotation_sent()
        self.assertEqual(order.state, 'sent')
        self.assertEqual(rev.state, 'sent_sealed')
        self.assertTrue(rev.sealed_hash)
        self.assertEqual(rev.sealed_by_id, self.sales)
        self.assertEqual(rev.sudo().net_revenue_projection, scope.anchor_line_id.price_subtotal, 'projection written by the service')
        self.assertEqual(rev._current_seal_hash(), rev.sealed_hash, 'the seal checksum verifies')
        self.assertEqual(len(rev.artifact_ids), 2)
        for g in COST_GROUPS:
            self.assertFalse(self.sales.has_group(g), 'no group was granted by the workflow')

    def test_audit_actor_is_the_initiating_sales_user(self):
        order, scope = self._sales_quotation()
        rev = scope.current_revision_id
        order.with_user(self.sales).action_quotation_sent()
        ev = self.env['sipanel.scope.audit.event'].sudo().search([('res_model', '=', rev._name), ('res_id', '=', rev.id), ('action', '=', 'seal')])
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev.actor_user_id, self.sales)

    def test_sales_user_cannot_seal_an_inaccessible_order(self):
        order, scope = self._sales_quotation()          # theirs
        other, other_scope = self._make_order(85.0)     # the estimator's
        other_scope.current_revision_id.action_generate_note(accept=True)
        other_scope.anchor_line_id.write({'price_unit': 100.0, 'tax_ids': [(5, 0, 0)]})
        self.assertNotEqual(other.user_id, self.sales)
        with self.assertRaises(AccessError):
            other.with_user(self.sales).action_quotation_sent()
        with self.assertRaises(AccessError):
            other_scope.current_revision_id.with_user(self.sales).action_seal()
        self.assertEqual(other_scope.current_revision_id.state, 'working')
        self.assertFalse(other_scope.current_revision_id.sealed_hash)

    # ------------------------------------------------------------------ protected fields stay protected
    def test_sales_user_cannot_read_net_revenue_projection(self):
        order, scope = self._sales_quotation()
        rev = scope.current_revision_id
        order.with_user(self.sales).action_quotation_sent()
        as_sales = rev.with_user(self.sales)
        for f in ('net_revenue_projection', 'margin_amount', 'margin_percent', 'eligible_cost_total'):
            with self.assertRaises(AccessError, msg=f):
                as_sales.read([f])
            with self.assertRaises(AccessError, msg=f):
                self.env['sipanel.quote.scope.revision'].with_user(self.sales).search_read([('id', '=', rev.id)], [f])
            with self.assertRaises(AccessError, msg=f):
                as_sales.export_data(['revision', f])
        self.assertNotIn('net_revenue_projection', as_sales.fields_get())
        self.assertTrue(as_sales.read(['revision', 'state', 'sealed_hash']))

    def test_sales_user_cannot_write_net_revenue_projection(self):
        order, scope = self._sales_quotation()
        rev = scope.current_revision_id
        before = rev.sudo().net_revenue_projection
        with self.assertRaises(AccessError):
            rev.with_user(self.sales).write({'net_revenue_projection': 999.0})
        with self.assertRaises(AccessError):
            rev.with_user(self.sales).write({'commercial_projection_json': {'price_subtotal': 999.0}})
        self.assertEqual(rev.sudo().net_revenue_projection, before)

    def test_sudo_without_the_genuine_guard_cannot_forge_the_projection(self):
        order, scope = self._sales_quotation()
        rev = scope.current_revision_id
        before = (rev.sudo().net_revenue_projection, rev.sudo().commercial_projection_json)
        for f in SEAL_PROJECTION_FIELDS:
            with self.assertRaises(AccessError, msg=f):
                rev.sudo().write({f: rev.sudo()[f].id if hasattr(rev.sudo()[f], 'id') else rev.sudo()[f]})
        with self.assertRaises(AccessError):
            rev.sudo().with_context(**guard_ctx('sipanel_seal_transaction')).write({'net_revenue_projection': 999.0})
        self.assertEqual((rev.sudo().net_revenue_projection, rev.sudo().commercial_projection_json), before)

    def test_raw_context_flag_does_not_open_the_service(self):
        order, scope = self._sales_quotation()
        rev = scope.current_revision_id
        for rs in (rev.with_user(self.sales), rev.sudo()):
            with self.assertRaises(AccessError):
                rs.with_context(sipanel_seal_projection_service=True, sipanel_seal_transaction=True).write({'net_revenue_projection': 999.0})
        self.assertNotEqual(rev.sudo().net_revenue_projection, 999.0)

    def test_guessed_token_does_not_open_the_service(self):
        order, scope = self._sales_quotation()
        rev = scope.current_revision_id
        with self.assertRaises(AccessError):
            rev.sudo().with_context(sipanel_seal_projection_service=True, sipanel_seal_transaction=True, sipanel_guard_token='guess').write({'net_revenue_projection': 999.0})
        self.assertNotEqual(rev.sudo().net_revenue_projection, 999.0)

    def test_import_context_does_not_open_the_service(self):
        order, scope = self._sales_quotation()
        rev = scope.current_revision_id
        with self.assertRaises(AccessError):
            rev.sudo().with_context(import_file=True).write({'net_revenue_projection': 999.0})
        xid = f'__export__.sipanel_quote_scope_revision_{rev.id}_seal'
        self.env['ir.model.data']._update_xmlids([{'xml_id': xid, 'record': rev}])
        res = self.env['sipanel.quote.scope.revision'].with_user(self.sales).load(['id', 'net_revenue_projection'], [[xid, '999']])
        self.assertTrue(res.get('messages'), 'import as the Sales user is refused')
        self.assertNotEqual(rev.sudo().net_revenue_projection, 999.0)

    # ------------------------------------------------------------------ other paths and outputs
    def test_estimator_and_manager_paths_remain_green(self):
        order, scope = self._make_order(85.0)
        scope.current_revision_id.action_generate_note(accept=True)
        scope.anchor_line_id.write({'price_unit': 12000.0 / 85.0, 'tax_ids': [(5, 0, 0)]})   # readiness (margin) as in the other fixtures
        order.with_user(self.estimator).action_quotation_sent()
        self.assertEqual(scope.current_revision_id.state, 'sent_sealed')
        order2, scope2 = self._sales_quotation()
        order2.with_user(self.sales_mgr).action_quotation_sent()      # a manager may send any order
        self.assertEqual(scope2.current_revision_id.state, 'sent_sealed')
        self.assertEqual(scope2.current_revision_id.sealed_by_id, self.sales_mgr)
        order2.with_user(self.sales_mgr).action_confirm()
        self.assertEqual(scope2.current_revision_id.state, 'accepted_sealed', 'acceptance verifies the seal made by the service')

    def test_customer_outputs_contain_no_cost_margin_or_net_revenue(self):
        order, scope = self._sales_quotation()
        rev = scope.current_revision_id
        order.with_user(self.sales).action_quotation_sent()
        net = rev.sudo().net_revenue_projection
        cost = rev.sudo().eligible_cost_total
        forbidden = ('net_revenue', 'Net revenue', 'margin_amount', 'Margin', 'eligible_cost', 'unit_cost', 'Cost')
        report = self.env.ref('sale.action_report_saleorder')
        html = report.with_user(self.sales)._render_qweb_html(report.report_name, order.ids)[0]
        text = self._visible_text(html)
        for token in forbidden:
            self.assertNotIn(token, text, f'{token!r} leaked into the quotation PDF')
        if cost:
            self.assertNotIn(f'{cost:,.2f}', text)
        # portal binding carries only the revision id and the seal hash
        self.assertEqual(set(scope.anchor_line_id._sipanel_portal_binding()), {'revision_id', 'seal_hash'})
        # portal: what the customer's portal user can read of the order, its lines and the sealed
        # artifacts (the portal page is rendered from exactly these records; internal models are denied)
        from odoo.tests import new_test_user
        portal_user = new_test_user(self.env, login='sipanel_pt_portal_seal', name='SIPANEL-PT Portal Seal', groups='base.group_portal')
        portal_user.partner_id.write({'parent_id': self.partner.id})
        portal_order = order.with_user(portal_user)
        ptext = ' '.join(f'{k}={v}' for rec in portal_order.read(['name', 'state', 'amount_untaxed', 'amount_total', 'note', 'partner_id', 'order_line']) for k, v in rec.items())
        ptext += ' '.join(f'{k}={v}' for rec in portal_order.order_line.with_user(portal_user).read(
            ['name', 'product_id', 'product_uom_qty', 'price_unit', 'price_subtotal', 'price_total', 'sipanel_is_generated']) for k, v in rec.items())
        readable = set(portal_order.order_line.with_user(portal_user).fields_get())
        self.assertFalse({f for f in readable if 'cost' in f or 'margin' in f}, 'no cost/margin field is even visible to the portal user')
        for art in self.env['sipanel.quote.scope.artifact'].with_user(portal_user).search([('order_id', '=', order.id)]):
            ptext += ' ' + (art.content_text or '')
        for token in ('net_revenue', 'margin_amount', 'margin_percent', 'eligible_cost', 'unit_cost', 'cost_amount', 'direct_cost'):
            self.assertNotIn(token, ptext, f'{token!r} leaked into portal-readable data')
        with self.assertRaises(AccessError):
            rev.with_user(portal_user).read(['sealed_hash'])
        # invoice customer output after confirmation (draft, never posted)
        order.with_user(self.sales_mgr).action_confirm()
        invoice = order.sudo()._create_invoices()
        self.assertEqual(invoice.state, 'draft')
        inv_report = self.env.ref('account.account_invoices')
        itext = self._visible_text(inv_report.sudo()._render_qweb_html(inv_report.report_name, invoice.ids)[0])
        for token in ('net_revenue', 'margin_amount', 'eligible_cost', 'unit_cost'):
            self.assertNotIn(token, itext)
        for aml in invoice.invoice_line_ids:
            self.assertFalse(any(f in aml._fields for f in ('sipanel_unit_cost', 'sipanel_margin')))
        self.assertTrue(net or net == 0.0)
