# -*- coding: utf-8 -*-
"""Standing Seam commercial model correction (work order 2026-10-05, B "Commercial model" / B3).

The released CS-STANDING-SEAM version still lists SIP-000075 "Standing Seam Installation Service" as an
INCLUDED_PARENT, customer-eligible recipe line: installation priced inside the Roof anchor. The frozen
business decision is the opposite - installation is a separate percentage line. A released version is
immutable, so this creates the NEXT version through the native path:

    current released version --action_new_version--> DRAFT copy (same content, translations, keys renewed)
    DRAFT: remove the recipe line(s) of the System's installation product (nothing else changes)
    DRAFT --action_release--> RELEASED; the previous version becomes SUPERSEDED (state only, content and
    release checksum untouched - verified before and after)

Customer text gate: the released Roof description says "supplied and installed ... Installation is included in
this price". Copied unchanged into the new version it would print next to a separately charged installation
line. Customer wording is the owner's decision, so the script does NOT release while the description still
claims installation is included, unless the corrected text is supplied:
    SIPANEL_V3_DESCRIPTION_EN=<approved English text>   (required when the gate trips)
    SIPANEL_V3_DESCRIPTION_FA=<approved Persian text>   (optional; required if a fa_IR term is stored)
PROPOSED_DESCRIPTION_EN below is a proposal for the owner, used only by the clone acceptance run.

Idempotent: when the current released version no longer prices the installation product in the
parent, nothing happens. Never touches a quotation.

Run (odoo shell):  docker exec -i [-e SIPANEL_V3_COMMIT=1] odoo-sipanel odoo shell -c /etc/odoo/odoo.conf -d <db> --no-http < this
Without SIPANEL_V3_COMMIT=1 the transaction is rolled back (dry run). Can also be exec()'d by another
shell script, which then calls create_standing_seam_v3(env) inside its own transaction.
"""
import json
import os

SCOPE_CODE = 'CS-STANDING-SEAM'
INSTALL_CODE = 'SIP-000075'
INCLUDED_CLAIMS = ('installation is included', 'supplied and installed')
PROPOSED_DESCRIPTION_EN = (
    'Complete Standing Seam roofing system, supplied, including all standard roofing components for this project. '
    'Installation / execution is quoted separately as a percentage of the item subtotal. '
    'Quantities and unit price are confirmed on the commercial quotation.')


def _stored_terms(env, version, field):
    env.cr.execute(f'SELECT "{field}" FROM sipanel_scope_version WHERE id = %s', (version.id,))
    return env.cr.fetchone()[0] or {}            # raw jsonb: no language fallback


def create_standing_seam_v3(env):
    scope = env['sipanel.scope'].search([('code', '=', SCOPE_CODE)])
    assert len(scope) == 1, f'{SCOPE_CODE}: {len(scope)} scopes'
    install = env['product.product'].with_context(active_test=False).search([('default_code', '=', INSTALL_CODE)])
    assert len(install) == 1, f'{INSTALL_CODE}: {len(install)} products'
    current = scope.current_version_id
    assert current and current.state == 'released', f'{SCOPE_CODE}: no released current version'
    offending = current.recipe_line_ids.filtered(
        lambda l: l.product_id == install and l.placement in ('included_parent', 'own_line'))
    report = {'scope': scope.code, 'previous_version': current.name, 'previous_version_id': current.id}
    if not offending:
        report['result'] = 'ALREADY_CORRECTED'
        return report
    desc = _stored_terms(env, current, 'customer_description')
    claims = [lang for lang, text in desc.items() if any(c in (text or '').lower() for c in INCLUDED_CLAIMS)]
    new_terms = {}
    if claims:
        new_en = (os.environ.get('SIPANEL_V3_DESCRIPTION_EN') or '').strip()
        new_fa = (os.environ.get('SIPANEL_V3_DESCRIPTION_FA') or '').strip()
        report['description_claims_installation_included'] = {lang: desc[lang] for lang in claims}
        if not new_en or ('fa_IR' in desc and not new_fa):
            report['result'] = 'BLOCKED_CUSTOMER_DESCRIPTION'
            report['action'] = ('Supply the approved corrected customer description (SIPANEL_V3_DESCRIPTION_EN'
                                + (' and SIPANEL_V3_DESCRIPTION_FA' if 'fa_IR' in desc else '') + '); nothing was created.')
            report['proposed_description_en'] = PROPOSED_DESCRIPTION_EN
            return report
        new_terms = {'en_US': new_en}            # en_US always passed: a lone fa_IR term would overwrite the source
        if new_fa:
            new_terms['fa_IR'] = new_fa
    prev_checksum = current.release_checksum
    report['previous_checksum_verified_before'] = current.verify_release_checksum()
    report['previous_lines'] = len(current.recipe_line_ids)
    action = current.action_new_version()
    draft = env['sipanel.scope.version'].browse(action['res_id'])
    removed = draft.recipe_line_ids.filtered(lambda l: l.product_id == install)
    report['removed_lines'] = [{
        'sequence': l.sequence, 'product': l.product_id.default_code, 'placement': l.placement,
        'responsibility': l.responsibility, 'disclosure': l.disclosure, 'customer_eligible': l.customer_eligible,
        'basis': l.basis, 'execution_mode': l.execution_mode, 'cost_policy': l.cost_policy,
        'customer_label': l.with_context(lang='en_US').customer_label,
        'customer_label_fa': l.with_context(lang='fa_IR').customer_label} for l in removed]
    removed.unlink()
    if new_terms:
        draft.update_field_translations('customer_description', new_terms)
        report['description_before'] = desc
        report['description_after'] = _stored_terms(env, draft, 'customer_description')
    draft.message_post(body=(
        f"Commercial model correction (2026-10-05): {INSTALL_CODE} removed from the recipe. Installation / "
        f"Execution is no longer included in the Roof anchor price; it is quoted as a separate percentage line "
        f"(sipanel_installation_pct). Copied from {current.name}"
        + ("; customer description corrected (it claimed installation was included)." if new_terms else "; no other change.")))
    draft.action_release()
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


if 'env' in globals() and not globals().get('SIPANEL_V3_LIBRARY'):
    result = create_standing_seam_v3(env)
    print('SIPANEL_V3 ' + json.dumps(result, ensure_ascii=False, default=str))
    if os.environ.get('SIPANEL_V3_COMMIT') == '1':
        env.cr.commit()
        print('SIPANEL_V3 COMMITTED')
    else:
        env.cr.rollback()
        print('SIPANEL_V3 ROLLED_BACK (dry run)')
