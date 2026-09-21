# -*- coding: utf-8 -*-
"""Scope version: DRAFT -> RELEASED -> SUPERSEDED (GAP-A02, GAP-A03, GAP-A09; C1-D02, C1-D09)."""
from odoo import api, fields, models
from odoo.exceptions import LockError, UserError, ValidationError
from .sipanel_tools import guard, guard_ctx

from .sipanel_tools import (CERTAINTY, DIMENSION_FAMILY, DISCLOSURE, OWNER_MODE, PLACEMENT,
                            RESPONSIBILITY, PERCENT_BASES, find_cycle, sha256_of,
                            stored_translations, translation_map)

# Fields that may change on a RELEASED/SUPERSEDED version (non-content bookkeeping).
VERSION_MUTABLE_AFTER_RELEASE = {
    'state', 'released_by_id', 'released_date', 'release_checksum', 'checksum_algo', 'superseded_by_id',
    'message_main_attachment_id', 'message_follower_ids', 'message_ids', 'activity_ids',
    'rating_ids', 'website_message_ids', 'message_partner_ids', 'activity_user_id',
    'activity_type_id', 'activity_date_deadline', 'activity_summary', 'my_activity_date_deadline',
    'activity_exception_decoration', 'activity_state', 'requires_quote_resolution',
}


class SipanelScopeVersion(models.Model):
    _name = 'sipanel.scope.version'
    _description = 'SIPANEL Scope version (master recipe container)'
    _inherit = ['mail.thread']
    _order = 'scope_id, revision desc'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    scope_id = fields.Many2one('sipanel.scope', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='scope_id.company_id', store=True, index=True)
    revision = fields.Integer(required=True, readonly=True, default=0, copy=False)
    parent_version_id = fields.Many2one('sipanel.scope.version', readonly=True, ondelete='restrict', copy=False)
    state = fields.Selection([('draft', 'Draft'), ('released', 'Released'), ('superseded', 'Superseded')],
                             required=True, default='draft', readonly=True, copy=False, tracking=True, index=True)
    # STEP 2A: one native translatable field per customer-facing text. The
    # operator edits en_US in the form and every other active language through
    # Odoo's standard translation dialog. The legacy *_fa / *_en columns are
    # dormant in the database and are no longer business fields.
    customer_label = fields.Char(string='Customer label', translate=True, tracking=True)
    customer_description = fields.Text(string='Customer description', translate=True)
    internal_description = fields.Text()
    base_uom_id = fields.Many2one('uom.uom', required=True, ondelete='restrict')
    dimension_family = fields.Selection(DIMENSION_FAMILY, required=True, default='count')
    anchor_product_id = fields.Many2one('product.product', ondelete='restrict',
                                        domain="[('sale_ok', '=', True)]")
    anchor_owner_mode = fields.Selection(OWNER_MODE, default='component_bridge_owner')
    all_systems = fields.Boolean(default=False)
    system_ids = fields.Many2many('account.analytic.account', 'sipanel_version_system_rel', 'version_id', 'account_id',
                                  string='Applicable systems')
    note_template = fields.Text()
    default_responsibility = fields.Selection(RESPONSIBILITY, required=True, default='sipanel')
    default_placement = fields.Selection(PLACEMENT, required=True, default='included_parent')
    default_certainty = fields.Selection(CERTAINTY, required=True, default='firm')
    default_disclosure = fields.Selection(DISCLOSURE, required=True, default='customer_eligible')
    recipe_line_ids = fields.One2many('sipanel.scope.recipe.line', 'version_id', copy=False)
    recipe_line_count = fields.Integer(compute='_compute_recipe_line_count')
    released_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    released_date = fields.Datetime(readonly=True, copy=False)
    release_checksum = fields.Char(readonly=True, copy=False)
    checksum_algo = fields.Char(readonly=True, copy=False, default='v2',
                                help="Algorithm the stored release checksum was produced with. "
                                     "v1 predates native translations; v2 hashes the full stored "
                                     "translation map. Existing releases keep v1 so their recorded "
                                     "checksum stays verifiable.")
    superseded_by_id = fields.Many2one('sipanel.scope.version', readonly=True, copy=False, ondelete='restrict')
    requires_quote_resolution = fields.Boolean(readonly=True, copy=False,
                                               help="Contains ESTIMATE_ONLY lines; can be quoted but never 'ready to execute'.")
    is_current = fields.Boolean(compute='_compute_is_current')
    usage_count = fields.Integer(compute='_compute_usage_count')

    _scope_revision_unique = models.Constraint('UNIQUE(scope_id, revision)', 'Revision number must be unique per scope.')
    _one_released_per_scope = models.UniqueIndex("(scope_id) WHERE state = 'released'")

    # ------------------------------------------------------------------ computes
    @api.depends('scope_id.code', 'revision')
    def _compute_name(self):
        for v in self:
            v.name = f"{v.scope_id.code or '?'} v{v.revision or 0}"

    @api.depends('recipe_line_ids')
    def _compute_recipe_line_count(self):
        for v in self:
            v.recipe_line_count = len(v.recipe_line_ids)

    @api.depends('scope_id.current_version_id')
    def _compute_is_current(self):
        for v in self:
            v.is_current = v.scope_id.current_version_id == v

    def _compute_usage_count(self):
        QuoteScope = self.env['sipanel.quote.scope'] if 'sipanel.quote.scope' in self.env else None
        for v in self:
            v.usage_count = QuoteScope.search_count([('source_version_id', '=', v.id)]) if QuoteScope is not None else 0

    # ------------------------------------------------------------------ CRUD guards
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('revision'):
                scope_id = vals.get('scope_id')
                last = self.search([('scope_id', '=', scope_id)], order='revision desc', limit=1)
                vals['revision'] = (last.revision or 0) + 1
            if vals.get('state', 'draft') != 'draft' and not guard(self.env, 'sipanel_release_transaction'):
                raise UserError(self.env._("A version can only be created in Draft state."))
        return super().create(vals_list)

    def write(self, vals):
        if not guard(self.env, 'sipanel_release_transaction'):
            content_keys = set(vals) - VERSION_MUTABLE_AFTER_RELEASE
            frozen = self.filtered(lambda v: v.state != 'draft')
            if frozen and content_keys:
                raise UserError(self.env._(
                    "Version %(name)s is %(state)s and immutable. Create a new version instead (fields: %(f)s).",
                    name=frozen[0].display_name, state=frozen[0].state, f=', '.join(sorted(content_keys))))
            if 'state' in vals:
                raise UserError(self.env._("State transitions are only possible through the release action."))
        return super().write(vals)

    def update_field_translations(self, field_name, translations, *args, **kwargs):
        """Released content is immutable in every language.

        `write` already covers a write made under a language context, an import,
        an RPC call or `sudo()` - the guard is a process-local token, not a
        permission - but Odoo's translation dialog and `update_field_translations`
        reach the jsonb column without going through `write`, so the same rule is
        enforced here. Otherwise a released customer label could be rewritten in
        Persian while the English term, and the release checksum, stayed put.
        """
        if self._fields[field_name].translate and not guard(self.env, 'sipanel_release_transaction'):
            frozen = self.filtered(lambda v: v.state != 'draft')
            if frozen:
                raise UserError(self.env._(
                    "Version %(name)s is %(state)s; its %(field)s translations are immutable. "
                    "Create a new version instead.",
                    name=frozen[0].display_name, state=frozen[0].state, field=field_name))
        return super().update_field_translations(field_name, translations, *args, **kwargs)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        for v in self:
            if v.state != 'draft':
                raise UserError(self.env._("Released or superseded versions cannot be deleted (%s).", v.display_name))
            if v.usage_count:
                raise UserError(self.env._("Version %s is referenced by quotations and cannot be deleted.", v.display_name))

    def copy(self, default=None):
        if not guard(self.env, 'sipanel_allow_copy'):
            raise UserError(self.env._("Use 'New version' or 'Duplicate as new Scope' (C1-D07)."))
        return super().copy(default=default)

    # ------------------------------------------------------------------ actions
    def action_new_version(self):
        """Copy content into a new DRAFT of the same identity (never 'unrelease')."""
        self.ensure_one()
        new = self._copy_content_to(self.scope_id, parent=self)
        self.env['sipanel.scope.audit.event'].log(new, 'new_version', after={'parent_version_id': self.id})
        return new._action_open()

    def _copy_content_to(self, scope, parent=None):
        self.ensure_one()
        vals = self.with_context(**guard_ctx('sipanel_allow_copy')).copy_data({
            'scope_id': scope.id, 'state': 'draft', 'revision': 0,
            'parent_version_id': parent.id if parent else False,
        })[0]
        vals.pop('recipe_line_ids', None)
        new = self.env['sipanel.scope.version'].create(vals)
        key_map = {}
        for line in self.recipe_line_ids.sorted('sequence'):
            lvals = line.copy_data({'version_id': new.id, 'base_line_ids': False})[0]
            lvals.pop('occurrence_key', None)
            new_line = self.env['sipanel.scope.recipe.line'].create(lvals)
            key_map[line.id] = new_line.id
        for line in self.recipe_line_ids:
            if line.base_line_ids:
                new_line = self.env['sipanel.scope.recipe.line'].browse(key_map[line.id])
                new_line.base_line_ids = [(6, 0, [key_map[b.id] for b in line.base_line_ids if b.id in key_map])]
        return new

    def _action_open(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'current'}

    def action_release(self):
        """Single-transaction release with identity lock (C1-D09, SV-07)."""
        for version in self:
            version._release_one()
        return True

    def _release_one(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(self.env._("Only draft versions can be released."))
        try:
            self.scope_id.lock_for_update()
        except LockError:
            raise UserError(self.env._("A release of scope %s is already in progress; please retry.", self.scope_id.code))
        issues = self._release_validations()
        blocking = [i for i in issues if i['level'] == 'block']
        if blocking:
            raise ValidationError(self.env._("Release blocked:\n%s", '\n'.join(f"- [{i['rule']}] {i['msg']}" for i in blocking)))
        previous = self.scope_id.current_version_id
        checksum = self._compute_content_checksum()
        ctx = self.with_context(**guard_ctx('sipanel_release_transaction'))
        if previous and previous != self:
            ctx.browse(previous.id).write({'state': 'superseded', 'superseded_by_id': self.id})
            self.env.flush_all()  # partial unique index (one released per scope) is evaluated in SQL
        ctx.browse(self.id).write({
            'state': 'released', 'released_by_id': self.env.uid, 'released_date': fields.Datetime.now(),
            'release_checksum': checksum,
            'requires_quote_resolution': any(i['rule'] == 'R9' for i in issues),
        })
        self.scope_id.write({'current_version_id': self.id})
        self.env['sipanel.scope.audit.event'].log(
            self, 'release', before={'previous_version_id': previous.id if previous else None},
            after={'release_checksum': checksum}, revision_ref=self.display_name)
        self.message_post(body=self.env._("Released. Checksum %s", checksum))
        for w in issues:
            if w['level'] == 'warn':
                self.message_post(body=self.env._("Release warning [%(rule)s]: %(msg)s", rule=w['rule'], msg=w['msg']))
        return True

    def _content_checksum_payload(self):
        """v2 payload. Customer-facing master text participates in released content,
        so the COMPLETE stored translation map goes in, in deterministic language
        order - adding, changing or removing any translation changes the checksum."""
        self.ensure_one()
        payload = {
            'scope': self.scope_id.code,
            'revision': self.revision,
            'customer_label': translation_map(self, 'customer_label'),
            'customer_description': translation_map(self, 'customer_description'),
            'base_uom': self.base_uom_id.id, 'dimension_family': self.dimension_family,
            'anchor_product': self.anchor_product_id.id, 'anchor_owner_mode': self.anchor_owner_mode,
            'all_systems': self.all_systems, 'systems': sorted(self.system_ids.ids),
            'defaults': [self.default_responsibility, self.default_placement, self.default_certainty, self.default_disclosure],
            'lines': [l._content_payload() for l in self.recipe_line_ids.sorted(lambda l: (l.sequence, l.id))],
        }
        return payload

    def _compute_content_checksum(self):
        return sha256_of(self._content_checksum_payload())

    def verify_release_checksum(self):
        """Recompute with the algorithm this version was released under.

        v1 releases predate native translations; recomputing them with v2 would
        report a false mismatch, so their recorded checksum is verified against
        the legacy payload read from the dormant columns.
        """
        self.ensure_one()
        if self.checksum_algo == 'v1':
            return self.release_checksum == self._compute_content_checksum_v1()
        return self.release_checksum == self._compute_content_checksum()

    def _compute_content_checksum_v1(self):
        """Historical algorithm, kept only to verify releases made before STEP 2A.

        Odoo 19 drops the column of a removed field once the module is updated,
        so the legacy *_fa / *_en columns no longer exist after this migration.
        The v1 payload is instead reconstructed from the migrated translation
        map, which is exact because the migration is a pure relabelling:
        FA -> fa_IR, EN -> en_US, and an absent term reproduces the `False` an
        empty legacy column used to read as. If a translation is later edited,
        this reconstruction stops matching the recorded checksum - which is the
        detection we want, not a bug.
        """
        self.ensure_one()
        label = stored_translations(self, 'customer_label')
        desc = stored_translations(self, 'customer_description')
        payload = {
            'scope': self.scope_id.code,
            'revision': self.revision,
            'label_fa': label.get('fa_IR') or False,
            'label_en': label.get('en_US') or False,
            'customer_description_fa': desc.get('fa_IR') or False,
            'customer_description_en': desc.get('en_US') or False,
            'base_uom': self.base_uom_id.id, 'dimension_family': self.dimension_family,
            'anchor_product': self.anchor_product_id.id, 'anchor_owner_mode': self.anchor_owner_mode,
            'all_systems': self.all_systems, 'systems': sorted(self.system_ids.ids),
            'defaults': [self.default_responsibility, self.default_placement, self.default_certainty, self.default_disclosure],
            'lines': [l._content_payload_v1() for l in self.recipe_line_ids.sorted(lambda l: (l.sequence, l.id))],
        }
        return sha256_of(payload)

    # ------------------------------------------------------------------ release validations R1..R12
    def _release_validations(self):
        self.ensure_one()
        issues = []
        _ = self.env._
        add = lambda rule, msg, level='block': issues.append({'rule': rule, 'msg': msg, 'level': level})
        lines = self.recipe_line_ids
        company = self.company_id
        # R1 company
        for l in lines:
            if l.product_id and l.product_id.company_id and l.product_id.company_id != company:
                add('R1', _("Product %s belongs to another company.", l.product_id.display_name))
        for acc in self.system_ids | lines.mapped('activity_id'):
            if acc.company_id and acc.company_id != company:
                add('R1', _("Analytic account %s belongs to another company.", acc.display_name))
        # R2 labels: one native field, checked across the stored translations
        label_terms = stored_translations(self, 'customer_label')
        if not label_terms:
            add('R2', _("A customer label is required."))
        else:
            missing = [code for code, _n in self.env['res.lang'].get_installed()
                       if code not in label_terms]
            if missing:
                add('R2', _("Customer label has no translation for: %s. Quotations in those "
                            "languages cannot be sealed until it is added.",
                            ', '.join(sorted(missing))), 'warn')
        for line in lines.filtered(lambda l: l.disclosure != 'internal_only' and l.customer_eligible):
            if not stored_translations(line, 'customer_label'):
                add('R2', _("Customer-eligible line %s has no customer label.", line.display_name))
        # R3 base uom
        if not self.base_uom_id.active:
            add('R3', _("Base unit is inactive."))
        Family = self.env['sipanel.uom.family']
        if Family.family_of(self.base_uom_id) not in (False, self.dimension_family):
            add('R3', _("Base unit family does not match the version dimension family."))
        # R4 anchor product / owner mode
        if not self.anchor_product_id:
            add('R4', _("Anchor product is required."))
        else:
            p = self.anchor_product_id
            if not p.sale_ok or not p.active:
                add('R4', _("Anchor product must be active and saleable."))
            if p.type == 'combo':
                add('R12', _("Anchor product must not be a combo product."))
            tracking = p.service_tracking if 'service_tracking' in p._fields else 'no'
            if self.anchor_owner_mode == 'component_bridge_owner' and tracking not in ('no', 'project_only'):
                add('R4', _("COMPONENT_BRIDGE_OWNER anchors must not create tasks natively (service_tracking=%s).", tracking))
            resolved = self._resolve_owner_mode_hook()
            if resolved and resolved != self.anchor_owner_mode:
                add('R4', _("Owner registry resolves %(r)s but the version declares %(d)s.", r=resolved, d=self.anchor_owner_mode))
        # R5 applicability
        if bool(self.all_systems) == bool(self.system_ids):
            add('R5', _("Applicability must be explicit: ALL systems XOR a non-empty system list."))
        # R6 recipe integrity
        if not lines:
            add('R6', _("Recipe is empty."))
        keys = lines.mapped('occurrence_key')
        if len(keys) != len(set(keys)):
            add('R6', _("Duplicate occurrence keys."))
        for l in lines:
            if l.base_line_ids - lines:
                add('R6', _("Line %s references a base outside this version.", l.display_name))
        # R7 percent validity
        edges = {l.id: set(l.base_line_ids.ids) for l in lines}
        if find_cycle(edges):
            add('R7', _("Percent bases form a cycle."))
        for l in lines.filtered(lambda l: l.basis in PERCENT_BASES):
            if not l.base_line_ids:
                add('R7', _("Percent line %s has no base lines.", l.display_name))
            if l in l.base_line_ids:
                add('R7', _("Percent line %s references itself.", l.display_name))
            if any(b.basis in PERCENT_BASES for b in l.base_line_ids):
                add('R7', _("Percent-on-percent is forbidden (%s).", l.display_name))
            if l.basis == 'percent_of_quantity' and len(set(l.base_line_ids.mapped('dimension_family'))) > 1:
                add('R7', _("PERCENT_OF_QUANTITY bases must share a dimension family (%s).", l.display_name))
            if l.basis == 'percent_of_cost' and any(b.cost_policy == 'derived' for b in l.base_line_ids):
                add('R7', _("PERCENT_OF_COST bases must be direct-cost lines (%s).", l.display_name))
        # R8 executable known lines
        for l in lines.filtered(lambda l: l.kind == 'product' and l.execution_mode != 'no_action'):
            if not l.activity_id:
                add('R8', _("Line %s needs an Activity.", l.display_name))
            if not l.execution_mode:
                add('R8', _("Line %s needs an execution mode.", l.display_name))
        # R9 estimate-only
        for l in lines.filtered(lambda l: l.kind == 'estimate_only'):
            if not (l.resolution_owner_id and l.internal_description and l.uom_id):
                add('R9', _("ESTIMATE_ONLY line %s needs owner, description and unit.", l.display_name))
            else:
                add('R9', _("ESTIMATE_ONLY line %s requires quote-time resolution.", l.display_name), 'warn')
        # R10 internal-only label
        for l in lines.filtered(lambda l: l.disclosure == 'internal_only' and l.customer_eligible):
            add('R10', _("INTERNAL_ONLY line %s must not be customer-eligible.", l.display_name))
        # R11 rounding
        for l in lines.filtered(lambda l: l.basis != 'percent_of_cost' and l.rounding_mode != 'none' and l.rounding_increment <= 0):
            add('R11', _("Line %s: rounding increment must be > 0 when a rounding mode is set.", l.display_name))
        return issues

    def _resolve_owner_mode_hook(self):
        """Overridden by sipanel_scope_execution (owner registry). None = no registry."""
        return None
