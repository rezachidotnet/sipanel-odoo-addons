# -*- coding: utf-8 -*-
"""sale.order.line side of the installation engine: the marker, the recompute triggers and the
protection of the system-managed lines (work order 2026-10-05, B)."""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard

from .sale_order import INSTALL_GUARD, OPEN_STATES

# A change of any of these on an ordinary line can change the installation base or the position of the
# installation block (it must stay last).
BASE_TRIGGER_FIELDS = {'product_id', 'product_uom_qty', 'product_uom_id', 'price_unit', 'discount', 'tax_ids',
                       'display_type', 'sequence', 'is_downpayment', 'order_id'}
# The managed lines are rewritten from the order whenever one of these is touched outside the engine.
MANAGED_FIELDS = {'product_id', 'product_uom_qty', 'product_uom_id', 'price_unit', 'discount', 'name',
                  'sequence', 'display_type'}


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # copy=False: a duplicated quotation does not copy the managed lines at all (sale.order.copy_data drops
    # them); the engine rebuilds them on the copy from its own percentage and base.
    sipanel_is_installation_line = fields.Boolean(
        string='Installation line', readonly=True, copy=False, index=True,
        help="System-managed Installation / Execution line (and its section). Never part of the "
             "installation base, never a Scope component, never in Scope costing.")

    @api.model
    def _sipanel_value_differs(self, record, field_name, value):
        current = record[field_name]
        if hasattr(current, 'id'):
            current = current.id
        if isinstance(current, float) or isinstance(value, float):
            return abs((current or 0.0) - (value or 0.0)) > 1e-6
        return (current or False) != (value or False)

    @api.model_create_multi
    def create(self, vals_list):
        if not guard(self.env, INSTALL_GUARD) and any(v.get('sipanel_is_installation_line') for v in vals_list):
            # a forged marker would let any line escape the base or be rewritten by the engine
            raise UserError(self.env._("The installation line marker is set by the installation engine only."))
        lines = super().create(vals_list)
        if not guard(self.env, INSTALL_GUARD):
            lines.order_id._sipanel_sync_installation()
        return lines

    def write(self, vals):
        if 'sipanel_is_installation_line' in vals and not guard(self.env, INSTALL_GUARD):
            raise UserError(self.env._("The installation line marker is set by the installation engine only."))
        orders = self.order_id
        res = super().write(vals)
        if not guard(self.env, INSTALL_GUARD):
            touched_managed = self.filtered('sipanel_is_installation_line') and MANAGED_FIELDS & set(vals)
            if touched_managed or BASE_TRIGGER_FIELDS & set(vals):
                (orders | self.order_id)._sipanel_sync_installation()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_managed_installation(self):
        if guard(self.env, INSTALL_GUARD):
            return
        for line in self.filtered('sipanel_is_installation_line'):
            order = line.order_id
            if order.state in OPEN_STATES and order.sipanel_installation_pct:
                raise UserError(self.env._(
                    "The Installation / Execution lines of %s are managed by its installation percentage; "
                    "set the percentage to 0 to remove them.", order.name))

    def unlink(self):
        orders = self.order_id
        res = super().unlink()
        if not guard(self.env, INSTALL_GUARD):
            orders.exists()._sipanel_sync_installation()
        return res

    # The governed amount must not be replaced by the pricelist ("Update prices", a pricelist or UoM change).
    def _compute_price_unit(self):
        return super(SaleOrderLine, self.filtered(lambda l: not l.sipanel_is_installation_line))._compute_price_unit()

    def _compute_discount(self):
        managed = self.filtered('sipanel_is_installation_line')
        for line in managed:
            line.discount = 0.0
        return super(SaleOrderLine, self - managed)._compute_discount()
