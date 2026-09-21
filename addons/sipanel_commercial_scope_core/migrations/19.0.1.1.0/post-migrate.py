# -*- coding: utf-8 -*-
"""STEP 2A: backfill native translations from the dormant *_fa / *_en columns.

post- rather than pre-migrate: the new translatable columns must exist before
anything can be written into them. The legacy columns are still present at this
point (Odoo does not drop columns of removed fields), which is what makes the
migration possible and why they are documented as dormant rather than deleted.
"""
import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.sipanel_commercial_scope_core.models.legacy_translation_backfill import backfill

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    preview = backfill(env, dry_run=True)
    _logger.info("SIPANEL STEP 2A translation backfill preview: %s", preview['totals'])
    result = backfill(env, dry_run=False)
    _logger.info("SIPANEL STEP 2A translation backfill applied: %s", result['totals'])
    _logger.info("SIPANEL STEP 2A checksum_algo v1 marked on %s released version(s)",
                 result['checksum_algo_v1']['count'])
