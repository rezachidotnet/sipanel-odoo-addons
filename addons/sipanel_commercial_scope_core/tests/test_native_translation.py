# -*- coding: utf-8 -*-
"""STEP 2A: native translatable master text, released immutability, migration.

These tests drive the ORM the way an operator, an import, an RPC client and the
translation dialog do. They never assert on template or view source.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..models.legacy_translation_backfill import backfill, plan_record
from ..models.sipanel_tools import (has_translation, resolve_customer_text,
                                    stored_translations, translation_map)
from .common import SipanelCoreCase, set_translation


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_translation')
class TestNativeMasterTranslation(SipanelCoreCase):
    """(1)(2)(3) storage and retrieval through the native mechanism."""

    def _draft_version(self):
        scope = self.env['sipanel.scope'].create({
            'code': f'SIPANEL-PT-XLATE-{self.env.cr.dbname[:4]}-{id(self) % 100000}',
            'name': 'SIPANEL-PT translation scope', 'owner_user_id': self.steward.id})
        return self.env['sipanel.scope.version'].create({
            'scope_id': scope.id, 'customer_label': 'Gutter accessories',
            'base_uom_id': self.uom_m.id, 'dimension_family': 'length',
            'anchor_product_id': self.p_anchor.id, 'all_systems': True})

    def test_persian_master_text_round_trips_through_fa_IR(self):
        version = self._draft_version()
        set_translation(version, 'customer_label', en='Gutter accessories', fa='متعلقات آبرو')
        self.assertEqual(version.with_context(lang='fa_IR').customer_label, 'متعلقات آبرو')
        self.assertTrue(has_translation(version, 'customer_label', 'fa_IR'))

    def test_english_master_text_round_trips_through_en_US(self):
        version = self._draft_version()
        set_translation(version, 'customer_label', en='Gutter accessories', fa='متعلقات آبرو')
        self.assertEqual(version.with_context(lang='en_US').customer_label, 'Gutter accessories')
        self.assertTrue(has_translation(version, 'customer_label', 'en_US'))

    def test_one_field_holds_every_language_and_the_dialog_sees_them(self):
        """(3) The operator maintains languages through the standard control,
        which reads and writes through get/update_field_translations."""
        version = self._draft_version()
        set_translation(version, 'customer_label', en='Gutter accessories', fa='متعلقات آبرو')
        translations, context = version.get_field_translations('customer_label')
        by_lang = {t['lang']: t['value'] for t in translations}
        self.assertEqual(by_lang['en_US'], 'Gutter accessories')
        self.assertEqual(by_lang['fa_IR'], 'متعلقات آبرو')
        self.assertEqual(context['translation_type'], 'char')
        # a third language can be added without a new field
        version.update_field_translations('customer_label', {'ru_RU': 'Водосток'})
        self.assertEqual(version.with_context(lang='ru_RU').customer_label, 'Водосток')
        self.assertEqual(sorted(stored_translations(version, 'customer_label')),
                         ['en_US', 'fa_IR', 'ru_RU'])

    def test_missing_translation_is_distinguished_from_a_fallback(self):
        """The whole language-readiness rule depends on this distinction."""
        version = self._draft_version()
        set_translation(version, 'customer_label', en='Gutter accessories')
        # reading fa_IR yields the English source ...
        self.assertEqual(version.with_context(lang='fa_IR').customer_label, 'Gutter accessories')
        # ... but nothing is stored for fa_IR, and we can tell
        self.assertFalse(has_translation(version, 'customer_label', 'fa_IR'))
        value, used, is_fallback = resolve_customer_text(version, 'customer_label', 'fa_IR')
        self.assertTrue(is_fallback)
        self.assertEqual(used, 'en_US')
        self.assertEqual(value, 'Gutter accessories')

    def test_persian_only_master_does_not_leak_into_the_english_source(self):
        version = self._draft_version()
        version.update_field_translations('customer_label', {'en_US': '', 'fa_IR': 'فقط فارسی'})
        self.assertEqual(version.with_context(lang='fa_IR').customer_label, 'فقط فارسی')
        self.assertFalse(version.with_context(lang='en_US').customer_label)
        self.assertFalse(has_translation(version, 'customer_label', 'en_US'))


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_translation')
class TestReleasedTranslationImmutability(SipanelCoreCase):
    """(11)(12) a released version is immutable in EVERY language and by every route."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope, cls.v1 = cls._make_master()

    def test_released_translation_cannot_be_edited_by_a_normal_write(self):
        with self.assertRaises(UserError):
            self.v1.write({'customer_label': 'renamed'})

    def test_released_translation_cannot_be_edited_through_a_language_context(self):
        with self.assertRaises(UserError):
            self.v1.with_context(lang='fa_IR').write({'customer_label': 'برچسب جدید'})

    def test_released_translation_cannot_be_edited_through_sudo(self):
        with self.assertRaises(UserError):
            self.v1.sudo().with_context(lang='fa_IR').write({'customer_label': 'برچسب جدید'})

    def test_released_translation_cannot_be_edited_through_the_translation_dialog(self):
        """update_field_translations bypasses write - the route the web
        translation dialog and an RPC client both take."""
        with self.assertRaises(UserError):
            self.v1.update_field_translations('customer_label', {'fa_IR': 'برچسب جدید'})
        with self.assertRaises(UserError):
            self.v1.sudo().update_field_translations('customer_label', {'fa_IR': 'برچسب جدید'})

    def test_released_recipe_line_translation_is_immutable_too(self):
        line = self.v1.recipe_line_ids[0]
        with self.assertRaises(UserError):
            line.update_field_translations('customer_label', {'fa_IR': 'دیگر'})
        with self.assertRaises(UserError):
            line.sudo().write({'customer_label': 'other'})

    def test_translation_stays_unchanged_after_a_rejected_edit(self):
        before = stored_translations(self.v1, 'customer_label')
        for attempt in (
            lambda: self.v1.update_field_translations('customer_label', {'fa_IR': 'x'}),
            lambda: self.v1.with_context(lang='fa_IR').write({'customer_label': 'y'}),
        ):
            with self.assertRaises(UserError):
                attempt()
        self.assertEqual(stored_translations(self.v1, 'customer_label'), before)


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_translation')
class TestReleaseChecksumCoversTranslations(SipanelCoreCase):
    """A translation edit must not be able to slip past the release checksum."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope, cls.v1 = cls._make_master()

    def _new_draft_from(self, version):
        """action_new_version returns a window action; follow it to the record."""
        action = version.action_new_version()
        return self.env['sipanel.scope.version'].browse(action['res_id'])

    def test_checksum_payload_contains_the_full_translation_map(self):
        payload = self.v1._content_checksum_payload()
        self.assertEqual(payload['customer_label'],
                         translation_map(self.v1, 'customer_label'))
        self.assertIn('fa_IR', payload['customer_label'])
        self.assertIn('en_US', payload['customer_label'])
        # deterministic language order
        self.assertEqual(list(payload['customer_label']),
                         sorted(payload['customer_label']))

    def test_adding_a_translation_changes_the_checksum(self):
        before = self.v1._compute_content_checksum()
        new = self._new_draft_from(self.v1)
        new.update_field_translations('customer_label', {'ru_RU': 'Водосток'})
        self.assertNotEqual(new._compute_content_checksum(), before,
                            "a new language term must change the content checksum")

    def test_changing_one_language_changes_the_checksum(self):
        new = self._new_draft_from(self.v1)
        before = new._compute_content_checksum()
        new.update_field_translations('customer_label', {'fa_IR': 'برچسب متفاوت'})
        self.assertNotEqual(new._compute_content_checksum(), before)

    def test_recipe_line_translation_participates_in_the_checksum(self):
        new = self._new_draft_from(self.v1)
        before = new._compute_content_checksum()
        new.recipe_line_ids[0].update_field_translations('customer_label', {'fa_IR': 'ناودان جدید'})
        new.invalidate_recordset()
        self.assertNotEqual(new._compute_content_checksum(), before)

    def test_existing_release_keeps_its_recorded_checksum_verifiable(self):
        """v1 releases predate translations; recomputing them with v2 would be a
        false mismatch, so the algorithm is recorded per release."""
        self.assertIn(self.v1.checksum_algo, ('v1', 'v2'))
        self.assertTrue(self.v1.verify_release_checksum(),
                        "a released version must verify under its own algorithm")


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_translation')
class TestLegacyTranslationMigration(SipanelCoreCase):
    """(4) migration of existing FA/EN values, including the awkward shapes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope, cls.v1 = cls._make_master()

    def test_plan_maps_fa_to_fa_IR_and_en_to_en_US(self):
        terms, klass = plan_record('متعلقات آبرو', 'Gutter accessories', {})
        self.assertEqual(terms, {'en_US': 'Gutter accessories', 'fa_IR': 'متعلقات آبرو'})
        self.assertEqual(klass, 'distinct_per_language')

    def test_plan_keeps_conflicting_values_as_separate_languages(self):
        terms, _klass = plan_record('فارسی', 'English', {})
        self.assertEqual(terms['fa_IR'], 'فارسی')
        self.assertEqual(terms['en_US'], 'English')

    def test_plan_never_overwrites_a_native_translation_with_a_blank_legacy_value(self):
        terms, klass = plan_record('', '', {'fa_IR': 'موجود'})
        self.assertEqual(terms, {})
        self.assertEqual(klass, 'blank_both')
        terms, _klass = plan_record('', 'English', {'fa_IR': 'موجود'})
        self.assertNotIn('fa_IR', terms, "a blank legacy FA must not clear a stored fa_IR term")

    def test_plan_always_writes_en_US_explicitly(self):
        """Odoo copies a lone non-English term into the English source, which
        would send Persian to an English customer."""
        terms, klass = plan_record('فقط فارسی', '', {})
        self.assertEqual(klass, 'fa_only')
        self.assertIn('en_US', terms)
        self.assertEqual(terms['en_US'], '')

    def test_plan_ignores_whitespace_only_legacy_values(self):
        terms, klass = plan_record('   ', '\t\n', {})
        self.assertEqual(terms, {})
        self.assertEqual(klass, 'blank_both')

    def test_backfill_dry_run_writes_nothing(self):
        before = stored_translations(self.v1, 'customer_label')
        report = backfill(self.env, dry_run=True)
        self.assertTrue(report['dry_run'])
        self.assertEqual(stored_translations(self.v1, 'customer_label'), before)

    def test_backfill_is_idempotent(self):
        """Re-running must not duplicate or disturb anything already migrated."""
        first = backfill(self.env, dry_run=False)
        snapshot = stored_translations(self.v1, 'customer_label')
        second = backfill(self.env, dry_run=False)
        self.assertEqual(stored_translations(self.v1, 'customer_label'), snapshot)
        self.assertLessEqual(second['totals']['terms_written'],
                             first['totals']['terms_written'])
