# -*- coding: utf-8 -*-
"""Standing Seam commercial model correction (work order 2026-10-05, B "Commercial model" / B3).

Installation / Execution is no longer included in the Standing Seam supply prices: it is quoted as a separate
percentage line (sipanel_installation_pct). The released Standing Seam Scope versions still say otherwise:

- CS-STANDING-SEAM lists SIP-000075 "Standing Seam Installation Service" as an INCLUDED_PARENT,
  customer-eligible recipe line (installation priced inside the Roof anchor), and its customer description
  says "supplied and installed ... Installation is included in this price";
- CS-STANDING-SEAM-FLASHING and CS-STANDING-SEAM-GUTTER describe themselves as "supplied and installed".

A released version is immutable, so each scope gets its NEXT version through the native path:

    current released version --action_new_version--> DRAFT copy (same content, translations, keys renewed)
    DRAFT: Roof only - remove the recipe line(s) of the installation product (no other recipe change)
    DRAFT: customer description replaced by the owner-approved wording (en_US + fa_IR)
    DRAFT --action_release--> RELEASED; the previous version becomes SUPERSEDED (state only, content and
    release checksum untouched - verified before and after)

Customer text gate: customer wording is the owner's decision. create_standing_seam_v3(env, wording) releases
nothing unless wording (en_US AND fa_IR, free of installation keywords - release rule QL2) is supplied for EVERY
scope that needs a new version; the gate is evaluated for all three scopes before anything is created, so a
refusal never leaves a partial set. APPROVED_WORDING is the supply-only text of 2026-10-06 (clone); the owner
approves the final Production text. Offending recipe lines follow release rule QL1 (installation work, any
placement). Needs sipanel_quotation_lines installed (QL1/QL2 definitions).

Idempotent: a scope whose current released version neither prices the installation product nor claims
installation in its description is left alone (ALREADY_CORRECTED). Never touches a quotation.

Run (odoo shell):  docker exec -i [-e SIPANEL_V3_COMMIT=1] odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d <db> --no-http < this
Without SIPANEL_V3_COMMIT=1 the transaction is rolled back (dry run). Can also be exec()'d by another
shell script (SIPANEL_V3_LIBRARY=True), which then calls create_standing_seam_v3(env, wording) inside its own
transaction.
"""
import json
import os

ROOF_CODE = 'CS-STANDING-SEAM'
SCOPE_CODES = (ROOF_CODE, 'CS-STANDING-SEAM-FLASHING', 'CS-STANDING-SEAM-GUTTER')
INSTALL_CODE = 'SIP-000075'
# Supply-only customer descriptions (business decision 2026-10-06: Roof 88,000,000/m², Flashing 34,000,000/m and
# Gutter 67,000,000/m are SUPPLY ONLY; installation is charged only by the order-level line). Keyword-free on
# purpose, so release rule QL2 stays silent. Used on the clone; the owner approves the final Production text.
APPROVED_WORDING = {
    'CS-STANDING-SEAM': {
        'en_US': 'Supply of Standing Seam roof system (supply only).',
        'fa_IR': 'تأمین سیستم سقف استندینگ سیم (فقط تأمین).',
    },
    'CS-STANDING-SEAM-FLASHING': {
        'en_US': 'Supply of flashing & sealing package (supply only).',
        'fa_IR': 'تأمین پکیج فلاشینگ و آب‌بندی (فقط تأمین).',
    },
    'CS-STANDING-SEAM-GUTTER': {
        'en_US': 'Supply of gutter system (supply only).',
        'fa_IR': 'تأمین سیستم ناودان (فقط تأمین).',
    },
}


def _wording_rule():
    """The release-warning keyword rule QL2 of sipanel_quotation_lines (single source of truth)."""
    from odoo.addons.sipanel_quotation_lines.models.scope_version import INSTALLATION_WORDING
    return INSTALLATION_WORDING


def _stored_terms(env, version, field):
    env.cr.execute(f'SELECT "{field}" FROM sipanel_scope_version WHERE id = %s', (version.id,))
    return env.cr.fetchone()[0] or {}            # raw jsonb: no language fallback


def _plan(env, code, install):
    """What the scope's current released version needs: (scope, current, offending recipe lines, claims).
    Offending = SIPANEL recipe lines of installation WORK (System-mapped installation products + products flagged
    sipanel_installation_work) in ANY placement - release rule QL1. Claims = installation wording in the customer
    label or description, any stored language - release rule QL2."""
    scope = env['sipanel.scope'].search([('code', '=', code)])
    assert len(scope) == 1, f'{code}: {len(scope)} scopes'
    current = scope.current_version_id
    assert current and current.state == 'released', f'{code}: no released current version'
    work = env['product.product']._sipanel_installation_work_products() | install
    offending = current.recipe_line_ids.filtered(lambda l: l.responsibility == 'sipanel' and l.product_id in work)
    desc = _stored_terms(env, current, 'customer_description')
    rule = _wording_rule()
    claims = {f'{field}:{lang}': text for field in ('customer_label', 'customer_description')
              for lang, text in _stored_terms(env, current, field).items() if rule.search(text or '')}
    return scope, current, offending, desc, claims


def _release_next(env, scope, current, offending, desc, terms):
    prev_checksum = current.release_checksum
    report = {'scope': scope.code, 'previous_version': current.name, 'previous_version_id': current.id,
              'previous_checksum_verified_before': current.verify_release_checksum(),
              'previous_lines': len(current.recipe_line_ids)}
    action = current.action_new_version()
    draft = env['sipanel.scope.version'].browse(action['res_id'])
    removed = draft.recipe_line_ids.filtered(lambda l: l.product_id in offending.product_id)
    report['removed_lines'] = [{
        'sequence': l.sequence, 'product': l.product_id.default_code, 'placement': l.placement,
        'responsibility': l.responsibility, 'disclosure': l.disclosure, 'customer_eligible': l.customer_eligible,
        'basis': l.basis, 'execution_mode': l.execution_mode, 'cost_policy': l.cost_policy,
        'customer_label': l.with_context(lang='en_US').customer_label,
        'customer_label_fa': l.with_context(lang='fa_IR').customer_label} for l in removed]
    removed_codes = sorted(set(removed.product_id.mapped('default_code')))   # read before the unlink
    removed.unlink()
    # en_US always passed with fa_IR: a lone fa_IR term would overwrite the source
    draft.update_field_translations('customer_description', terms)
    report['description_before'] = desc
    report['description_after'] = _stored_terms(env, draft, 'customer_description')
    changes = ["customer description replaced by the supply-only wording"]
    if removed_codes:
        changes.insert(0, ', '.join(removed_codes)
                       + " removed from the recipe (installation no longer included in the anchor price)")
    draft.message_post(body=(
        f"Commercial model correction (2026-10-06, supply only), copied from {current.name}: " + "; ".join(changes)
        + ". Installation / Execution is quoted as a separate percentage line (sipanel_installation_pct)."))
    draft.action_release()
    report['release_warnings'] = [str(m.body) for m in draft.message_ids if 'Release warning' in str(m.body)]
    current.invalidate_recordset()
    report.update({
        'result': 'RELEASED', 'new_version': draft.name, 'new_version_id': draft.id, 'new_lines': len(draft.recipe_line_ids),
        'new_checksum': draft.release_checksum, 'previous_state_after': current.state,
        'previous_checksum_unchanged': current.release_checksum == prev_checksum,
        'previous_checksum_verified_after': current.verify_release_checksum(),
        'previous_lines_after': len(current.recipe_line_ids),
        'customer_label_en': draft.with_context(lang='en_US').customer_label,
        'customer_label_fa': draft.with_context(lang='fa_IR').customer_label,
        'customer_description_en': draft.with_context(lang='en_US').customer_description,
        'customer_description_fa': draft.with_context(lang='fa_IR').customer_description,
    })
    return report


def create_standing_seam_v3(env, wording=None):
    """wording: {scope code: {'en_US': ..., 'fa_IR': ...}}. Missing wording for a scope that needs a new
    version blocks the whole run (nothing created)."""
    wording = wording or {}
    install = env['product.product'].with_context(active_test=False).search([('default_code', '=', INSTALL_CODE)])
    assert len(install) == 1, f'{INSTALL_CODE}: {len(install)} products'
    plans, result, missing = [], {'scopes': {}}, []
    for code in SCOPE_CODES:
        scope, current, offending, desc, claims = _plan(env, code, install)
        if not offending and not claims:
            result['scopes'][code] = {'result': 'ALREADY_CORRECTED', 'current_version': current.name}
            continue
        terms = {lang: (wording.get(code, {}).get(lang) or '').strip() for lang in ('en_US', 'fa_IR')}
        if not all(terms.values()) or any(_wording_rule().search(t) for t in terms.values()):
            missing.append(code)
            result['scopes'][code] = {'result': 'BLOCKED_CUSTOMER_DESCRIPTION', 'current_version': current.name,
                                      'description_claims_installation_included': claims,
                                      'installation_lines_in_recipe': offending.mapped('sequence')}
        plans.append((scope, current, offending, desc, terms))
    if missing:
        result['result'] = 'BLOCKED_CUSTOMER_DESCRIPTION'
        result['action'] = ('Supply the approved customer description (en_US and fa_IR) for: '
                            + ', '.join(missing) + '; nothing was created.')
        return result
    for scope, current, offending, desc, terms in plans:
        result['scopes'][scope.code] = _release_next(env, scope, current, offending, desc, terms)
    result['result'] = 'RELEASED' if plans else 'ALREADY_CORRECTED'
    return result


if 'env' in globals() and not globals().get('SIPANEL_V3_LIBRARY'):
    result = create_standing_seam_v3(env, APPROVED_WORDING)
    print('SIPANEL_V3 ' + json.dumps(result, ensure_ascii=False, default=str))
    if os.environ.get('SIPANEL_V3_COMMIT') == '1' and result['result'] == 'RELEASED':
        env.cr.commit()
        print('SIPANEL_V3 COMMITTED')
    else:
        env.cr.rollback()
        print('SIPANEL_V3 ROLLED_BACK')
