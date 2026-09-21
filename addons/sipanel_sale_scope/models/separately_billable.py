# -*- coding: utf-8 -*-
"""Separately-billable Sale Line projection (STEP 2B).

A component whose ``placement`` is ``own_line`` is billed on its own customer
line instead of inside the anchor price. Until now that existed only as a
sentence in the generated note; here it becomes a real, governed, idempotent
``sale.order.line`` so that Odoo's native Sale -> Invoice flow can turn it into
an ``account.move.line``.

Nothing in this module invents a Billing Treatment. ``placement == 'own_line'``
is the installed representation and stays the authority; the other axes
(responsibility, disclosure, certainty, acceptance, active state) are applied
orthogonally on top of it.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard_ctx, sha256_of


class SipanelQuoteScopeRevision(models.Model):
    _inherit = 'sipanel.quote.scope.revision'

    projected_line_ids = fields.One2many('sale.order.line', 'sipanel_source_revision_id',
                                         string='Separately billable lines', readonly=True)
    projected_line_count = fields.Integer(compute='_compute_projection_totals')
    anchor_amount = fields.Monetary(currency_field='currency_id', compute='_compute_projection_totals',
                                    help="Untaxed amount carried by the anchor line.")
    separate_amount = fields.Monetary(currency_field='currency_id', compute='_compute_projection_totals',
                                      help="Untaxed amount carried by the projected separately-billable lines.")
    reconciliation_json = fields.Json(compute='_compute_projection_totals',
                                      help="Per-revision reconciliation of anchor vs separately billable amounts.")
    reconciliation_ok = fields.Boolean(compute='_compute_projection_totals')

    # ------------------------------------------------------------------ totals
    @api.depends('projected_line_ids.price_subtotal', 'projected_line_ids.product_uom_qty',
                 'quote_scope_id.anchor_line_id.price_subtotal', 'component_ids.separately_billable',
                 'component_ids.sell_price_status', 'component_ids.active_state')
    def _compute_projection_totals(self):
        for rev in self:
            lines = rev.projected_line_ids
            anchor = rev.quote_scope_id.anchor_line_id
            rev.projected_line_count = len(lines)
            rev.anchor_amount = anchor.price_subtotal if anchor else 0.0
            rev.separate_amount = sum(lines.mapped('price_subtotal'))
            rev.reconciliation_json = rev._build_reconciliation()
            rev.reconciliation_ok = not rev.reconciliation_json.get('problems')

    def _build_reconciliation(self):
        """Explicit per-revision reconciliation.

        The invariant is not an arithmetic identity on the order total - Odoo
        already sums its own lines correctly - but that no component is counted
        on both sides, and that every component that should carry revenue does
        so exactly once.
        """
        self.ensure_one()
        comps = self.component_ids
        own = comps.filtered('separately_billable')
        lines = self.projected_line_ids
        by_key = {l.sipanel_origin_key: l for l in lines}
        problems, rows = [], []
        for comp in own.sorted(lambda c: (c.sequence, c.id)):
            key = self._origin_key(comp)
            line = by_key.pop(key, None)
            rows.append({
                'component': comp.occurrence_uid, 'label': comp.customer_label_resolved or comp.name,
                'qty': comp.final_qty, 'sell_price_status': comp.sell_price_status,
                'line_id': line.id if line else None,
                'line_qty': line.product_uom_qty if line else None,
                'line_subtotal': line.price_subtotal if line else None,
            })
            if line is None and comp.sell_price_status != 'missing' and comp.product_id:
                problems.append(f"component {comp.occurrence_uid} is separately billable but has no line")
        for orphan_key, line in by_key.items():
            if line.product_uom_qty:
                problems.append(f"line {line.id} has no eligible component ({orphan_key})")
        # a consumed line from a superseded revision cannot be withdrawn automatically
        consumed = self.env['sale.order.line'].search([
            ('sipanel_source_quote_scope_id', '=', self.quote_scope_id.id),
            ('sipanel_is_generated', '=', True),
            ('sipanel_source_revision_id', '!=', self.id),
        ]).filtered(lambda l: l.invoice_lines or l.qty_delivered)
        for line in consumed:
            problems.append(
                f"line {line.id} from a superseded revision is already invoiced or delivered; "
                f"settle it through a change order")
        # a component may never be billed inside the anchor AND on its own line
        included = comps.filtered(lambda c: c.placement == 'included_parent' and c.separately_billable)
        if included:
            problems.append("component is both included and separately billable")
        return {
            'revision': self.display_name,
            'anchor_amount': self.quote_scope_id.anchor_line_id.price_subtotal
            if self.quote_scope_id.anchor_line_id else 0.0,
            'separate_amount': sum(lines.mapped('price_subtotal')),
            'separately_billable_components': len(own),
            'projected_lines': len(lines),
            'rows': rows,
            'problems': problems,
        }

    # ------------------------------------------------------------------ keys
    @api.model
    def _origin_key(self, component):
        """Stable within a revision, distinct across revisions and duplicates.

        `occurrence_uid` is unique per revision and survives an amendment, and
        the revision id makes the key globally unique - which is what the
        database unique index on sale_order_line needs.
        """
        return f"{component.revision_id.id}:{component.occurrence_uid}"

    # ------------------------------------------------------------------ readiness
    def _projection_blocking_issues(self):
        """Blocking reasons a separately-billable component cannot be sent."""
        self.ensure_one()
        _ = self.env._
        issues = []
        for comp in self.component_ids.filtered('separately_billable').sorted(lambda c: (c.sequence, c.id)):
            label = comp.customer_label_resolved or comp.name or comp.occurrence_uid
            if not comp.product_id:
                if comp.kind == 'estimate_only':
                    issues.append(('SB_ESTIMATE_PRODUCT', _(
                        "%s is separately billable but is an ESTIMATE_ONLY component with no "
                        "resolved product; it cannot be invoiced. Resolve it to a product or "
                        "change its placement.", label)))
                else:
                    issues.append(('SB_NO_PRODUCT', _(
                        "%s is separately billable but has no invoiceable product.", label)))
            if comp.sell_price_status == 'missing':
                issues.append(('SB_PRICE_MISSING', _(
                    "%s is separately billable but its selling price is missing. Set a governed "
                    "price, or record a reason if it is deliberately zero.", label)))
        return issues

    # ------------------------------------------------------------------ projection
    def _projected_line_vals(self, component, key):
        """Customer-facing content of a generated line.

        Everything comes from the frozen quotation snapshot: the already-resolved
        label, the snapshot quantity, the governed unit and the governed selling
        price. Master translations are never re-read here. Taxes and the fiscal
        position are left to Odoo, which computes them from the product.
        """
        self.ensure_one()
        scope = self.quote_scope_id
        anchor = scope.anchor_line_id
        name = (component.customer_label_resolved or component.customer_label_fa
                or component.customer_label_en or component.name or '')
        return {
            'order_id': self.order_id.id,
            'product_id': component.product_id.id,
            'product_uom_id': component.uom_id.id,
            'product_uom_qty': self._projected_qty(component),
            'name': name,
            'sequence': (anchor.sequence if anchor else 10) + 1,
            'sipanel_is_generated': True,
            'sipanel_origin_key': key,
            'sipanel_source_component_id': component.id,
            'sipanel_source_revision_id': self.id,
            'sipanel_source_quote_scope_id': scope.id,
            'sipanel_source_scope_id': scope.source_scope_id.id,
            'sipanel_snapshot_language': self.resolved_language or self.language,
            'sipanel_placement_snapshot': component.placement,
            'sipanel_certainty_snapshot': component.certainty,
            'sipanel_qty_provenance': f"{component.basis}:{component.final_qty}",
            'sipanel_price_provenance': f"{component.sell_price_source}:{component.sell_price_status}",
            'sipanel_invoice_gate': self._invoice_gate(component),
        }

    def _projected_qty(self, component):
        """An unaccepted option is an ordinary line at quantity zero (native Odoo
        optional-product behaviour); it becomes invoiceable on acceptance."""
        self.ensure_one()
        scope = self.quote_scope_id
        if scope.is_optional and scope.acceptance_state != 'accepted':
            return 0.0
        return component.final_qty or 0.0

    def _invoice_gate(self, component):
        """Why this line must not be invoiced yet, or '' when it may be.

        A provisional component is shown to the customer as provisional but its
        quantity or price is not final, so it is held back from invoicing until
        it is resolved to firm. The installed source has no approved revenue
        recognition policy that could lift this - `sipanel.cost.recognition.policy`
        governs COST routes - and inventing one is out of scope, so the gate is
        unconditional until resolution.
        """
        if component.certainty == 'provisional':
            return 'provisional'
        if component.resolution_state == 'open':
            return 'unresolved'
        return ''

    def _sync_separately_billable_lines(self):
        """Idempotent upsert of the projection. Safe to call as often as you like."""
        SOL = self.env['sale.order.line']
        for rev in self:
            if rev.state != 'working':
                # sealed projections are frozen; a change needs a new revision
                continue
            scope = rev.quote_scope_id
            if not scope.anchor_line_id or not rev.order_id:
                continue
            eligible = rev.component_ids.filtered(
                lambda c: c.separately_billable and c.product_id)
            existing = SOL.with_context(active_test=False).search(
                [('sipanel_source_revision_id', '=', rev.id)])
            by_key = {l.sipanel_origin_key: l for l in existing}
            seen = set()
            ctx = guard_ctx('sipanel_projection')
            for index, comp in enumerate(eligible.sorted(lambda c: (c.sequence, c.id))):
                key = rev._origin_key(comp)
                seen.add(key)
                vals = rev._projected_line_vals(comp, key)
                vals['sequence'] = vals['sequence'] + index
                line = by_key.get(key)
                if line:
                    changed = {f: v for f, v in vals.items()
                               if f not in ('order_id',) and rev._differs(line, f, v)}
                    if changed:
                        line.with_context(**ctx).write(changed)
                else:
                    line = SOL.with_context(**ctx).create(vals)
                    by_key[key] = line
                # the governed price is written after creation so Odoo's native
                # pricelist computation cannot overwrite a manual decision
                if rev._differs(line, 'price_unit', comp.sell_price_unit or 0.0):
                    line.with_context(**ctx).write({'price_unit': comp.sell_price_unit or 0.0})
            for key, line in by_key.items():
                if key in seen:
                    continue
                rev._retire_projected_line(line)
            rev._retire_superseded_projection()
        return True

    def _retire_superseded_projection(self):
        """Remove the projection of PRIOR revisions of the same quotation Scope.

        An amendment creates a new working revision and a fresh projection. If
        the previous revision's lines stayed, the same component would be billed
        twice on one order - which is precisely the double counting this step
        exists to prevent.

        A prior line that has already been invoiced or delivered is history and
        is left alone; that is the change-order boundary, and it is reported as a
        reconciliation problem so an operator handles it deliberately instead of
        the projection silently guessing.
        """
        self.ensure_one()
        scope = self.quote_scope_id
        superseded = self.env['sale.order.line'].search([
            ('sipanel_source_quote_scope_id', '=', scope.id),
            ('sipanel_is_generated', '=', True),
            ('sipanel_source_revision_id', '!=', self.id),
        ])
        for line in superseded:
            if line.invoice_lines or line.qty_delivered:
                continue          # consumed: keep it, and flag it in the reconciliation
            line.with_context(**guard_ctx('sipanel_projection')).unlink()
        return True

    @api.model
    def _differs(self, record, field_name, value):
        current = record[field_name]
        if hasattr(current, 'id'):
            current = current.id
        if isinstance(current, float) or isinstance(value, float):
            return abs((current or 0.0) - (value or 0.0)) > 1e-6
        return (current or False) != (value or False)

    @api.model
    def _retire_projected_line(self, line):
        """Remove a projection whose component is gone, or neutralise it when it
        already carries operational history."""
        ctx = guard_ctx('sipanel_projection')
        if line.invoice_lines or line.qty_delivered:
            if line.product_uom_qty:
                line.with_context(**ctx).write({'product_uom_qty': 0.0})
            return False
        line.with_context(**ctx).unlink()
        return True


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_invoiceable_lines(self, final=False):
        """Hold back generated lines that are not allowed to invoice yet.

        Unaccepted options need no rule here: they are quantity zero and Odoo
        already skips them. This gate is for provisional or unresolved content.
        """
        lines = super()._get_invoiceable_lines(final=final)
        blocked = lines.filtered(lambda l: l.sipanel_is_generated and l.sipanel_invoice_gate)
        return lines - blocked

    def action_sipanel_sync_scope_lines(self):
        """Manual fallback for the operator. Synchronisation is automatic on every
        governed transition; this button only makes it visible and repeatable."""
        for order in self:
            revisions = order.sipanel_quote_scope_ids.mapped('current_revision_id')
            revisions.filtered(lambda r: r.state == 'working')._sync_separately_billable_lines()
        return True
