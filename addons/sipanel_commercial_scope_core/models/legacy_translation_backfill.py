# -*- coding: utf-8 -*-
"""STEP 2A: move the legacy *_fa / *_en customer text into native translations.

The legacy columns are no longer ORM fields, so they are read with a plain
SELECT. That is a read of dormant business data, not hand-written translation
SQL: every write goes through `Model.update_field_translations`.

Two behaviours of the installed Odoo 19 were measured before this was written
(both on a NULL jsonb column, which is the state of every new field here):

  * `update_field_translations` works directly on a NULL column, so no priming
    write is needed;
  * passing only a non-English language COPIES that term into the `en_US`
    source. Persian would silently become the English term - exactly what a
    customer must never receive - so an explicit `en_US` key is always sent,
    blank when the record has no English text.
"""
from .sipanel_tools import guard_ctx, stored_translations

# (model, table, [(legacy_fa_column, legacy_en_column, native_field)])
LEGACY_MAP = [
    ('sipanel.scope.version', 'sipanel_scope_version', [
        ('label_fa', 'label_en', 'customer_label'),
        ('customer_description_fa', 'customer_description_en', 'customer_description'),
    ]),
    ('sipanel.scope.recipe.line', 'sipanel_scope_recipe_line', [
        ('customer_label_fa', 'customer_label_en', 'customer_label'),
    ]),
]


def _clean(value):
    return value.strip() if isinstance(value, str) else ''


def _column_exists(env, table, column):
    env.cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column))
    return bool(env.cr.fetchone())


def plan_record(fa, en, existing):
    """Decide what to store for one record/field.

    Returns (terms_to_write, classification). `terms_to_write` is empty when
    there is nothing to do. Rules:
      * a blank legacy value never overwrites a non-empty native translation;
      * FA and EN are kept as separate language terms, never merged;
      * `en_US` is always written explicitly so Persian cannot leak into it.
    """
    fa, en = _clean(fa), _clean(en)
    if not fa and not en:
        return {}, 'blank_both'
    terms = {'en_US': en, 'fa_IR': fa} if fa else {'en_US': en}
    # never clobber an existing native term with an empty legacy value
    terms = {lang: val for lang, val in terms.items()
             if val or not existing.get(lang)}
    conflicting = {lang: val for lang, val in terms.items()
                   if existing.get(lang) and existing[lang] != val}
    if not terms:
        return {}, 'nothing_to_write'
    if conflicting:
        return terms, 'would_overwrite_existing'
    if fa and en:
        klass = 'identical_both' if fa == en else 'distinct_per_language'
    else:
        klass = 'fa_only' if fa else 'en_only'
    return terms, klass


def backfill(env, dry_run=True):
    """Migrate every legacy value into native translations.

    Runs under the release guard: the masters in this database are RELEASED and
    their content - translations included - is otherwise immutable. This is the
    one-time, audited system path.
    """
    report = {'dry_run': dry_run, 'models': {}, 'totals': {}}
    totals = {'records_scanned': 0, 'records_written': 0, 'terms_written': 0,
              'terms_by_lang': {}, 'skipped': 0}

    for model, table, pairs in LEGACY_MAP:
        if model not in env:
            continue
        entry = {'table': table, 'fields': {}, 'missing_legacy_columns': []}
        records = env[model].sudo().with_context(active_test=False).search([])
        for fa_col, en_col, native in pairs:
            if not (_column_exists(env, table, fa_col) and _column_exists(env, table, en_col)):
                entry['missing_legacy_columns'].append(f'{fa_col}/{en_col}')
                continue
            env.cr.execute(
                f'SELECT id, "{fa_col}", "{en_col}" FROM "{table}" WHERE id IN %s',
                (tuple(records.ids) or (0,),))
            legacy = {row[0]: (row[1], row[2]) for row in env.cr.fetchall()}
            stats = {'native_field': native, 'scanned': 0, 'written': 0,
                     'terms_by_lang': {}, 'classification': {}, 'details': []}
            for record in records:
                fa, en = legacy.get(record.id, (None, None))
                existing = stored_translations(record, native)
                terms, klass = plan_record(fa, en, existing)
                stats['scanned'] += 1
                stats['classification'][klass] = stats['classification'].get(klass, 0) + 1
                totals['records_scanned'] += 1
                if not terms:
                    totals['skipped'] += 1
                    continue
                stats['details'].append({
                    'id': record.id, 'ref': record.display_name, 'class': klass,
                    'langs': sorted(terms), 'existing_langs': sorted(existing),
                })
                if not dry_run:
                    record.with_context(**guard_ctx('sipanel_release_transaction')) \
                          .update_field_translations(native, terms)
                stats['written'] += 1
                totals['records_written'] += 1
                for lang, value in terms.items():
                    if value:
                        stats['terms_by_lang'][lang] = stats['terms_by_lang'].get(lang, 0) + 1
                        totals['terms_by_lang'][lang] = totals['terms_by_lang'].get(lang, 0) + 1
                        totals['terms_written'] += 1
            entry['fields'][f'{fa_col}|{en_col}'] = stats
        report['models'][model] = entry

    # Releases made before STEP 2A were checksummed without the translation map.
    # Mark them v1 so their recorded checksum stays verifiable; anything released
    # from now on uses v2, which hashes the complete translation map.
    Version = env['sipanel.scope.version'].sudo().with_context(active_test=False)
    stale = Version.search([('release_checksum', '!=', False), ('checksum_algo', '!=', 'v1')])
    report['checksum_algo_v1'] = {'count': len(stale), 'ids': stale.ids}
    if not dry_run and stale:
        stale.with_context(**guard_ctx('sipanel_release_transaction')).write({'checksum_algo': 'v1'})

    report['totals'] = totals
    return report
