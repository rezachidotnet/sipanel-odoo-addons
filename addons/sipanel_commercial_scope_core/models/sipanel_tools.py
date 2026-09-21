# -*- coding: utf-8 -*-
"""Shared pure helpers for the SIPANEL Commercial Scope modules.

No ORM access here: every function is deterministic and unit-testable.
Decision references: C1-D04 (per-line rounding), C2-D03, C0-D07.
"""
import hashlib
import json
import math
import uuid

from odoo.tools import float_round

# AM-02 orthogonal treatment axes
RESPONSIBILITY = [('sipanel', 'SIPANEL'), ('customer', 'Customer')]
PLACEMENT = [
    ('included_parent', 'Included in parent line'),
    ('own_line', 'Own customer line'),
    ('no_customer_line', 'No customer line'),
]
ACCEPTANCE = [('base', 'Base'), ('offered', 'Offered'), ('accepted', 'Accepted'), ('declined', 'Declined')]
CERTAINTY = [('firm', 'Firm'), ('provisional', 'Provisional')]
DISCLOSURE = [('customer_eligible', 'Customer eligible'), ('internal_only', 'Internal only')]
PRESETS = [
    ('included', 'INCLUDED'),
    ('separately_billable', 'SEPARATELY_BILLABLE'),
    ('optional', 'OPTIONAL'),
    ('provisional', 'PROVISIONAL'),
    ('customer_scope', 'CUSTOMER_SCOPE'),
    ('internal_only', 'INTERNAL_ONLY'),
    ('custom', 'CUSTOM'),
]
BASIS = [
    ('per_scope_qty', 'Per scope quantity'),
    ('fixed', 'Fixed'),
    ('manual', 'Manual'),
    ('percent_of_quantity', 'Percent of quantity'),
    ('percent_of_cost', 'Percent of cost'),
]
PERCENT_BASES = ('percent_of_quantity', 'percent_of_cost')
EXECUTION_MODE = [
    ('stock_issue', 'Stock issue'),
    ('buy_direct', 'Buy direct'),
    ('manufacture', 'Manufacture'),
    ('labour', 'Labour'),
    ('equipment_service', 'Equipment / service'),
    ('native_anchor_covered', 'Covered by native anchor'),
    ('no_action', 'No action'),
]
NO_ACTION_REASON = [
    ('customer_responsibility', 'Customer responsibility'),
    ('allowance', 'Allowance'),
    ('declined_option', 'Declined option'),
    ('covered_cost', 'Covered cost'),
]
DIMENSION_FAMILY = [
    ('count', 'Count'), ('length', 'Length'), ('area', 'Area'), ('volume', 'Volume'),
    ('mass', 'Mass'), ('time', 'Time'), ('other', 'Other'),
]
ROUNDING_MODE = [('none', 'None'), ('up', 'Up'), ('nearest', 'Nearest'), ('down', 'Down')]
KIND = [('product', 'Product'), ('estimate_only', 'Estimate only')]
OWNER_MODE = [('native_line_owner', 'NATIVE_LINE_OWNER'), ('component_bridge_owner', 'COMPONENT_BRIDGE_OWNER')]


def round_to_increment(value, increment, mode):
    """Per-line rounding (C1-D04). increment <= 0 or mode 'none' => unchanged."""
    if not increment or increment <= 0 or mode in (False, None, 'none'):
        return value
    ratio = value / increment
    if mode == 'up':
        n = math.ceil(ratio - 1e-9)
    elif mode == 'down':
        n = math.floor(ratio + 1e-9)
    else:
        n = math.floor(ratio + 0.5)
    return float_round(n * increment, precision_digits=6)


def preset_from_axes(responsibility, placement, acceptance, certainty, disclosure):
    """Derive the AM-02 preset label from the five axes (label is derived, never authoritative)."""
    if disclosure == 'internal_only':
        return 'internal_only'
    if responsibility == 'customer':
        return 'customer_scope'
    if certainty == 'provisional':
        return 'provisional'
    if placement == 'own_line' and acceptance in ('offered', 'accepted', 'declined'):
        return 'optional'
    if placement == 'own_line' and acceptance == 'base':
        return 'separately_billable'
    if placement == 'included_parent' and acceptance == 'base':
        return 'included'
    return 'custom'


def canonical_json(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)


def sha256_of(payload):
    if isinstance(payload, (dict, list, tuple)):
        payload = canonical_json(payload)
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def find_cycle(edges):
    """edges: {node: set(nodes)}. Return True if a cycle exists (DFS)."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {n: WHITE for n in edges}

    def visit(n):
        colour[n] = GREY
        for m in edges.get(n, ()):
            c = colour.get(m, WHITE)
            if c == GREY:
                return True
            if c == WHITE and visit(m):
                return True
        colour[n] = BLACK
        return False

    return any(colour[n] == WHITE and visit(n) for n in list(edges))


# ---------------------------------------------------------------------------
# Internal transaction guards (CD-12). RPC callers can send any context key, so a
# bare context flag must never unlock a privileged path. Internal code passes the
# flag together with a process-local token that no external caller can know.
GUARD_TOKEN = uuid.uuid4().hex


def guard_ctx(*names):
    """Context values that activate the given internal guard flags."""
    ctx = {name: True for name in names}
    ctx['sipanel_guard_token'] = GUARD_TOKEN
    return ctx


def guard(env, name):
    """True only when the flag was set by internal code (token matches)."""
    return bool(env.context.get(name)) and env.context.get('sipanel_guard_token') == GUARD_TOKEN


# ---------------------------------------------------------------------------
# Native translation helpers (STEP 2A).
#
# Odoo 19 stores a `translate=True` field in a jsonb column keyed by language,
# with `en_US` as the source term. Reading the field in a language context
# silently falls back to `en_US` when that language has no stored term, and so
# does `Model.get_field_translations` — verified against the installed source:
# `Text._insert_cache` fills every installed language with `val['en_US']` when
# `prefetch_langs` is set, which is exactly what `get_field_translations` uses.
# A customer-facing quotation must never ship that fallback silently, so we need
# to know whether a term is really stored.
#
# `Text._get_stored_translations` is the only accessor in the installed ORM that
# returns the raw jsonb map without applying the fallback
# (odoo/orm/fields_textual.py). It is module-private but it is an ORM accessor,
# not hand-written translation SQL: it flushes the record and reads back the
# column Odoo itself wrote. The dependency is kept in this one place.
#
# If a future Odoo removes it we FAIL CLOSED rather than degrade. The obvious
# degradation - reading the field under each language context and treating a
# non-empty value as a stored term - is exactly wrong: that read returns the
# en_US fallback, so every language would look translated and a Persian
# customer could be sent English text with no warning. A hard error is
# recoverable by a developer; a silent mistranslation on a sent quotation is
# not.

class MissingTranslationAccessor(RuntimeError):
    """The ORM no longer exposes a raw stored-translation accessor.

    Deliberately a technical error, not a UserError: it means the code must be
    ported, and no business decision can be taken while it is raised.
    """


def stored_translations(record, field_name):
    """Raw {lang: term} actually stored for a translatable field, no fallback.

    Returns {} when nothing is stored. Empty and whitespace-only terms are
    dropped, so callers can treat the result as "these languages are ready".
    """
    record.ensure_one()
    field = record._fields[field_name]
    if not field.translate:
        raise ValueError(f"{record._name}.{field_name} is not translatable")
    if not record.id:
        return {}
    getter = getattr(field, '_get_stored_translations', None)
    if getter is None:
        raise MissingTranslationAccessor(
            f"This Odoo build has no {type(field).__name__}._get_stored_translations, "
            f"so a stored translation of {record._name}.{field_name} cannot be told "
            f"apart from the en_US fallback. SIPANEL refuses to guess: customer-facing "
            f"language readiness depends on this distinction. Port "
            f"sipanel_tools.stored_translations() to the new ORM accessor."
        )
    raw = getter(record) or {}
    return {lang: term.strip() for lang, term in raw.items()
            if isinstance(term, str) and term.strip()}


def has_translation(record, field_name, lang):
    """True only when `lang` really has a stored, non-empty term."""
    return bool(stored_translations(record, field_name).get(lang))


def resolve_customer_text(record, field_name, lang, fallback_lang='en_US'):
    """Resolve customer-facing text for `lang`.

    Returns (value, used_lang, is_fallback). `is_fallback` is True whenever the
    requested language had no stored term, including when the value returned is
    the source term. Callers decide whether a fallback is acceptable: it is for
    a draft (with a warning), never for sealing a customer quotation.
    """
    terms = stored_translations(record, field_name)
    if lang and terms.get(lang):
        return terms[lang], lang, False
    if terms.get(fallback_lang):
        return terms[fallback_lang], fallback_lang, True
    if terms:
        used = sorted(terms)[0]
        return terms[used], used, True
    return '', None, True


def translation_map(record, field_name):
    """Deterministic {lang: term} for checksums: sorted by language code."""
    terms = stored_translations(record, field_name)
    return {lang: terms[lang] for lang in sorted(terms)}


SNAPSHOT_LANGS = ('fa_IR', 'en_US')


def snapshot_customer_text(master, field_name, lang, snapshot_langs=SNAPSHOT_LANGS):
    """Freeze one customer-facing master term into a quotation snapshot.

    Returns (terms, resolved, provenance):
      terms      {lang: term} limited to `snapshot_langs`, containing only terms
                 that are really stored - an English term is never written into
                 the Persian snapshot column, and vice versa;
      resolved   the term for `lang`, or '' when that language has none. Callers
                 may fall back for a draft, but the fallback is always visible in
                 the provenance so sealing can refuse it;
      provenance {'lang': used or None, 'fallback': bool, 'available': [langs]}.
    """
    terms = stored_translations(master, field_name)
    resolved = terms.get(lang, '')
    return (
        {code: terms[code] for code in snapshot_langs if terms.get(code)},
        resolved,
        {'lang': lang if resolved else None, 'fallback': not resolved,
         'available': sorted(terms)},
    )
