# -*- coding: utf-8 -*-
"""Controlled Project Site change WITH fiscal impact.

The ordinary write of the Delivery Address (Project Site) is refused when it would change the fiscal position
or the mapped taxes (sale.order._sipanel_check_shipping_fiscal_impact). This wizard is the explicit override:

* Sales Manager only (sales_team.group_sale_manager: ACL on this model + server check); a normal Sales user has
  neither the ACL nor the guard token, and a context flag without the token does not bypass the guard;
* draft quotations only, not locked, no invoice, no delivery, and no sealed SIPANEL Scope revision (a sent or
  accepted seal must go through the Scope amendment flow first);
* preview of current vs proposed site, fiscal position, per-line taxes and totals, all computed with the native
  fiscal-position resolution, tax mapping and amount pipeline, without writing anything;
* explicit confirmation; the preview must still match the order when it is applied (stale previews are refused);
* apply = write the address, let Odoo resolve the fiscal position natively, run the native "Update Taxes" action
  (sale.order.action_update_taxes), then verify that the native result equals the preview — otherwise roll back;
* the approval (user, time, old/new site, old/new fiscal position, totals before/after) is posted in the chatter.

No tax rule is coded here: the fiscal treatment is whatever the Finance-approved fiscal positions resolve to.
"""
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard_ctx
from odoo.addons.sipanel_quotation_project_info.models.sale_order import FISCAL_CHANGE_GUARD

APPROVER_GROUP = 'sales_team.group_sale_manager'


class ProjectSiteFiscalChange(models.TransientModel):
    _name = 'sipanel.project.site.fiscal.change'
    _description = 'Change Project Site with fiscal impact'

    order_id = fields.Many2one('sale.order', required=True, readonly=True, ondelete='cascade')
    company_id = fields.Many2one(related='order_id.company_id')
    currency_id = fields.Many2one(related='order_id.currency_id')
    parent_partner_id = fields.Many2one(related='order_id.partner_id.commercial_partner_id')
    current_site_id = fields.Many2one(related='order_id.partner_shipping_id', string='Current Project Site')
    current_fiscal_position_id = fields.Many2one(related='order_id.fiscal_position_id', string='Current Fiscal Position')
    expected_site_id = fields.Many2one('res.partner', readonly=True,
                                       help="Technical: Delivery Address when the preview was opened (stale-preview check).")
    expected_fiscal_position_id = fields.Many2one('account.fiscal.position', readonly=True,
                                                  help="Technical: fiscal position when the preview was opened.")
    proposed_site_id = fields.Many2one(
        'res.partner', string='Proposed Project Site', check_company=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="The delivery / job-site contact to set as Delivery Address.")
    proposed_fiscal_position_id = fields.Many2one(
        'account.fiscal.position', string='Proposed Fiscal Position', compute='_compute_preview',
        help="Resolved by Odoo's own fiscal-position rules for the customer with this delivery address.")
    current_amount_untaxed = fields.Monetary(related='order_id.amount_untaxed', string='Current Untaxed Amount')
    current_amount_tax = fields.Monetary(related='order_id.amount_tax', string='Current Tax')
    current_amount_total = fields.Monetary(related='order_id.amount_total', string='Current Total')
    projected_amount_untaxed = fields.Monetary(compute='_compute_preview', string='Projected Untaxed Amount')
    projected_amount_tax = fields.Monetary(compute='_compute_preview', string='Projected Tax')
    projected_amount_total = fields.Monetary(compute='_compute_preview', string='Projected Total')
    fiscal_impact = fields.Boolean(compute='_compute_preview')
    line_taxes_html = fields.Html(compute='_compute_preview', string='Line taxes', sanitize=True)
    confirm = fields.Boolean(string='I confirm the fiscal position and tax change shown above')

    # ------------------------------------------------------------------ guards
    def _check_approver(self):
        if not self.env.user.has_group(APPROVER_GROUP):
            raise AccessError(self.env._("Only a Sales Manager can apply a Project Site change that changes taxes."))

    @api.model
    def _check_order_editable(self, order):
        """Fail closed outside an editable commercial state."""
        reasons = []
        if order.state != 'draft':
            reasons.append(self.env._("the quotation is not in draft (sent quotations are sealed)"))
        if order.locked:
            reasons.append(self.env._("the order is locked"))
        if order.invoice_ids:
            reasons.append(self.env._("invoices exist"))
        if 'picking_ids' in order._fields and order.picking_ids:
            reasons.append(self.env._("deliveries exist"))
        # read the seal state as the system: an approver without Scope rights must still be refused, never let through
        sealed = order.sudo().sipanel_quote_scope_ids.filtered('active').filtered(
            lambda s: s.accepted_revision_id or (s.current_revision_id and s.current_revision_id.state != 'working'))
        if sealed:
            reasons.append(self.env._("Scope content is sealed (%s); create an amendment revision first",
                                      ', '.join(sealed.mapped('display_name'))))
        if reasons:
            raise UserError(self.env._("Project Site fiscal change refused for %(o)s: %(r)s.",
                                       o=order.display_name, r='; '.join(reasons)))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_approver()
        records = super().create(vals_list)
        for wizard in records:
            self._check_order_editable(wizard.order_id)
            wizard.write({'expected_site_id': wizard.order_id.partner_shipping_id.id,
                          'expected_fiscal_position_id': wizard.order_id.fiscal_position_id.id})
        return records

    # ------------------------------------------------------------------ preview (read-only, native computations)
    @api.depends('order_id', 'proposed_site_id')
    def _compute_preview(self):
        for wizard in self:
            order = wizard.order_id
            if not order or not wizard.proposed_site_id:
                wizard.update({'proposed_fiscal_position_id': False, 'projected_amount_untaxed': 0.0,
                               'projected_amount_tax': 0.0, 'projected_amount_total': 0.0,
                               'fiscal_impact': False, 'line_taxes_html': False})
                continue
            proposed = order._sipanel_resolve_fiscal_position(wizard.proposed_site_id)
            current_taxes = order._sipanel_line_taxes_under(order.fiscal_position_id)
            proposed_taxes = order._sipanel_line_taxes_under(proposed)
            untaxed, tax, total = order._sipanel_amounts_with_taxes(proposed_taxes)
            wizard.update({
                'proposed_fiscal_position_id': proposed,
                'projected_amount_untaxed': untaxed, 'projected_amount_tax': tax, 'projected_amount_total': total,
                'fiscal_impact': (order._sipanel_fiscal_state(order.fiscal_position_id)
                                  != order._sipanel_fiscal_state(proposed)),
                'line_taxes_html': wizard._render_line_taxes(order, current_taxes, proposed_taxes),
            })

    def _render_line_taxes(self, order, current_taxes, proposed_taxes):
        def names(taxes):
            return ', '.join(taxes.mapped('name')) or '-'
        rows = Markup('').join(
            Markup('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>') % (
                line.product_id.display_name or line.name, names(line.tax_ids),
                names(current_taxes.get(line)), names(proposed_taxes.get(line)))
            for line in order._get_priced_lines())
        head = Markup('<tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>') % (
            self.env._("Line"), self.env._("Taxes on the line now"), self.env._("Current position maps"),
            self.env._("Proposed position maps"))
        return Markup('<table class="table table-sm o_sipanel_fiscal_preview"><thead>%s</thead><tbody>%s</tbody></table>') % (head, rows)

    # ------------------------------------------------------------------ apply
    def action_apply(self):
        self.ensure_one()
        self._check_approver()
        order = self.order_id
        self._check_order_editable(order)
        if not self.proposed_site_id:
            raise UserError(self.env._("Select the proposed Project Site."))
        if not self.confirm:
            raise UserError(self.env._("Tick the confirmation after reviewing the fiscal position and tax change."))
        if order.partner_shipping_id != self.expected_site_id or order.fiscal_position_id != self.expected_fiscal_position_id:
            raise UserError(self.env._("The quotation changed after this preview was opened; open the change again."))
        preview = {
            'fiscal_position': self.proposed_fiscal_position_id,
            'amounts': (self.projected_amount_untaxed, self.projected_amount_tax, self.projected_amount_total),
            'state': order._sipanel_fiscal_state(self.proposed_fiscal_position_id),
        }
        before = {
            'site': order.partner_shipping_id, 'fiscal_position': order.fiscal_position_id,
            'amounts': (order.amount_untaxed, order.amount_tax, order.amount_total),
        }
        # 1-2. set the site; the stored compute resolves the fiscal position natively (no fiscal_position_id in vals)
        order.with_context(**guard_ctx(FISCAL_CHANGE_GUARD)).write({'partner_shipping_id': self.proposed_site_id.id})
        # 3-4. native "Update Taxes": order_line._compute_tax_ids() + chatter note; totals recompute natively
        order.action_update_taxes()
        order.flush_recordset()
        order.invalidate_recordset()
        after_state = order._sipanel_fiscal_state(order.fiscal_position_id)
        actual_taxes = {line.id: tuple(sorted(line.tax_ids.ids)) for line in order._get_priced_lines()}
        after_amounts = (order.amount_untaxed, order.amount_tax, order.amount_total)
        currency = order.currency_id
        if (order.fiscal_position_id != preview['fiscal_position'] or after_state != preview['state']
                or actual_taxes != preview['state'][1]
                or any(currency.compare_amounts(a, b) for a, b in zip(after_amounts, preview['amounts']))):
            # raising rolls the whole transaction back: nothing of the change is kept
            raise UserError(self.env._("The native result differs from the preview; nothing was changed. "
                                       "Review the fiscal position configuration with Finance."))
        # 5. audit trail in the order chatter (author = approving user, date = approval time)
        fmt = lambda v: escape(currency.format(v))  # noqa: E731
        order.message_post(body=Markup(
            '<p><b>%s</b></p><ul>'
            '<li>%s: %s</li><li>%s: %s</li>'
            '<li>%s: %s → %s</li><li>%s: %s → %s</li>'
            '<li>%s: %s / %s / %s → %s / %s / %s</li></ul>') % (
            self.env._("Project Site change with fiscal impact approved"),
            self.env._("Approved by"), self.env.user.display_name,
            self.env._("Approved on"), fields.Datetime.to_string(fields.Datetime.now()) + ' UTC',
            self.env._("Project Site"), before['site'].display_name or '-', order.partner_shipping_id.display_name,
            self.env._("Fiscal Position"), before['fiscal_position'].display_name or '-', order.fiscal_position_id.display_name or '-',
            self.env._("Untaxed / Tax / Total"), *map(fmt, before['amounts']), *map(fmt, after_amounts)))
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': order.id,
                'view_mode': 'form', 'target': 'current'}
