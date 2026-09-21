# -*- coding: utf-8 -*-
"""Quote Scope aggregate bound to one explicit anchor line (GAP-B01, C0-D02, AM-01-R2, GAP-C01..C03)."""
import uuid

from odoo import api, fields, models
from odoo.exceptions import LockError, UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import ACCEPTANCE
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import snapshot_customer_text

COST_GROUP = 'sipanel_commercial_scope_core.group_scope_cost_viewer'


class SipanelQuoteScope(models.Model):
    _name = 'sipanel.quote.scope'
    _description = 'SIPANEL quote scope'
    _inherit = ['mail.thread']
    _order = 'order_id, id'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    order_id = fields.Many2one('sale.order', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='order_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    scope_uid = fields.Char(required=True, readonly=True, copy=False, default=lambda self: str(uuid.uuid4()), index=True)
    source_scope_id = fields.Many2one('sipanel.scope', readonly=True, ondelete='restrict')
    source_version_id = fields.Many2one('sipanel.scope.version', readonly=True, ondelete='restrict')
    is_adhoc = fields.Boolean(readonly=True)
    anchor_line_id = fields.Many2one('sale.order.line', required=True, readonly=True, ondelete='restrict', index=True)
    optional_section_line_id = fields.Many2one('sale.order.line', ondelete='set null', help="Presentation only.")
    is_optional = fields.Boolean(readonly=True, help="Placement OWN_LINE + acceptance axis OFFERED/ACCEPTED/DECLINED (AM-01-R2).")
    acceptance_state = fields.Selection(ACCEPTANCE, required=True, default='base', readonly=True, tracking=True)
    acceptance_reference = fields.Char(readonly=True)
    current_revision_id = fields.Many2one('sipanel.quote.scope.revision', readonly=True, ondelete='restrict')
    accepted_revision_id = fields.Many2one('sipanel.quote.scope.revision', readonly=True, ondelete='restrict')
    state = fields.Selection([('draft', 'Draft'), ('sent', 'Sent'), ('accepted', 'Accepted'), ('amending', 'Amending'),
                              ('cancelled', 'Cancelled')], compute='_compute_state', store=True)
    revision_ids = fields.One2many('sipanel.quote.scope.revision', 'quote_scope_id')
    revision_count = fields.Integer(compute='_compute_counts')
    system_id = fields.Many2one('account.analytic.account', ondelete='restrict')
    active = fields.Boolean(default=True)
    readiness_text = fields.Text(compute='_compute_readiness')
    readiness_state = fields.Selection([('ok', 'OK'), ('warnings', 'Warnings'), ('blocked', 'Blocked')], compute='_compute_readiness')
    eligible_cost_total = fields.Monetary(related='current_revision_id.eligible_cost_total', currency_field='currency_id', groups=COST_GROUP)
    margin_amount = fields.Monetary(related='current_revision_id.margin_amount', currency_field='currency_id', groups=COST_GROUP)
    margin_percent = fields.Float(related='current_revision_id.margin_percent', groups=COST_GROUP)

    _scope_uid_unique = models.Constraint('UNIQUE(scope_uid)', 'Scope uid must be unique.')
    _anchor_line_unique = models.Constraint('UNIQUE(anchor_line_id)', 'A sale order line can anchor at most one Scope (C0-D02).')

    # ------------------------------------------------------------ computes
    @api.depends('order_id.name', 'source_scope_id.code', 'current_revision_id.label_en', 'current_revision_id.label_fa')
    def _compute_name(self):
        for s in self:
            label = s.source_scope_id.code or s.current_revision_id.label_en or s.current_revision_id.label_fa or 'ad-hoc'
            s.name = f"{s.order_id.name or '?'} / {label}"

    @api.depends('revision_ids')
    def _compute_counts(self):
        for s in self:
            s.revision_count = len(s.revision_ids)

    @api.depends('current_revision_id.state', 'accepted_revision_id', 'order_id.state', 'active')
    def _compute_state(self):
        for s in self:
            if not s.active or s.order_id.state == 'cancel':
                s.state = 'cancelled'
            elif s.accepted_revision_id and s.current_revision_id.state == 'working':
                s.state = 'amending'
            elif s.current_revision_id.state == 'accepted_sealed':
                s.state = 'accepted'
            elif s.current_revision_id.state == 'sent_sealed':
                s.state = 'sent'
            else:
                s.state = 'draft'

    def _compute_readiness(self):
        for s in self:
            issues = s._readiness_issues()
            s.readiness_text = '\n'.join(f"[{i['level'].upper()}] {i['code']}: {i['msg']}" for i in issues) or self.env._('Ready')
            s.readiness_state = 'blocked' if any(i['level'] == 'block' for i in issues) else ('warnings' if issues else 'ok')

    # ------------------------------------------------------------ constraints
    @api.constrains('anchor_line_id', 'order_id')
    def _check_anchor(self):
        for s in self:
            line = s.anchor_line_id
            if line.order_id != s.order_id:
                raise ValidationError(self.env._("Anchor line must belong to the same order."))
            if line.display_type or line.combo_item_id or line.linked_line_id or line.is_downpayment:
                raise ValidationError(self.env._("Sections, notes, combo items, linked lines and down payments cannot anchor a Scope (SV-06)."))
            if line.product_type == 'combo':
                raise ValidationError(self.env._("A combo product cannot anchor a Scope in MVP."))

    # ------------------------------------------------------------ helpers
    def _sync_current_revision(self):
        for s in self:
            working = s.revision_ids.filtered(lambda r: r.state == 'working')
            current = working or s.revision_ids.sorted('revision')[-1:]
            if current and s.current_revision_id != current:
                s.write({'current_revision_id': current.id})

    def _readiness_issues(self):
        """C4-D02 readiness drawer: blocking / warning issues for Send."""
        self.ensure_one()
        _ = self.env._
        issues = []
        add = lambda code, msg, level='block': issues.append({'code': code, 'msg': msg, 'level': level})
        rev = self.current_revision_id
        if not rev:
            add('NO_REVISION', _("No revision."))
            return issues
        order = self.order_id
        Config = self.env['sipanel.config']
        if Config.company_currency_only() and order.currency_id != order.company_id.currency_id:
            add('CURRENCY', _("Foreign-currency quotations are blocked in MVP (BQ-09)."))
        missing = rev._missing_translation_keys()
        if missing:
            add('LABEL_LANG', _("Customer text has no %(lang)s translation for: %(items)s (BQ-01).",
                                lang=rev.language or '?', items=', '.join(missing)))
        if rev.state != 'working':
            return issues
        comps = rev.component_ids.sudo().filtered(lambda c: c.active_state == 'active')
        for c in comps:
            if c.basis == 'manual' and not c.manual_qty_set:
                add('MANUAL_QTY', _("Manual quantity missing for %s.", c.display_name))
            if c.override_stale:
                add('OVERRIDE_STALE', _("Stale override on %s: confirm or clear it.", c.display_name))
            if c.kind == 'estimate_only' and c.resolution_state == 'open':
                add('ESTIMATE_ONLY', _("%s needs resolution.", c.display_name), 'warn')
            if c.disclosure == 'customer_eligible' and not (
                    c.customer_label_resolved or c.customer_label_fa or c.customer_label_en):
                add('LABEL', _("%s has no customer label; it is skipped in the note.", c.display_name), 'warn')
        approved = rev.waiver_ids.filtered(lambda w: w.state == 'approved').mapped('waiver_type')
        if rev.waiver_ids.filtered(lambda w: w.state == 'pending'):
            add('WAIVER_PENDING', _("A waiver is pending joint approval (BQ-02)."))
        if rev.missing_cost_count and 'missing_estimate' not in approved:
            add('MISSING_COST', _("%s component(s) have missing cost; a joint waiver is required.", rev.missing_cost_count))
        rs = rev.sudo()
        if not rs.margin_percent_na and rs.margin_amount < 0 and 'negative_margin' not in approved:
            add('NEGATIVE_MARGIN', _("Negative margin; a joint Finance+Sales waiver is required (BQ-02)."))
        floor = Config.min_margin_pct()
        if floor is not None and not rs.margin_percent_na and rs.margin_percent < floor and 'below_min_margin' not in approved:
            add('BELOW_MIN_MARGIN', _("Margin below the configured floor; waiver required."))
        if rev.note_stale and not rev.note_reviewed:
            add('NOTE_STALE', _("Customer note is stale and not reviewed."))
        if not rev.final_note:
            add('NOTE_EMPTY', _("Customer note is empty; generate it."), 'warn')
        # STEP 2B: a separately-billable component that cannot become a real,
        # invoiceable customer line keeps the quotation working
        for code, msg in rev._projection_blocking_issues():
            add(code, msg)
        recon = rev.reconciliation_json or {}
        for problem in recon.get('problems', []):
            add('SB_RECONCILIATION', _("Scope line reconciliation: %s", problem))
        return issues

    # ------------------------------------------------------------ governed acceptance transition (AM-01-R2, GAP-C02/C03)
    def _transition_acceptance(self, new_state, actor='operator', revision_id=None, seal_hash=None, reason=None):
        """Single governed transition. Idempotent. Binds to the current sealed revision."""
        self.ensure_one()
        _ = self.env._
        if not self.is_optional:
            raise UserError(_("Scope %s is not optional; its quantity is not a customer choice.", self.display_name))
        rev = self.current_revision_id
        if rev.state != 'sent_sealed':
            raise UserError(_("Scope %s has no current sealed revision; acceptance is not possible.", self.display_name))
        if actor == 'portal':
            if not revision_id or int(revision_id) != rev.id or not seal_hash or seal_hash != rev.sealed_hash:
                raise UserError(_("This quotation link is no longer current."))
        if new_state not in ('offered', 'accepted', 'declined'):
            raise UserError(_("Invalid acceptance state."))
        allowed = {'offered': ('accepted', 'declined'), 'accepted': ('declined', 'offered'), 'declined': ('offered', 'accepted')}
        if new_state == self.acceptance_state:
            return True  # idempotent
        if new_state not in allowed[self.acceptance_state]:
            raise UserError(_("Transition %(a)s -> %(b)s is not allowed.", a=self.acceptance_state, b=new_state))
        line = self.anchor_line_id
        before = {'acceptance_state': self.acceptance_state, 'qty': line.product_uom_qty}
        qty = rev.scope_qty if new_state == 'accepted' else 0.0
        if rev.quote_uom_id and rev.base_uom_id and rev.quote_uom_id != rev.base_uom_id and line.product_uom_id == rev.quote_uom_id:
            qty = rev.base_uom_id._compute_quantity(qty, rev.quote_uom_id, round=False) if qty else 0.0
        with self.env.protecting([line._fields['discount'], line._fields['price_unit']], line):
            line.with_context(**guard_ctx('sipanel_governed_transition')).write({'product_uom_qty': qty})
        self.write({'acceptance_state': new_state,
                    'acceptance_reference': f"{actor}:{rev.id}:{uuid.uuid4().hex[:12]}" if new_state == 'accepted' else self.acceptance_reference})
        # An optional scope's separately-billable lines follow the same decision:
        # zero while the option is only offered, governed quantity once accepted.
        # Repeating the transition is idempotent, so retries cannot duplicate or
        # double-count anything.
        self._sync_optional_projection(rev, accepted=new_state == 'accepted')
        self.env['sipanel.scope.audit.event'].log(
            self, 'acceptance_transition', before=before, after={'acceptance_state': new_state, 'qty': qty, 'actor': actor},
            reason=reason, revision_ref=rev.display_name)
        return True

    def _sync_optional_projection(self, rev, accepted):
        """Propagate an optional acceptance to the projected lines of that scope."""
        self.ensure_one()
        lines = self.env['sale.order.line'].search([
            ('sipanel_source_revision_id', '=', rev.id), ('sipanel_is_generated', '=', True)])
        for line in lines:
            comp = line.sipanel_source_component_id
            qty = (comp.final_qty or 0.0) if accepted else 0.0
            if abs((line.product_uom_qty or 0.0) - qty) > 1e-6:
                with self.env.protecting([line._fields['discount'], line._fields['price_unit']], line):
                    line.with_context(**guard_ctx('sipanel_projection')).write({'product_uom_qty': qty})
        return True

    # ------------------------------------------------------------ actions
    def action_amend(self):
        self.ensure_one()
        new = self.current_revision_id.action_amend()
        return {'type': 'ir.actions.act_window', 'res_model': 'sipanel.quote.scope.revision', 'res_id': new.id, 'view_mode': 'form'}

    def action_accept_change_order(self, change_order_ref):
        """BQ-03=A: an accepted Change Order makes the current working revision the new baseline (internal path)."""
        self.ensure_one()
        if not change_order_ref:
            raise UserError(self.env._("An accepted Change Order reference is required."))
        rev = self.current_revision_id
        if rev.state == 'working':
            rev.action_seal(actor='change_order')
        rev.action_accept(reference=f"change_order:{change_order_ref}", change_order_ref=change_order_ref)
        return True

    def action_open_current_revision(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sipanel.quote.scope.revision', 'res_id': self.current_revision_id.id, 'view_mode': 'form'}

    def action_open_revisions(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.env._('Revisions'), 'res_model': 'sipanel.quote.scope.revision',
                'view_mode': 'list,form', 'domain': [('quote_scope_id', '=', self.id)]}

    @api.ondelete(at_uninstall=False)
    def _unlink_except_unsealed(self):
        for s in self:
            if s.revision_ids.filtered(lambda r: r.state != 'working'):
                raise UserError(self.env._("Scope %s has sealed revisions; archive it instead.", s.display_name))

    # ------------------------------------------------------------ creation from a released version (Add Scope)
    @api.model
    def _create_from_version(self, order, version, scope_qty, quote_uom, optional=False, section_line=None, system=None, sequence=None):
        """One transaction: anchor line + quote scope + revision 1 + component snapshots (C0-D02, C0-D04)."""
        _ = self.env._
        if version.state != 'released':
            raise UserError(_("Only RELEASED versions can be added to a quotation."))
        if version.company_id != order.company_id:
            raise UserError(_("Scope version belongs to another company."))
        if self.env['sipanel.config'].company_currency_only() and order.currency_id != order.company_id.currency_id:
            raise UserError(_("Foreign-currency quotations cannot carry a Scope in MVP (BQ-09)."))
        if order.state not in ('draft', 'sent'):
            raise UserError(_("Scopes can only be added to quotations (draft/sent)."))
        Family = self.env['sipanel.uom.family']
        quote_uom = quote_uom or version.base_uom_id
        Family.check_compatible(quote_uom, version.base_uom_id)
        qty_base = Family.convert(scope_qty, quote_uom, version.base_uom_id)
        # quotation language: customer note and unit-name snapshots are rendered in this language (D-02, BQ-01)
        lang = order.partner_id.lang or self.env.user.lang or 'en_US'
        label_terms, label_resolved, label_prov = snapshot_customer_text(version, 'customer_label', lang)
        desc_terms, desc_resolved, desc_prov = snapshot_customer_text(version, 'customer_description', lang)
        line_vals = {
            'order_id': order.id, 'product_id': version.anchor_product_id.id,
            'product_uom_qty': 0.0 if optional else qty_base, 'product_uom_id': version.base_uom_id.id,
            # a draft may fall back so the operator still sees a usable line; the
            # fallback is recorded and blocks the seal (BQ-01, STEP 2A)
            'name': label_resolved or label_terms.get('en_US') or label_terms.get('fa_IR') or '',
        }
        if sequence is not None:
            line_vals['sequence'] = sequence
        elif section_line:
            line_vals['sequence'] = section_line.sequence + 1
        line = self.env['sale.order.line'].with_context(**guard_ctx('sipanel_anchor_create')).create(line_vals)
        scope = self.create({
            'order_id': order.id, 'source_scope_id': version.scope_id.id, 'source_version_id': version.id,
            'anchor_line_id': line.id, 'is_optional': optional, 'optional_section_line_id': section_line.id if section_line else False,
            'acceptance_state': 'offered' if optional else 'base', 'system_id': system.id if system else False,
        })
        rev = self.env['sipanel.quote.scope.revision'].create({
            'quote_scope_id': scope.id, 'revision': 1, 'language': lang,
            'quote_uom_id': quote_uom.id, 'base_uom_id': version.base_uom_id.id,
            'uom_factor': Family.convert(1.0, quote_uom, version.base_uom_id),
            'label_fa': label_terms.get('fa_IR', False), 'label_en': label_terms.get('en_US', False),
            'customer_description_fa': desc_terms.get('fa_IR', False), 'customer_description_en': desc_terms.get('en_US', False),
            'label_resolved': label_resolved, 'customer_description_resolved': desc_resolved,
            'resolved_language': lang, 'source_version_checksum': version.release_checksum,
            'system_id': system.id if system else False,
            'fx_source_currency_id': order.currency_id.id, 'fx_rate': 1.0, 'fx_date': fields.Date.today(), 'fx_source': 'company_currency',
        })
        scope.write({'current_revision_id': rev.id})
        if optional:
            # OFFERED scope: snapshot quantities are computed on the offered scope qty, stored on the revision
            rev.with_context(**guard_ctx('sipanel_seal_transaction')).write({'offered_scope_qty': qty_base})
        Comp = self.env['sipanel.quote.scope.component'].sudo()
        id_map = {}
        comp_prov = {}
        for l in version.recipe_line_ids.sorted(lambda l: (l.sequence, l.id)):
            c_terms, c_resolved, c_prov = snapshot_customer_text(l, 'customer_label', lang)
            # an internal-only line is never shown to the customer, so a missing
            # customer translation is not a defect for it
            c_prov['exempt'] = (l.disclosure == 'internal_only') or not l.customer_eligible
            comp_prov[l.occurrence_key] = c_prov
            cvals = {
                'revision_id': rev.id, 'source_occurrence_key': l.occurrence_key, 'source_line_id': l.id, 'origin': 'master',
                'sequence': l.sequence, 'kind': l.kind, 'product_id': l.product_id.id, 'description': l.internal_description,
                'customer_label_fa': c_terms.get('fa_IR', False), 'customer_label_en': c_terms.get('en_US', False),
                'customer_label_resolved': c_resolved, 'label_provenance': c_prov, 'spec_json': l.spec_json,
                'uom_id': l.uom_id.id, 'uom_name_snapshot': l.uom_id.with_context(lang=lang).name, 'dimension_family': l.dimension_family,
                'basis': l.basis, 'rate': l.rate, 'fixed_qty': l.fixed_qty, 'percent': l.percent,
                'manual_qty': l.manual_qty_default, 'manual_qty_set': bool(l.basis == 'manual' and l.manual_qty_default),
                'rounding_increment': l.rounding_increment, 'rounding_mode': l.rounding_mode,
                'activity_id': l.activity_id.id, 'system_id': system.id if system else False,
                'execution_mode': l.execution_mode, 'no_action_reason': l.no_action_reason,
                'responsibility': l.responsibility, 'placement': l.placement, 'certainty': l.certainty, 'disclosure': l.disclosure,
                'resolution_owner_id': l.resolution_owner_id.id, 'resolution_note': l.resolution_note,
                'resolution_state': 'open' if l.kind == 'estimate_only' else 'not_required',
            }
            # governed selling price snapshot: only an own-line component has one
            cvals.update(Comp._sell_price_snapshot_vals(l.product_id, order, l.uom_id, l.placement))
            if l.responsibility == 'customer':
                cvals['cost_source'] = 'not_applicable'
            elif l.cost_policy == 'derived':
                cvals['cost_source'] = 'derived'
            elif l.cost_policy == 'manual_estimate':
                cvals.update({'cost_source': 'manual_estimate', 'unit_cost': l.manual_cost_default, 'cost_uom_id': l.uom_id.id,
                              'cost_uom_factor': 1.0, 'manual_cost_user_id': self.env.uid, 'manual_cost_date': fields.Datetime.now(),
                              'manual_cost_reason': _('Master default manual estimate')})
            elif l.product_id:
                cvals.update(Comp._product_cost_snapshot_vals(l.product_id, order.company_id, l.uom_id))
            else:
                cvals.update({'cost_source': 'product_cost', 'unit_cost': 0.0})
            id_map[l.id] = Comp.create(cvals).id
        for l in version.recipe_line_ids:
            if l.base_line_ids:
                Comp.browse(id_map[l.id]).write({'base_component_ids': [(6, 0, [id_map[b.id] for b in l.base_line_ids if b.id in id_map])]})
        provenance = {'language': lang, 'version': {'customer_label': label_prov,
                                                    'customer_description': desc_prov},
                      'components': comp_prov}
        provenance['missing'] = rev._missing_translation_keys(provenance)
        rev.with_context(**guard_ctx('sipanel_seal_transaction')).write({'translation_provenance': provenance})
        rev.action_generate_note(accept=True)
        if provenance['missing']:
            # draft may proceed on the fallback, but the gap must be visible now
            # and it will block the seal (STEP 2A language readiness)
            scope.message_post(body=self.env._(
                "Customer text is missing a %(lang)s translation for: %(items)s. "
                "The draft uses a fallback; this quotation cannot be sent until the "
                "master translations are completed.",
                lang=lang, items=', '.join(provenance['missing'])))
        self.env['sipanel.scope.audit.event'].log(scope, 'add_scope', after={'version_id': version.id, 'scope_qty': qty_base,
                                                                              'optional': optional,
                                                                              'resolved_language': lang,
                                                                              'missing_translations': provenance['missing']},
                                                  revision_ref=rev.display_name)
        return scope
