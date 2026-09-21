# -*- coding: utf-8 -*-
"""STEP 2A: quotation snapshots resolve the master translations once and freeze them.

The snapshot boundary is the point of these tests: a quotation must carry the
text it was created with, in the customer's language, and must not move when the
master or its translations later change.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import (
    guard_ctx, stored_translations)
from odoo.addons.sipanel_commercial_scope_core.tests.common import set_translation

from .common import SipanelSaleCase


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_translation')
class TestTranslationSnapshot(SipanelSaleCase):

    def _order(self, lang='en_US'):
        self.env['res.lang'].sudo()._activate_lang('fa_IR')
        partner = self.env['res.partner'].create({
            'name': f'SIPANEL-PT-XLATE customer {lang}', 'lang': lang, 'email': False})
        return self.env['sale.order'].with_user(self.estimator).create({
            'partner_id': partner.id, 'origin': 'SIPANEL-PT-XLATE'})

    def _scope(self, lang='en_US', version=None, qty=12.0):
        order = self._order(lang)
        return self.env['sipanel.quote.scope'].with_user(self.estimator)._create_from_version(
            order, version or self.v1, qty, self.uom_m)

    def _draft_master(self):
        """A fresh DRAFT version whose translations we are free to edit."""
        action = self.v1.action_new_version()
        return self.env['sipanel.scope.version'].browse(action['res_id'])

    # ------------------------------------------------------------ (8)(9) resolution
    def test_persian_quotation_snapshots_the_persian_master_text(self):
        scope = self._scope('fa_IR')
        rev = scope.current_revision_id
        self.assertEqual(rev.resolved_language, 'fa_IR')
        self.assertEqual(rev.label_resolved, 'متعلقات آبرو')
        self.assertEqual(rev.label_fa, 'متعلقات آبرو')
        self.assertEqual(rev.label_en, 'Gutter accessories')
        self.assertFalse(rev.translation_provenance['version']['customer_label']['fallback'])

    def test_english_quotation_snapshots_the_english_master_text(self):
        scope = self._scope('en_US')
        rev = scope.current_revision_id
        self.assertEqual(rev.resolved_language, 'en_US')
        self.assertEqual(rev.label_resolved, 'Gutter accessories')
        self.assertFalse(rev.translation_provenance['version']['customer_label']['fallback'])

    def test_snapshot_records_the_source_version_provenance(self):
        scope = self._scope('fa_IR')
        rev = scope.current_revision_id
        self.assertEqual(scope.source_version_id, self.v1)
        self.assertEqual(rev.source_version_checksum, self.v1.release_checksum)
        self.assertEqual(rev.translation_provenance['language'], 'fa_IR')

    def test_component_labels_are_resolved_in_the_quotation_language(self):
        scope = self._scope('fa_IR')
        labels = scope.current_revision_id.component_ids.mapped('customer_label_resolved')
        self.assertIn('ناودان', labels)
        self.assertNotIn('Gutter', labels)

    # ------------------------------------------------------------ (10) immutability
    def test_master_translation_change_does_not_alter_an_existing_snapshot(self):
        scope = self._scope('fa_IR')
        rev = scope.current_revision_id
        before = (rev.label_resolved, rev.label_fa, rev.label_en,
                  rev.component_ids.mapped('customer_label_resolved'))
        # a NEW master version with different Persian text
        draft = self._draft_master()
        draft.update_field_translations('customer_label', {'fa_IR': 'برچسب تازه'})
        draft.recipe_line_ids[0].update_field_translations('customer_label', {'fa_IR': 'ناودان تازه'})
        rev.invalidate_recordset()
        self.assertEqual(
            (rev.label_resolved, rev.label_fa, rev.label_en,
             rev.component_ids.mapped('customer_label_resolved')), before,
            "an existing quotation snapshot must not follow later master translations")

    def test_sealed_snapshot_and_artifact_survive_a_master_translation_change(self):
        scope = self._scope('fa_IR')
        rev = scope.current_revision_id
        rev.action_seal()
        sealed_hash = rev.sealed_hash
        artifact_hashes = sorted(rev.artifact_ids.mapped('content_hash'))
        draft = self._draft_master()
        draft.update_field_translations('customer_label', {'fa_IR': 'برچسب تازه'})
        rev.invalidate_recordset()
        self.assertEqual(rev.sealed_hash, sealed_hash)
        self.assertEqual(sorted(rev.artifact_ids.mapped('content_hash')), artifact_hashes)
        self.assertEqual(rev._current_seal_hash(), sealed_hash,
                         "recomputing the seal payload must still match")

    def test_snapshot_is_not_a_live_read_of_the_master(self):
        """The snapshot columns are plain columns, never translatable fields."""
        rev = self._scope('fa_IR').current_revision_id
        for fname in ('label_fa', 'label_en', 'label_resolved',
                      'customer_description_resolved'):
            self.assertFalse(rev._fields[fname].translate,
                             f'{fname} must not be a translatable field')

    # ------------------------------------------------- (5)(6)(7) language readiness
    def _master_without_persian(self):
        scope = self.env['sipanel.scope'].create({
            'code': f'SIPANEL-PT-NOFA-{id(self) % 100000}', 'name': 'SIPANEL-PT no-Persian',
            'owner_user_id': self.steward.id})
        version = self.env['sipanel.scope.version'].create({
            'scope_id': scope.id, 'customer_label': 'English only scope',
            'base_uom_id': self.uom_m.id, 'dimension_family': 'length',
            'anchor_product_id': self.p_anchor.id, 'all_systems': True})
        self.env['sipanel.scope.recipe.line'].create({
            'version_id': version.id, 'sequence': 10, 'product_id': self.p_gutter.id,
            'uom_id': self.uom_m.id, 'dimension_family': 'length', 'basis': 'per_scope_qty',
            'rate': 1.0, 'activity_id': self.act_ins.id, 'execution_mode': 'stock_issue',
            'customer_eligible': True, 'customer_label': 'Gutter'})
        version.with_context(**guard_ctx('sipanel_release_transaction')).write({
            'state': 'released', 'release_checksum': 'test'})
        return version

    def test_draft_warns_when_the_requested_translation_is_missing(self):
        """(5) the draft may fall back, but the gap must be visible."""
        version = self._master_without_persian()
        scope = self._scope('fa_IR', version=version)
        rev = scope.current_revision_id
        self.assertIn('customer_label', rev._missing_translation_keys())
        self.assertTrue(rev.translation_provenance['version']['customer_label']['fallback'])
        body = ' '.join(scope.message_ids.mapped('body'))
        self.assertIn('customer_label', body,
                      "the missing translation must be posted on the scope")
        # the draft still has a usable anchor line
        self.assertTrue(scope.anchor_line_id.name)

    def test_seal_fails_closed_when_the_requested_translation_is_missing(self):
        """(6) never send English fallback to a Persian customer."""
        version = self._master_without_persian()
        rev = self._scope('fa_IR', version=version).current_revision_id
        with self.assertRaises(UserError):
            rev.action_seal()
        self.assertEqual(rev.state, 'working')
        self.assertFalse(rev.artifact_ids)

    def test_seal_succeeds_once_the_translation_exists(self):
        rev = self._scope('fa_IR').current_revision_id
        self.assertEqual(rev._missing_translation_keys(), [])
        rev.action_seal()
        self.assertEqual(rev.state, 'sent_sealed')

    def test_readiness_blocks_on_a_missing_translation(self):
        version = self._master_without_persian()
        scope = self._scope('fa_IR', version=version)
        codes = [i['code'] for i in scope._readiness_issues() if i['level'] == 'block']
        self.assertIn('LABEL_LANG', codes)

    def test_internal_only_component_needs_no_customer_translation(self):
        """(7) exemption: an internal-only line never reaches the customer."""
        scope = self._scope('fa_IR')
        rev = scope.current_revision_id
        internal = rev.component_ids.filtered(lambda c: c.disclosure == 'internal_only')
        self.assertTrue(internal, 'fixture must contain an internal-only component')
        for comp in internal:
            self.assertTrue(comp.label_provenance.get('exempt'))
        for key in rev._missing_translation_keys():
            self.assertNotIn(key.removeprefix('component:'),
                             internal.mapped('source_occurrence_key'))
        # and it does not block the seal
        rev.action_seal()
        self.assertEqual(rev.state, 'sent_sealed')

    # ------------------------------------------------------------ (13) duplication
    def test_duplicate_quotation_keeps_the_original_snapshot_and_provenance(self):
        scope = self._scope('fa_IR')
        rev = scope.current_revision_id
        order = scope.order_id
        draft = self._draft_master()
        draft.update_field_translations('customer_label', {'fa_IR': 'برچسب تازه'})
        copy_order = order.copy()
        new_scope = copy_order.sipanel_quote_scope_ids
        self.assertEqual(len(new_scope), 1)
        new_rev = new_scope.current_revision_id
        self.assertEqual(new_rev.label_resolved, rev.label_resolved,
                         "a duplicate copies the quotation, it does not re-resolve the master")
        self.assertEqual(new_rev.resolved_language, rev.resolved_language)
        self.assertEqual(new_rev.source_version_checksum, rev.source_version_checksum)
        self.assertEqual(new_rev.translation_provenance, rev.translation_provenance)

    # ------------------------------------------------------- (14) PDF / portal text
    def test_customer_note_uses_the_resolved_snapshot_language(self):
        rev = self._scope('fa_IR').current_revision_id
        self.assertIn('متعلقات آبرو', rev.final_note)
        self.assertNotIn('Gutter accessories', rev.final_note)
        # the anchor line, which is what the PDF and the portal render
        self.assertEqual(rev.quote_scope_id.anchor_line_id.name, rev.final_note)

    def test_english_quotation_note_is_english(self):
        rev = self._scope('en_US').current_revision_id
        self.assertIn('Gutter accessories', rev.final_note)
        self.assertNotIn('متعلقات آبرو', rev.final_note)

    def test_sealed_text_artifact_carries_the_resolved_language(self):
        rev = self._scope('fa_IR').current_revision_id
        rev.action_seal()
        artifact = rev.artifact_ids.filtered(lambda a: a.kind == 'text')
        self.assertTrue(artifact)
        self.assertEqual(artifact[0].language, 'fa_IR')
        self.assertIn('ناودان', artifact[0].content_text)

    # --------------------------------------------------------------- (15) leakage
    def test_no_cost_margin_or_internal_text_reaches_the_customer_payload(self):
        rev = self._scope('fa_IR').current_revision_id
        blob = (rev.final_note or '') + ' '.join(
            str(c._customer_payload(rev.language)) for c in rev.component_ids)
        for forbidden in ('unit_cost', 'cost_amount', 'margin', 'standard_price',
                          'internal_description', 'eligible_cost'):
            self.assertNotIn(forbidden, blob)
        internal = rev.component_ids.filtered(lambda c: c.disclosure == 'internal_only')
        for comp in internal:
            self.assertIsNone(comp._customer_payload(rev.language),
                              'an internal-only component must never build a customer payload')

    def test_master_internal_description_is_not_translatable_and_stays_internal(self):
        self.assertFalse(self.v1._fields['internal_description'].translate)
        rev = self._scope('fa_IR').current_revision_id
        self.assertNotIn(self.v1.internal_description or '#none#', rev.final_note or '')

    # --------------------------------------------------------- snapshot integrity
    def test_snapshot_columns_hold_only_really_stored_terms(self):
        """An English term must never be written into the Persian column."""
        version = self._master_without_persian()
        rev = self._scope('fa_IR', version=version).current_revision_id
        self.assertFalse(rev.label_fa, 'no Persian term exists, so the column stays empty')
        self.assertEqual(rev.label_en, 'English only scope')
        self.assertFalse(stored_translations(version, 'customer_label').get('fa_IR'))
