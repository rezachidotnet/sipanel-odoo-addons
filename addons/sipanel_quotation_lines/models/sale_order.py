# -*- coding: utf-8 -*-
"""Installation / Execution percentage line and amount in words (work order 2026-10-05, B + C).

One system-managed sale.order.line, priced as a percentage of the untaxed subtotal of the lines whose
product is flagged `sipanel_installation_base`, always last on the quotation, recomputed while the
order is a quotation (draft/sent) and frozen afterwards. Taxes and totals stay native: the line is an
ordinary product line of the System's installation product, so its taxes come from the product and the
fiscal position like any other line.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx

INSTALL_GUARD = 'sipanel_installation_sync'
OPEN_STATES = ('draft', 'sent')
# Scope component placements that already put the installation product in front of the customer:
# INCLUDED in the anchor price or billed on its OWN line. A percentage line on top would charge it twice.
INSTALL_IN_SCOPE_PLACEMENTS = ('included_parent', 'own_line')


def format_pct(pct):
    """40.0 -> '40', 12.5 -> '12.5' (no trailing zeros, no locale grouping)."""
    return ('%.4f' % pct).rstrip('0').rstrip('.')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sipanel_installation_pct = fields.Float(
        string='Installation %', digits=(16, 4), tracking=True,
        default=lambda self: self.env.company.sipanel_installation_pct_default,
        help="Installation / Execution as a percentage of the untaxed subtotal of the installation-base "
             "items. Empty or 0 = no installation line. Frozen once the order is confirmed.")
    sipanel_installation_base_amount = fields.Monetary(
        string='Installation base', compute='_compute_sipanel_installation_amounts', currency_field='currency_id')
    sipanel_installation_amount = fields.Monetary(
        string='Installation amount', compute='_compute_sipanel_installation_amounts', currency_field='currency_id')

    @api.depends('order_line.price_subtotal', 'order_line.sipanel_is_installation_line',
                 'order_line.product_id.sipanel_installation_base')
    def _compute_sipanel_installation_amounts(self):
        for order in self:
            order.sipanel_installation_base_amount = sum(order._sipanel_installation_base_lines().mapped('price_subtotal'))
            order.sipanel_installation_amount = sum(order.order_line.filtered(
                lambda l: l.sipanel_is_installation_line and not l.display_type).mapped('price_subtotal'))

    # ------------------------------------------------------------------ CRUD
    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._sipanel_sync_installation()
        return orders

    def write(self, vals):
        if 'sipanel_installation_pct' in vals and not guard(self.env, INSTALL_GUARD):
            frozen = self.filtered(lambda o: o.state not in OPEN_STATES)
            if any(float_compare(o.sipanel_installation_pct, vals['sipanel_installation_pct'] or 0.0, precision_digits=4)
                   for o in frozen):
                raise UserError(self.env._(
                    "Order %s is no longer a quotation; its installation percentage is frozen.", frozen[0].name))
        res = super().write(vals)
        if (vals.get('sipanel_installation_pct') or 0.0) > 0 and not guard(self.env, INSTALL_GUARD):
            # an explicit percentage needs a System with an installation product (B2) - say so now,
            # not later when the first priced item is added
            for order in self.filtered(lambda o: o.state in OPEN_STATES):
                order._sipanel_installation_product()
        if not guard(self.env, INSTALL_GUARD) and {'sipanel_installation_pct', 'order_line', 'partner_id',
                                                   'sipanel_requested_system_id'} & set(vals):
            self._sipanel_sync_installation()
        return res

    def _get_copiable_order_lines(self):
        """A duplicated quotation does not copy the managed installation lines; its engine rebuilds them."""
        return super()._get_copiable_order_lines().filtered(lambda l: not l.sipanel_is_installation_line)

    # ------------------------------------------------------------------ installation engine
    def _sipanel_installation_base_lines(self):
        """Eligible supply / item lines (B1): flagged products only. Never the installation line itself,
        sections, notes or down payments."""
        self.ensure_one()
        return self.order_line.filtered(
            lambda l: not l.display_type and not l.is_downpayment and not l.sipanel_is_installation_line
            and l.product_id.product_tmpl_id.sipanel_installation_base)

    def _sipanel_installation_amount_for(self, base):
        self.ensure_one()
        return self.currency_id.round(base * (self.sipanel_installation_pct or 0.0) / 100.0)

    def _sipanel_installation_system(self):
        """The order's SIPANEL System (B2): from its Commercial Scopes, else its Requested System."""
        self.ensure_one()
        systems = self.env['account.analytic.account']
        for scope in self.sipanel_quote_scope_ids.filtered('active'):
            system = scope.system_id or scope.current_revision_id.system_id
            if not system and len(scope.source_version_id.system_ids) == 1:
                system = scope.source_version_id.system_ids
            systems |= system
        if len(systems) > 1:
            products = systems.mapped('sipanel_installation_product_id')
            if len(products) == 1 and all(systems.mapped('sipanel_installation_product_id')):
                return systems[0]
            raise UserError(self.env._(
                "Order %(o)s carries Scopes of several SIPANEL Systems (%(s)s) with different installation "
                "products; one installation percentage line cannot be priced for it. Set the installation "
                "percentage to 0 and quote installation explicitly.",
                o=self.name, s=', '.join(systems.mapped('name'))))
        return systems or self.sipanel_requested_system_id

    def _sipanel_installation_product(self):
        self.ensure_one()
        system = self._sipanel_installation_system()
        if not system:
            raise UserError(self.env._(
                "Order %s has an installation percentage but no SIPANEL System: add a Scope or set the "
                "Requested System, or set the installation percentage to 0.", self.name))
        product = system.sudo().sipanel_installation_product_id
        if not product:
            raise UserError(self.env._(
                "SIPANEL System \"%s\" has no installation product configured; no installation line can be "
                "created. Configure it on the System, or set the installation percentage to 0.", system.name))
        return product

    def _sipanel_check_installation_not_in_scope(self):
        """B3: a Scope snapshot that already includes (or bills) an installation product forbids the
        percentage line - that is a quotation made on a Scope version older than the corrected
        commercial model. Checked on the frozen quotation snapshot, never on today's master."""
        self.ensure_one()
        install_products = self.env['account.analytic.account'].sudo().search(
            [('sipanel_installation_product_id', '!=', False)]).mapped('sipanel_installation_product_id')
        if not install_products:
            return
        for scope in self.sipanel_quote_scope_ids.filtered('active'):
            comps = scope.current_revision_id.sudo().component_ids.filtered(
                lambda c: c.active_state == 'active' and c.responsibility == 'sipanel'
                and c.placement in INSTALL_IN_SCOPE_PLACEMENTS and c.product_id in install_products)
            if comps:
                raise UserError(self.env._(
                    "Scope %(s)s (version %(v)s) already includes %(p)s in its price. This quotation was "
                    "made on a Scope version older than the separate installation line; setting an "
                    "installation percentage would charge installation twice. Keep the percentage at 0, "
                    "or quote on the current Scope version.",
                    s=scope.display_name, v=scope.source_version_id.display_name or '-',
                    p=comps[0].product_id.display_name))

    def _sipanel_installation_label(self, lang, pct):
        env = self.with_context(lang=lang).env
        return env._("Installation & Execution (%(pct)s%% of item subtotal)", pct=format_pct(pct))

    def _sipanel_sync_installation(self):
        """Idempotent: create / update / remove the installation section + line. Quotations only."""
        Line = self.env['sale.order.line']
        for order in self:
            if order.state not in OPEN_STATES or guard(order.env, INSTALL_GUARD):
                continue
            ctx = guard_ctx(INSTALL_GUARD)
            managed = order.order_line.filtered('sipanel_is_installation_line')
            pct = order.sipanel_installation_pct or 0.0
            if pct < 0:
                raise UserError(self.env._("The installation percentage cannot be negative."))
            if pct and order.sipanel_quote_scope_ids:
                order._sipanel_check_installation_not_in_scope()
            base = sum(order._sipanel_installation_base_lines().mapped('price_subtotal'))
            if not pct or order.currency_id.is_zero(base):
                if managed:
                    managed.with_context(**ctx).unlink()
                continue
            product = order._sipanel_installation_product()
            lang = order.partner_id.lang or order.env.lang or 'en_US'
            amount = order._sipanel_installation_amount_for(base)
            product_l = product.with_context(lang=lang)
            name = order._sipanel_installation_label(lang, pct)
            if product_l.description_sale:
                name = f"{name}\n{product_l.description_sale}"
            others = order.order_line - managed
            top = max(others.mapped('sequence') or [0])
            section_vals = {'display_type': 'line_section', 'sequence': top + 1,
                            'name': order.with_context(lang=lang).env._("Installation & Execution")}
            line_vals = {'product_id': product.id, 'product_uom_qty': 1.0, 'product_uom_id': product.uom_id.id,
                         'price_unit': amount, 'discount': 0.0, 'name': name, 'sequence': top + 2}
            section = managed.filtered(lambda l: l.display_type == 'line_section')[:1]
            line = managed.filtered(lambda l: not l.display_type)[:1]
            # one section and one priced line, nothing else: duplicates are removed, never summed
            (managed - section - line).with_context(**ctx).unlink()
            for record, vals in ((section, section_vals), (line, line_vals)):
                if record:
                    changed = {f: v for f, v in vals.items() if Line._sipanel_value_differs(record, f, v)}
                    if changed:
                        record.with_context(**ctx).write(changed)
                else:
                    Line.with_context(**ctx).create(dict(vals, order_id=order.id, sipanel_is_installation_line=True))

    # ------------------------------------------------------------------ amount in words (C)
    def _sipanel_amount_total_in_words(self):
        """Native res.currency.amount_to_text in the document language (the report runs under t-lang)."""
        self.ensure_one()
        return self.currency_id.with_context(lang=self.env.lang).amount_to_text(self.amount_total)
