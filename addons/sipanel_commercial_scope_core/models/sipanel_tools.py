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
