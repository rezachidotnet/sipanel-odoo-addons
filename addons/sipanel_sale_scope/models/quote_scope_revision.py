# -*- coding: utf-8 -*-
"""Scope revision snapshot: WORKING -> SENT_SEALED -> ACCEPTED_SEALED (GAP-B02, B09, B12, B16, B17; C3-D01, C3-D03, C5-D02, C7-D01)."""
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import sha256_of
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx

COST_GROUP = 'sipanel_commercial_scope_core.group_scope_cost_viewer'
REVISION_MUTABLE_AFTER_SEAL = {
    'note_reviewed', 'review_user_id', 'review_date', 'state', 'sealed_hash', 'sealed_date', 'sealed_by_id',
    'artifact_ids', 'accepted_date', 'accepted_by_id', 'acceptance_reference', 'change_order_ref',
    'message_main_attachment_id', 'message_follower_ids', 'message_ids', 'activity_ids', 'website_message_ids',
    'message_partner_ids', 'rating_ids',
}


class SipanelQuoteScopeRevision(models.Model):
    _name = 'sipanel.quote.scope.revision'
    _description = 'SIPANEL quote scope revision (snapshot)'
    _inherit = ['mail.thread']
    _order = 'quote_scope_id, revision desc'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    quote_scope_id = fields.Many2one('sipanel.quote.scope', required=True, readonly=True, ondelete='cascade', index=True)
    order_id = fields.Many2one(related='quote_scope_id.order_id', store=True, index=True)
    company_id = fields.Many2one(related='quote_scope_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    revision = fields.Integer(required=True, readonly=True, default=1)
    state = fields.Selection([('working', 'Working'), ('sent_sealed', 'Sent (sealed)'), ('accepted_sealed', 'Accepted (sealed)')],
                             required=True, default='working', readonly=True, tracking=True, index=True)
    prior_revision_id = fields.Many2one('sipanel.quote.scope.revision', readonly=True, ondelete='restrict')
    language = fields.Char(required=True, default=lambda self: self.env.user.lang or 'en_US')
    system_id = fields.Many2one('account.analytic.account', ondelete='restrict')
    scope_qty = fields.Float(digits=(16, 6), compute='_compute_scope_qty', store=True, readonly=True)
    offered_scope_qty = fields.Float(digits=(16, 6), readonly=True, help="Scope quantity of an OFFERED (qty 0) optional scope.")
    quote_uom_id = fields.Many2one('uom.uom', readonly=True, ondelete='restrict')
    base_uom_id = fields.Many2one('uom.uom', readonly=True, ondelete='restrict')
    uom_factor = fields.Float(digits=(16, 6), default=1.0, readonly=True)
    # Immutable snapshot of the master customer text. These stay plain columns on
    # purpose: a snapshot must never follow later master edits, so it is copied,
    # never translated. They now hold ONLY terms that were really stored for that
    # language - an English term is never written into the Persian column.
    label_fa = fields.Char()
    label_en = fields.Char()
    customer_description_fa = fields.Text()
    customer_description_en = fields.Text()
    # STEP 2A: the text actually resolved for `language`, plus its provenance.
    # Empty on revisions created before STEP 2A, and every reader falls back to
    # the pair above in that case, so sealed content does not move.
    label_resolved = fields.Char(readonly=True)
    customer_description_resolved = fields.Text(readonly=True)
    resolved_language = fields.Char(readonly=True,
                                    help="Language the customer text was resolved in when this revision was created.")
    source_version_checksum = fields.Char(readonly=True,
                                          help="Release checksum of the master version this snapshot came from.")
    translation_provenance = fields.Json(readonly=True,
                                         help="Which language each customer-facing term came from, and whether it was a fallback.")
    spec_json = fields.Json()
    commercial_projection_json = fields.Json(compute='_compute_commercial', store=True, readonly=True)
    net_revenue_projection = fields.Monetary(currency_field='currency_id', compute='_compute_commercial', store=True, groups=COST_GROUP)
    direct_cost_total = fields.Monetary(currency_field='currency_id', compute='_compute_costs', store=True, groups=COST_GROUP)
    derived_cost_total = fields.Monetary(currency_field='currency_id', compute='_compute_costs', store=True, groups=COST_GROUP)
    eligible_cost_total = fields.Monetary(currency_field='currency_id', compute='_compute_costs', store=True, groups=COST_GROUP)
    offered_cost_total = fields.Monetary(currency_field='currency_id', compute='_compute_costs', store=True, groups=COST_GROUP)
    missing_cost_count = fields.Integer(compute='_compute_costs', store=True)
    margin_amount = fields.Monetary(currency_field='currency_id', compute='_compute_margin', groups=COST_GROUP)
    margin_percent = fields.Float(compute='_compute_margin', digits=(16, 2), groups=COST_GROUP)
    margin_percent_na = fields.Boolean(compute='_compute_margin', groups=COST_GROUP, help="True when revenue is zero (N/A).")
    fx_source_currency_id = fields.Many2one('res.currency', readonly=True)
    fx_rate = fields.Float(digits=(16, 6), default=1.0, readonly=True)
    fx_date = fields.Date(readonly=True)
    fx_source = fields.Char(default='company_currency', readonly=True)
    generated_note = fields.Text(readonly=True)
    final_note = fields.Text()
    note_manually_edited = fields.Boolean(readonly=True)
    note_fingerprint = fields.Char(readonly=True, help="Fingerprint of the eligible payload at last generate/review.")
    note_stale = fields.Boolean(compute='_compute_note_stale', store=True)
    note_reviewed = fields.Boolean(readonly=True)
    review_user_id = fields.Many2one('res.users', readonly=True)
    review_date = fields.Datetime(readonly=True)
    sealed_hash = fields.Char(readonly=True, copy=False)
    sealed_date = fields.Datetime(readonly=True, copy=False)
    sealed_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    accepted_date = fields.Datetime(readonly=True, copy=False)
    accepted_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    acceptance_reference = fields.Char(readonly=True, copy=False)
    change_order_ref = fields.Char(readonly=True, copy=False, help="Accepted Change Order reference (BQ-03=A).")
    artifact_ids = fields.One2many('sipanel.quote.scope.artifact', 'revision_id')
    component_ids = fields.One2many('sipanel.quote.scope.component', 'revision_id')
    waiver_ids = fields.One2many('sipanel.quote.waiver', 'revision_id')

    _scope_revision_unique = models.Constraint('UNIQUE(quote_scope_id, revision)', 'Revision number must be unique per quote scope.')
    _one_working_per_scope = models.UniqueIndex("(quote_scope_id) WHERE state = 'working'")

    # ---------------------------------------------------------- computes
    @api.depends('quote_scope_id.name', 'revision')
    def _compute_name(self):
        for r in self:
            r.name = f"{r.quote_scope_id.name or '?'} r{r.revision}"

    @api.depends('quote_scope_id.anchor_line_id.product_uom_qty', 'quote_scope_id.anchor_line_id.product_uom_id', 'state', 'offered_scope_qty')
    def _compute_scope_qty(self):
        Family = self.env['sipanel.uom.family']
        for r in self:
            if r.state != 'working':
                r.scope_qty = r.scope_qty  # frozen
                continue
            line = r.quote_scope_id.anchor_line_id
            qty = line.product_uom_qty or 0.0
            if not qty and r.quote_scope_id.is_optional and r.offered_scope_qty:
                r.scope_qty = r.offered_scope_qty
                continue
            if line.product_uom_id and r.base_uom_id and line.product_uom_id != r.base_uom_id:
                if Family.check_compatible(line.product_uom_id, r.base_uom_id, raise_if_failure=False):
                    qty = line.product_uom_id._compute_quantity(qty, r.base_uom_id, round=False)
            r.scope_qty = qty

    @api.depends('quote_scope_id.anchor_line_id.price_unit', 'quote_scope_id.anchor_line_id.discount',
                 'quote_scope_id.anchor_line_id.tax_ids', 'quote_scope_id.anchor_line_id.price_subtotal',
                 'quote_scope_id.anchor_line_id.product_uom_qty', 'state')
    def _compute_commercial(self):
        for r in self:
            if r.state != 'working':
                r.commercial_projection_json = r.commercial_projection_json
                r.net_revenue_projection = r.net_revenue_projection
                continue
            r.commercial_projection_json = r._anchor_projection()
            r.net_revenue_projection = r.commercial_projection_json.get('price_subtotal', 0.0)

    def _anchor_projection(self):
        self.ensure_one()
        line = self.quote_scope_id.anchor_line_id
        if not line:
            return {}
        return {
            'line_id': line.id, 'product_id': line.product_id.id, 'qty': line.product_uom_qty, 'uom_id': line.product_uom_id.id,
            'price_unit': line.price_unit, 'discount': line.discount, 'tax_ids': sorted(line.tax_ids.ids),
            'price_subtotal': line.price_subtotal, 'currency_id': line.currency_id.id,
        }

    @api.depends('component_ids.cost_amount', 'component_ids.eligible_for_rollup', 'component_ids.cost_source',
                 'component_ids.cost_status', 'component_ids.acceptance', 'component_ids.execution_mode', 'component_ids.active_state')
    def _compute_costs(self):
        for r in self:
            comps = r.component_ids.sudo()
            elig = comps.filtered('eligible_for_rollup')
            r.direct_cost_total = sum(elig.filtered(lambda c: c.cost_source != 'derived').mapped('cost_amount'))
            r.derived_cost_total = sum(elig.filtered(lambda c: c.cost_source == 'derived').mapped('cost_amount'))
            r.eligible_cost_total = r.direct_cost_total + r.derived_cost_total
            r.offered_cost_total = sum(comps.filtered(lambda c: c.active_state == 'active' and c.responsibility == 'sipanel'
                                                      and c.acceptance == 'offered').mapped('cost_amount'))
            r.missing_cost_count = len(comps.filtered(lambda c: c.active_state == 'active' and c.cost_status == 'missing'
                                                      and c.execution_mode != 'no_action' and c.responsibility == 'sipanel'))

    @api.depends('eligible_cost_total', 'net_revenue_projection')
    def _compute_margin(self):
        for r in self:
            rs = r.sudo()
            R = rs.net_revenue_projection or 0.0
            C = rs.eligible_cost_total or 0.0
            r.margin_amount = R - C
            if float_is_zero(R, precision_digits=6):
                r.margin_percent = 0.0
                r.margin_percent_na = True
            else:
                r.margin_percent = (R - C) / R * 100.0
                r.margin_percent_na = False

    @api.depends('component_ids.final_qty', 'component_ids.customer_label_fa', 'component_ids.customer_label_en',
                 'component_ids.customer_label_resolved',
                 'component_ids.disclosure', 'component_ids.active_state', 'component_ids.placement', 'component_ids.certainty',
                 'component_ids.provisional_basis', 'component_ids.sequence', 'note_fingerprint', 'language')
    def _compute_note_stale(self):
        for r in self:
            r.note_stale = bool(r.note_fingerprint) and r._eligible_fingerprint() != r.note_fingerprint

    def _reset_review_if_stale(self):
        """Called after component changes: a stale note loses its review flag (design 2.2, PT-08)."""
        for r in self.filtered(lambda r: r.state == 'working' and r.note_reviewed):
            if r.note_fingerprint and r._eligible_fingerprint() != r.note_fingerprint:
                r.with_context(**guard_ctx('sipanel_note_sync')).write({'note_reviewed': False})

    # ---------------------------------------------------------- guards
    def _check_working(self, action):
        sealed = self.filtered(lambda r: r.state != 'working')
        if sealed and not guard(self.env, 'sipanel_seal_transaction'):
            raise UserError(self.env._("Cannot %(a)s revision %(r)s: it is %(s)s. Create an amendment revision.",
                                       a=action, r=sealed[0].display_name, s=sealed[0].state))

    def write(self, vals):
        if not guard(self.env, 'sipanel_seal_transaction'):
            content = set(vals) - REVISION_MUTABLE_AFTER_SEAL
            sealed = self.filtered(lambda r: r.state != 'working')
            if sealed and content:
                raise UserError(self.env._("Revision %(r)s is sealed; fields %(f)s are immutable. Amend instead.",
                                           r=sealed[0].display_name, f=', '.join(sorted(content))))
            if 'state' in vals:
                raise UserError(self.env._("Revision states change only through seal/accept actions."))
        if 'final_note' in vals and not guard(self.env, 'sipanel_note_sync'):
            vals = dict(vals, note_manually_edited=True)
        res = super().write(vals)
        if 'final_note' in vals and not guard(self.env, 'sipanel_note_sync'):
            for r in self.filtered(lambda r: r.state == 'working' and r.quote_scope_id.anchor_line_id):
                r.quote_scope_id.anchor_line_id.with_context(**guard_ctx('sipanel_note_sync')).write({'name': r.final_note or ''})
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_working(self):
        if any(r.state != 'working' for r in self):
            raise UserError(self.env._("Sealed revisions cannot be deleted."))

    # ---------------------------------------------------------- note engine (C0-D09, C7-D01)
    def _eligible_rows(self):
        self.ensure_one()
        rows = []
        for c in self.component_ids.sorted(lambda c: (c.sequence, c.id)):
            p = c._customer_payload(self.language)
            if p:
                rows.append(p)
        return rows

    def _eligible_fingerprint(self):
        return sha256_of(self._eligible_rows())

    def _build_generated_note(self):
        self.ensure_one()
        lang_fa = (self.language or '').startswith('fa')
        # Prefer the term resolved when the snapshot was taken. Revisions created
        # before STEP 2A have none, and keep the historical language-pair lookup,
        # so their regenerated note is unchanged.
        head = self.label_resolved or (self.label_fa if lang_fa else self.label_en) or self.label_fa or self.label_en or ''
        desc = self.customer_description_resolved or (
            self.customer_description_fa if lang_fa else self.customer_description_en) or ''
        lines = [head] if head else []
        if desc:
            lines.append(desc)
        for row in self._eligible_rows():
            txt = row['label']
            if 'qty' in row:
                qty = row['qty']
                qty_txt = ('%.6f' % qty).rstrip('0').rstrip('.')
                txt = f"{txt}: {qty_txt} {row.get('uom') or ''}".rstrip()
            if row.get('provisional_basis'):
                txt = f"{txt} ({row['provisional_basis']})"
            lines.append(f"- {txt}")
        return '\n'.join(lines)

    def action_generate_note(self, accept=True):
        for r in self:
            r._check_working('regenerate the note of')
            generated = r._build_generated_note()
            vals = {'generated_note': generated, 'note_fingerprint': r._eligible_fingerprint()}
            if accept:
                vals.update({'final_note': generated, 'note_manually_edited': False, 'note_reviewed': True,
                             'review_user_id': self.env.uid, 'review_date': fields.Datetime.now()})
            r.with_context(**guard_ctx('sipanel_note_sync')).write(vals)
            if accept and r.quote_scope_id.anchor_line_id:
                r.quote_scope_id.anchor_line_id.with_context(**guard_ctx('sipanel_note_sync')).write({'name': generated})
        return True

    def action_mark_note_reviewed(self):
        for r in self:
            r.with_context(**guard_ctx('sipanel_note_sync')).write({'note_reviewed': True, 'note_fingerprint': r._eligible_fingerprint(),
                                                          'review_user_id': self.env.uid, 'review_date': fields.Datetime.now()})
            self.env['sipanel.scope.audit.event'].log(r, 'note_reviewed', revision_ref=r.display_name)
        return True

    # ---------------------------------------------------------- language readiness (STEP 2A)
    def _missing_translation_keys(self, provenance=None):
        """Customer-facing terms with no translation in this quotation's language.

        Empty list means the quotation can be sent. A revision created before
        STEP 2A carries no provenance, so it is judged by the historical rule on
        its snapshot columns and its behaviour does not change.
        """
        self.ensure_one()
        prov = provenance if provenance is not None else (self.translation_provenance or None)
        if not prov:
            lang_fa = (self.language or '').startswith('fa')
            if lang_fa and not self.label_fa:
                return ['customer_label']
            if not lang_fa and not self.label_en:
                return ['customer_label']
            return []
        missing = []
        version = prov.get('version') or {}
        label = version.get('customer_label') or {}
        if label.get('fallback'):
            # a quotation always needs a label in its own language
            missing.append('customer_label')
        desc = version.get('customer_description') or {}
        if desc.get('fallback') and desc.get('available'):
            # the master has a description, just not in this language
            missing.append('customer_description')
        for key, cprov in sorted((prov.get('components') or {}).items()):
            if cprov.get('exempt'):
                continue          # internal-only lines never reach the customer
            if cprov.get('fallback') and cprov.get('available'):
                missing.append(f'component:{key}')
        return missing

    # ---------------------------------------------------------- seal / accept (C3-D03, C7-D04)
    def _seal_payload(self):
        self.ensure_one()
        order = self.order_id
        return {
            'order': order.name, 'scope_uid': self.quote_scope_id.scope_uid, 'revision': self.revision,
            'language': self.language, 'scope_qty': self.scope_qty,
            'anchor': self._anchor_projection() if self.state == 'working' else (self.commercial_projection_json or {}),
            'components': self._eligible_rows(),
            'final_note': self.final_note or '',
            'amount_untaxed': order.amount_untaxed, 'amount_total': order.amount_total, 'currency': order.currency_id.id,
        }

    def _current_seal_hash(self):
        """Hash of the payload as it is NOW (anchor projection re-read from the live line) for mismatch detection."""
        self.ensure_one()
        payload = self._seal_payload()
        payload['anchor'] = self._anchor_projection()
        return sha256_of(payload)

    def action_seal(self, actor='operator'):
        for r in self:
            if r.state != 'working':
                continue
            # Fail closed: never send a customer a fallback in the wrong language.
            missing = r._missing_translation_keys()
            if missing:
                raise UserError(self.env._(
                    "Cannot send %(rev)s: the customer text has no %(lang)s translation for "
                    "%(items)s. Complete the master translations, then create a new revision.",
                    rev=r.display_name, lang=r.language or '?', items=', '.join(missing)))
            payload = r._seal_payload()
            h = sha256_of(payload)
            r.with_context(**guard_ctx('sipanel_seal_transaction')).write({
                'state': 'sent_sealed', 'sealed_hash': h, 'sealed_date': fields.Datetime.now(), 'sealed_by_id': self.env.uid,
                'commercial_projection_json': payload['anchor'], 'net_revenue_projection': payload['anchor'].get('price_subtotal', 0.0),
                'scope_qty': r.scope_qty,
                'fx_source_currency_id': r.order_id.currency_id.id, 'fx_rate': 1.0, 'fx_date': fields.Date.today(), 'fx_source': 'company_currency',
            })
            r.quote_scope_id._sync_current_revision()
            r._create_artifacts(payload)
            self.env['sipanel.scope.audit.event'].log(r, 'seal', after={'sealed_hash': h, 'actor': actor}, revision_ref=r.display_name)
            r.message_post(body=self.env._("Sealed on send. Hash %s", h))
        return True

    def _create_artifacts(self, payload):
        self.ensure_one()
        order = self.order_id
        Artifact = self.env['sipanel.quote.scope.artifact'].sudo()
        # TEXT artifact: canonical customer payload (always)
        from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import canonical_json
        text = canonical_json({'components': payload['components'], 'final_note': payload['final_note'], 'language': payload['language']})
        Artifact.create({
            'revision_id': self.id, 'kind': 'text', 'language': self.language, 'content_hash': sha256_of(text),
            'content_text': text, 'amount_untaxed': order.amount_untaxed, 'amount_total': order.amount_total,
            'currency_id': order.currency_id.id, 'sent_date': fields.Datetime.now(), 'sent_by_id': self.env.uid,
        })
        # PDF artifact: native quotation report through the same call path as portal accept (best effort)
        try:
            pdf, _fmt = self.env['ir.actions.report'].sudo()._render_qweb_pdf('sale.action_report_saleorder', order.ids)
        except Exception:  # noqa: BLE001 - rendering must never break the seal transaction
            pdf, _fmt = None, None
        if pdf:
            is_pdf = (_fmt == 'pdf')
            att = self.env['ir.attachment'].sudo().create({
                'name': f"{order.name}-{self.quote_scope_id.scope_uid[:8]}-r{self.revision}.{'pdf' if is_pdf else 'html'}",
                'raw': pdf, 'mimetype': 'application/pdf' if is_pdf else 'text/html',
                'res_model': 'sipanel.quote.scope.artifact', 'res_id': 0,
            })
            art = Artifact.create({
                'revision_id': self.id, 'kind': 'pdf' if is_pdf else 'portal_html', 'language': self.language, 'attachment_id': att.id,
                'content_hash': sha256_of(pdf), 'amount_untaxed': order.amount_untaxed, 'amount_total': order.amount_total,
                'currency_id': order.currency_id.id, 'sent_date': fields.Datetime.now(), 'sent_by_id': self.env.uid,
            })
            att.write({'res_id': art.id})

    def action_accept(self, reference=None, change_order_ref=None):
        """SENT_SEALED -> ACCEPTED_SEALED after hash verification (C3-D03). Returns the revision."""
        for r in self:
            if r.state == 'accepted_sealed':
                continue
            if r.state != 'sent_sealed':
                raise UserError(self.env._("Scope %s must be sent (sealed) before it can be accepted.", r.quote_scope_id.display_name))
            current = r._current_seal_hash()
            if current != r.sealed_hash:
                raise UserError(self.env._(
                    "Scope %(s)s changed after it was sent (sealed %(a)s…, now %(b)s…). Re-send the quotation to seal a new revision.",
                    s=r.quote_scope_id.display_name, a=r.sealed_hash[:12], b=current[:12]))
            r.with_context(**guard_ctx('sipanel_seal_transaction')).write({
                'state': 'accepted_sealed', 'accepted_date': fields.Datetime.now(), 'accepted_by_id': self.env.uid,
                'acceptance_reference': reference, 'change_order_ref': change_order_ref})
            r.quote_scope_id.write({'accepted_revision_id': r.id})
            r.quote_scope_id._sync_current_revision()
            self.env['sipanel.scope.audit.event'].log(r, 'accept', after={'sealed_hash': r.sealed_hash, 'reference': reference,
                                                                            'change_order_ref': change_order_ref},
                                                      revision_ref=r.display_name)
        return True

    # ---------------------------------------------------------- amendment
    def action_amend(self):
        """Create a new WORKING revision copying components (lineage via copy_from_id); never unseal."""
        self.ensure_one()
        if self.state == 'working':
            return self
        scope = self.quote_scope_id
        if scope.revision_ids.filtered(lambda x: x.state == 'working'):
            raise UserError(self.env._("A working revision already exists for %s.", scope.display_name))
        vals = self.copy_data({'state': 'working', 'revision': self.revision + 1, 'prior_revision_id': self.id,
                               'sealed_hash': False, 'sealed_date': False, 'sealed_by_id': False, 'accepted_date': False,
                               'accepted_by_id': False, 'acceptance_reference': False, 'change_order_ref': False,
                               'note_reviewed': False})[0]
        vals.pop('component_ids', None)
        vals.pop('artifact_ids', None)
        vals.pop('waiver_ids', None)
        self.env.flush_all()  # pending state writes must reach the DB before the partial unique index is evaluated
        new = self.env['sipanel.quote.scope.revision'].with_context(**guard_ctx('sipanel_seal_transaction')).create(vals)
        self._copy_components_to(new, keep_uids=True)
        scope._sync_current_revision()
        new.with_context(**guard_ctx('sipanel_note_sync')).write({'note_fingerprint': new._eligible_fingerprint()})
        self.env['sipanel.scope.audit.event'].log(new, 'amend', after={'prior_revision_id': self.id}, revision_ref=new.display_name)
        return new

    def _copy_components_to(self, target, keep_uids=True, new_scope=False):
        """Copy components; keep occurrence_uid when amending the same scope, new uid when duplicating an order."""
        self.ensure_one()
        Comp = self.env['sipanel.quote.scope.component']
        id_map = {}
        for c in self.component_ids.sorted(lambda c: (c.sequence, c.id)):
            cvals = c.copy_data({'revision_id': target.id, 'base_component_ids': False, 'copy_from_id': c.id,
                                 'moved_from_id': False, 'moved_to_id': False})[0]
            cvals.pop('occurrence_uid', None)
            if keep_uids:
                cvals['occurrence_uid'] = c.occurrence_uid
            for k in ('unit_cost', 'cost_uom_id', 'cost_uom_factor', 'cost_source_date', 'cost_source_company_id',
                      'product_value_id', 'manual_cost_user_id', 'manual_cost_date', 'manual_cost_reason',
                      'override_reason', 'known_zero_reason'):
                cvals[k] = c.sudo()[k].id if hasattr(c.sudo()[k], 'id') else c.sudo()[k]
            id_map[c.id] = Comp.sudo().create(cvals).id
        for c in self.component_ids:
            if c.base_component_ids:
                Comp.browse(id_map[c.id]).sudo().write({'base_component_ids': [(6, 0, [id_map[b.id] for b in c.base_component_ids if b.id in id_map])]})
        return Comp.browse(list(id_map.values()))
