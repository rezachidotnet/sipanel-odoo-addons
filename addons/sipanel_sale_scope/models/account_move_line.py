# -*- coding: utf-8 -*-
"""Invoice-line traceability back to the governed Scope (STEP 2B).

Only provenance is added here. Amount, tax, fiscal position, currency and
rounding stay entirely native: nothing in this file computes money.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard

TRACE_FIELDS = {
    'sipanel_source_component_id', 'sipanel_source_revision_id',
    'sipanel_source_quote_scope_id', 'sipanel_source_scope_id',
    'sipanel_origin_key', 'sipanel_source_line_id',
}


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    sipanel_source_component_id = fields.Many2one('sipanel.quote.scope.component', readonly=True,
                                                  copy=False, ondelete='restrict', index=True)
    sipanel_source_revision_id = fields.Many2one('sipanel.quote.scope.revision', readonly=True,
                                                 copy=False, ondelete='restrict', index=True)
    sipanel_source_quote_scope_id = fields.Many2one('sipanel.quote.scope', readonly=True,
                                                    copy=False, ondelete='restrict')
    sipanel_source_scope_id = fields.Many2one('sipanel.scope', readonly=True, copy=False,
                                              ondelete='restrict')
    sipanel_origin_key = fields.Char(readonly=True, copy=False, index=True)
    sipanel_source_line_id = fields.Many2one('sale.order.line', readonly=True, copy=False,
                                             ondelete='restrict')

    @api.model
    def _sipanel_trace_guarded(self):
        return guard(self.env, 'sipanel_projection') or guard(self.env, 'sipanel_invoice_trace')

    @api.model_create_multi
    def create(self, vals_list):
        # The native Sale->Invoice flow fills these through _prepare_invoice_line,
        # which runs inside Odoo's own create. Anything else - a hand-made invoice,
        # an import, an RPC payload - must not be able to claim Scope provenance it
        # does not have.
        if not self.env.context.get('sipanel_from_sale_invoice'):
            for vals in vals_list:
                supplied = TRACE_FIELDS & set(vals)
                if supplied and not vals.get('sale_line_ids'):
                    raise UserError(self.env._(
                        "Fields %s trace an invoice line back to a governed Scope and are set "
                        "only by the Quotation -> Confirmation -> Create Invoice flow.",
                        ', '.join(sorted(supplied))))
        return super().create(vals_list)

    def write(self, vals):
        if not self._sipanel_trace_guarded():
            supplied = TRACE_FIELDS & set(vals)
            if supplied:
                raise UserError(self.env._(
                    "Scope provenance on an invoice line is immutable (%s).",
                    ', '.join(sorted(supplied))))
        return super().write(vals)
