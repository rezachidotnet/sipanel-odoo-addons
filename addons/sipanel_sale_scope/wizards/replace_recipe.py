# -*- coding: utf-8 -*-
"""Replace the master part of a WORKING revision with another released version; explicit diff, never silent (GAP-B15)."""
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx


class SipanelWizardReplaceRecipe(models.TransientModel):
    _name = 'sipanel.wizard.replace.recipe'
    _description = 'Replace recipe from a released version'

    quote_scope_id = fields.Many2one('sipanel.quote.scope', required=True)
    version_id = fields.Many2one('sipanel.scope.version', required=True, domain="[('state', '=', 'released')]")
    keep_overrides = fields.Boolean(default=False, help="Retain manual quantity overrides on occurrences that still exist (matched by occurrence key).")
    diff_text = fields.Text(compute='_compute_diff')

    @api.depends('quote_scope_id', 'version_id')
    def _compute_diff(self):
        for w in self:
            rev = w.quote_scope_id.current_revision_id
            old = {c.source_occurrence_key: c for c in rev.component_ids.filtered(lambda c: c.active_state == 'active' and c.origin == 'master')}
            new = {l.occurrence_key: l for l in w.version_id.recipe_line_ids}
            added = [new[k].display_name for k in new if k not in old]
            removed = [old[k].display_name for k in old if k not in new]
            w.diff_text = self.env._("Added: %(a)s\nRemoved: %(r)s\nRetained (re-snapshotted): %(k)s",
                                     a=', '.join(added) or '-', r=', '.join(removed) or '-',
                                     k=', '.join(old[k].display_name for k in old if k in new) or '-')

    def action_apply(self):
        self.ensure_one()
        scope = self.quote_scope_id
        rev = scope.current_revision_id
        rev._check_working('replace the recipe of')
        if self.version_id.scope_id != scope.source_scope_id:
            raise UserError(self.env._("The replacement version must belong to the same Scope identity."))
        old_master = rev.component_ids.filtered(lambda c: c.origin == 'master' and c.active_state == 'active')
        overrides = {c.source_occurrence_key: (c.override_qty, c.sudo().override_reason) for c in old_master if c.qty_override}
        for c in old_master:
            dependents = rev.component_ids.filtered(lambda x: c in x.base_component_ids and x.origin != 'master')
            if dependents:
                raise UserError(self.env._("Added line %s depends on a master line; relocate it first.", dependents[0].display_name))
        old_master.write({'active_state': 'tombstone', 'origin': 'removed'})
        # re-snapshot using the standard path on a temp scope is heavy; snapshot directly
        tmp = self.env['sipanel.quote.scope']
        Comp = self.env['sipanel.quote.scope.component'].sudo()
        id_map = {}
        for l in self.version_id.recipe_line_ids.sorted(lambda l: (l.sequence, l.id)):
            c_terms, c_resolved, c_prov = snapshot_customer_text(l, 'customer_label', rev.language or 'en_US')
            c_prov['exempt'] = (l.disclosure == 'internal_only') or not l.customer_eligible
            cvals = {
                'revision_id': rev.id, 'source_occurrence_key': l.occurrence_key, 'source_line_id': l.id, 'origin': 'master',
                'sequence': l.sequence, 'kind': l.kind, 'product_id': l.product_id.id, 'description': l.internal_description,
                'customer_label_fa': c_terms.get('fa_IR', False), 'customer_label_en': c_terms.get('en_US', False),
                'customer_label_resolved': c_resolved, 'label_provenance': c_prov, 'spec_json': l.spec_json,
                'uom_id': l.uom_id.id, 'uom_name_snapshot': l.uom_id.with_context(lang=rev.language or 'en_US').name, 'dimension_family': l.dimension_family,
                'basis': l.basis, 'rate': l.rate, 'fixed_qty': l.fixed_qty, 'percent': l.percent,
                'manual_qty': l.manual_qty_default, 'manual_qty_set': bool(l.basis == 'manual' and l.manual_qty_default),
                'rounding_increment': l.rounding_increment, 'rounding_mode': l.rounding_mode,
                'activity_id': l.activity_id.id, 'system_id': scope.system_id.id, 'execution_mode': l.execution_mode,
                'no_action_reason': l.no_action_reason, 'responsibility': l.responsibility, 'placement': l.placement,
                'certainty': l.certainty, 'disclosure': l.disclosure, 'resolution_owner_id': l.resolution_owner_id.id,
                'resolution_note': l.resolution_note, 'resolution_state': 'open' if l.kind == 'estimate_only' else 'not_required',
            }
            if l.responsibility == 'customer':
                cvals['cost_source'] = 'not_applicable'
            elif l.cost_policy == 'derived':
                cvals['cost_source'] = 'derived'
            elif l.cost_policy == 'manual_estimate':
                cvals.update({'cost_source': 'manual_estimate', 'unit_cost': l.manual_cost_default, 'cost_uom_id': l.uom_id.id, 'cost_uom_factor': 1.0,
                              'manual_cost_user_id': self.env.uid, 'manual_cost_date': fields.Datetime.now(), 'manual_cost_reason': 'Master default'})
            elif l.product_id:
                cvals.update(Comp._product_cost_snapshot_vals(l.product_id, scope.company_id, l.uom_id))
            if self.keep_overrides and l.occurrence_key in overrides:
                cvals.update({'qty_override': True, 'override_qty': overrides[l.occurrence_key][0], 'override_reason': overrides[l.occurrence_key][1]})
            id_map[l.id] = Comp.create(cvals).id
        for l in self.version_id.recipe_line_ids:
            if l.base_line_ids:
                Comp.browse(id_map[l.id]).write({'base_component_ids': [(6, 0, [id_map[b.id] for b in l.base_line_ids if b.id in id_map])]})
        scope.write({'source_version_id': self.version_id.id})
        rev.with_context(**guard_ctx('sipanel_note_sync')).write({'note_reviewed': False})
        self.env['sipanel.scope.audit.event'].log(scope, 'replace_recipe', after={'version_id': self.version_id.id, 'diff': self.diff_text},
                                                  revision_ref=rev.display_name)
        return {'type': 'ir.actions.act_window_close'}
