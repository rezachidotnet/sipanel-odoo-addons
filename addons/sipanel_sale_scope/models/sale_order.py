# -*- coding: utf-8 -*-
"""sale.order hooks: seal at send, verify at confirm, independent copy, currency guard (GAP-B14, B17, B18; SV-14)."""
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx

COST_GROUP = 'sipanel_commercial_scope_core.group_scope_cost_viewer'


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sipanel_quote_scope_ids = fields.One2many('sipanel.quote.scope', 'order_id', copy=False)
    sipanel_scope_count = fields.Integer(compute='_compute_sipanel_scope_count')
    sipanel_has_scopes = fields.Boolean(compute='_compute_sipanel_has_scopes', store=True)
    sipanel_current_seal_hash = fields.Char(readonly=True, copy=False)
    sipanel_readiness_state = fields.Selection([('ok', 'OK'), ('warnings', 'Warnings'), ('blocked', 'Blocked')],
                                               compute='_compute_sipanel_readiness')
    sipanel_readiness_text = fields.Text(compute='_compute_sipanel_readiness')
    sipanel_company_currency_ok = fields.Boolean(compute='_compute_sipanel_currency_ok')
    sipanel_total_cost = fields.Monetary(compute='_compute_sipanel_totals', groups=COST_GROUP)
    sipanel_total_margin = fields.Monetary(compute='_compute_sipanel_totals', groups=COST_GROUP)

    @api.depends('sipanel_quote_scope_ids', 'sipanel_quote_scope_ids.active')
    def _compute_sipanel_scope_count(self):
        for o in self:
            o.sipanel_scope_count = len(o.sipanel_quote_scope_ids.filtered('active'))

    @api.depends('sipanel_quote_scope_ids', 'sipanel_quote_scope_ids.active')
    def _compute_sipanel_has_scopes(self):
        for o in self:
            o.sipanel_has_scopes = bool(o.sipanel_quote_scope_ids.filtered('active'))

    @api.depends('currency_id', 'company_id.currency_id')
    def _compute_sipanel_currency_ok(self):
        for o in self:
            o.sipanel_company_currency_ok = o.currency_id == o.company_id.currency_id

    def _compute_sipanel_readiness(self):
        for o in self:
            issues = []
            for s in o.sipanel_quote_scope_ids.filtered('active'):
                issues += [dict(i, scope=s.display_name) for i in s._readiness_issues()]
            o.sipanel_readiness_text = '\n'.join(f"[{i['level'].upper()}] {i['scope']} {i['code']}: {i['msg']}" for i in issues)
            o.sipanel_readiness_state = 'blocked' if any(i['level'] == 'block' for i in issues) else ('warnings' if issues else 'ok')

    def _compute_sipanel_totals(self):
        for o in self:
            revs = o.sipanel_quote_scope_ids.filtered('active').mapped('current_revision_id').sudo()
            o.sipanel_total_cost = sum(revs.mapped('eligible_cost_total'))
            o.sipanel_total_margin = sum(revs.mapped('margin_amount'))

    # ---------------------------------------------------------- guards
    def _sipanel_check_currency(self):
        Config = self.env['sipanel.config']
        for o in self.filtered('sipanel_has_scopes'):
            if Config.company_currency_only() and o.currency_id != o.company_id.currency_id:
                raise UserError(self.env._("Order %s carries a Scope: foreign-currency quotations are blocked in MVP (BQ-09).", o.name))

    def _sipanel_check_readiness(self):
        for o in self.filtered('sipanel_has_scopes'):
            blocking = []
            for s in o.sipanel_quote_scope_ids.filtered('active'):
                blocking += [f"{s.display_name}: {i['msg']}" for i in s._readiness_issues() if i['level'] == 'block']
            if blocking:
                raise UserError(self.env._("Quotation %(o)s cannot be sent:\n%(l)s", o=o.name, l='\n'.join('- ' + b for b in blocking)))

    def _sipanel_seal_current_revisions(self, actor='send'):
        """Seal every WORKING revision; re-seal changed SENT revisions through an amendment; idempotent otherwise."""
        for o in self.filtered('sipanel_has_scopes'):
            o._sipanel_check_currency()
            o._sipanel_check_readiness()
            hashes = []
            for s in o.sipanel_quote_scope_ids.filtered('active'):
                rev = s.current_revision_id
                if rev.state == 'working':
                    rev.action_seal(actor=actor)
                elif rev.state == 'sent_sealed':
                    if rev._current_seal_hash() != rev.sealed_hash:
                        rev = rev.action_amend()
                        rev.action_generate_note(accept=False)
                        rev.action_mark_note_reviewed()
                        rev.action_seal(actor=actor)
                elif rev.state == 'accepted_sealed' and rev._current_seal_hash() != rev.sealed_hash:
                    raise UserError(self.env._("Scope %s changed after acceptance; create an amendment revision first.", s.display_name))
                hashes.append(s.current_revision_id.sealed_hash or '')
            from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import sha256_of
            o.write({'sipanel_current_seal_hash': sha256_of(sorted(hashes))})
        return True

    def _sipanel_acceptance_reference(self, reference=None):
        """Explicit reference wins; otherwise a customer portal signature (signed_by/signed_on) is the acceptance evidence (D-03)."""
        self.ensure_one()
        if reference:
            return reference
        if self.signed_by and self.signed_on:
            return f"portal_signature:{self.signed_by}:{fields.Datetime.to_string(self.signed_on)}"
        return None

    def _sipanel_accept_current_revisions(self, reference=None):
        for o in self.filtered('sipanel_has_scopes'):
            ref = o._sipanel_acceptance_reference(reference)
            for s in o.sipanel_quote_scope_ids.filtered('active'):
                rev = s.current_revision_id
                if rev.state == 'working':
                    raise UserError(self.env._("Scope %s was never sent: send the quotation before confirming (C3-D03).", s.display_name))
                rev.action_accept(reference=ref)
        return True

    # ---------------------------------------------------------- native hooks (SV-14)
    def action_quotation_send(self):
        self._sipanel_seal_current_revisions(actor='send')
        return super().action_quotation_send()

    def action_quotation_sent(self):
        self._sipanel_seal_current_revisions(actor='mark_sent')
        return super().action_quotation_sent()

    def write(self, vals):
        if vals.get('state') == 'sent' and not guard(self.env, 'sipanel_seal_transaction'):
            self.filtered(lambda o: o.state == 'draft')._sipanel_seal_current_revisions(actor='mark_sent')
        if 'currency_id' in vals or 'pricelist_id' in vals:
            res = super().write(vals)
            self._sipanel_check_currency()
            return res
        return super().write(vals)

    def action_confirm(self):
        self._sipanel_check_currency()
        self._sipanel_accept_current_revisions(reference=guard(self.env, 'sipanel_acceptance_reference'))
        return super().action_confirm()

    # ---------------------------------------------------------- STEP 2B invoice gate
    def _sipanel_check_seal_integrity_for_invoice(self):
        """Refuse to invoice governed Scope content that no longer matches what the
        customer accepted.

        The acceptance and confirmation gates already refuse drift
        (quote_scope_revision.action_accept and, through it, action_confirm);
        this is the third and last gate, because an order can still be edited
        between confirmation and invoicing.
        """
        for o in self.filtered('sipanel_has_scopes'):
            drifted = []
            for s in o.sipanel_quote_scope_ids.filtered('active'):
                rev = s.accepted_revision_id or s.current_revision_id
                if not rev or rev.state == 'working' or not rev.sealed_hash:
                    continue
                if rev._current_seal_hash() != rev.sealed_hash:
                    drifted.append(f"{s.display_name} (sealed {rev.sealed_hash[:12]}…)")
            if drifted:
                raise UserError(self.env._(
                    "Order %(o)s cannot be invoiced: the governed Scope content changed after "
                    "acceptance:\n%(l)s\nCreate an amendment revision and reseal, then invoice.",
                    o=o.name, l='\n'.join('- ' + d for d in drifted)))

    def _create_invoices(self, grouped=False, final=False, date=None):
        self._sipanel_check_seal_integrity_for_invoice()
        # let the account.move.line provenance guard know this is the governed
        # Quotation -> Confirmation -> Create Invoice path
        return super(SaleOrder, self.with_context(sipanel_from_sale_invoice=True))._create_invoices(
            grouped=grouped, final=final, date=date)

    def _action_cancel(self):
        for o in self.filtered('sipanel_has_scopes'):
            self.env['sipanel.scope.audit.event'].log(o, 'order_cancel', summary='Scope revisions retained; nothing deleted.')
        return super()._action_cancel()

    def copy(self, default=None):
        new = super().copy(default=default)
        for order, new_order in zip(self, new):
            order._sipanel_copy_scopes_to(new_order)
        return new

    def _sipanel_copy_scopes_to(self, new_order):
        """Independent copy: latest revision -> WORKING r1; no artifacts/acceptances/keys/execution links (C3-D02, PT-09)."""
        self.ensure_one()
        src_by_line = {s.anchor_line_id.id: s for s in self.sipanel_quote_scope_ids.filtered('active')}
        for line in new_order.order_line:
            src_line_id = line.sipanel_copied_from_line_id
            src = src_by_line.get(src_line_id)
            if not src:
                continue
            rev = src.current_revision_id
            scope = self.env['sipanel.quote.scope'].create({
                'order_id': new_order.id, 'source_scope_id': src.source_scope_id.id, 'source_version_id': src.source_version_id.id,
                'is_adhoc': src.is_adhoc, 'anchor_line_id': line.id, 'is_optional': src.is_optional,
                'acceptance_state': 'offered' if src.is_optional else 'base', 'system_id': src.system_id.id,
            })
            new_rev = self.env['sipanel.quote.scope.revision'].create({
                'quote_scope_id': scope.id, 'revision': 1, 'language': rev.language, 'quote_uom_id': rev.quote_uom_id.id,
                'base_uom_id': rev.base_uom_id.id, 'uom_factor': rev.uom_factor, 'label_fa': rev.label_fa, 'label_en': rev.label_en,
                'customer_description_fa': rev.customer_description_fa, 'customer_description_en': rev.customer_description_en,
                # the duplicate keeps the ORIGINAL snapshot and its provenance: it is a
                # copy of this quotation, not a fresh resolution against today's master
                'label_resolved': rev.label_resolved, 'customer_description_resolved': rev.customer_description_resolved,
                'resolved_language': rev.resolved_language, 'source_version_checksum': rev.source_version_checksum,
                'translation_provenance': rev.translation_provenance,
                'spec_json': rev.spec_json, 'final_note': rev.final_note, 'generated_note': rev.generated_note,
                'note_manually_edited': rev.note_manually_edited, 'system_id': rev.system_id.id,
                'fx_source_currency_id': new_order.currency_id.id, 'fx_rate': 1.0, 'fx_date': fields.Date.today(), 'fx_source': 'company_currency',
            })
            scope.write({'current_revision_id': new_rev.id})
            if src.is_optional:
                new_rev.with_context(**guard_ctx('sipanel_seal_transaction')).write({'offered_scope_qty': rev.offered_scope_qty or rev.scope_qty})
            rev._copy_components_to(new_rev, keep_uids=False)
            new_rev.with_context(**guard_ctx('sipanel_note_sync')).write({'note_fingerprint': new_rev._eligible_fingerprint(), 'note_reviewed': rev.note_reviewed})
            self.env['sipanel.scope.audit.event'].log(scope, 'copy_scope', after={'from_scope_id': src.id}, revision_ref=new_rev.display_name)
        return True

    def action_sipanel_add_scope(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.env._('Add Scope'), 'res_model': 'sipanel.wizard.add.scope',
            'view_mode': 'form', 'target': 'new', 'context': {'default_order_id': self.id},
        }

    def action_sipanel_open_scopes(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.env._('Scopes'), 'res_model': 'sipanel.quote.scope',
                'view_mode': 'list,form', 'domain': [('order_id', '=', self.id)]}
