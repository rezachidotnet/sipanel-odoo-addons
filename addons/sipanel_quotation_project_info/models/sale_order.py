# -*- coding: utf-8 -*-
"""Quotation Page 1 project information.

Project Name and Requested System are customer-document SNAPSHOTS: they are filled once from the
Opportunity (on creation, or when an Opportunity is assigned later) and only while they are empty.
There is deliberately no @api.depends on opportunity_id.name / opportunity_id.sipanel_requested_system_id:
renaming the Opportunity, changing its Requested System or renaming the System master never rewrites
an existing quotation. The PDF prints sipanel_requested_system_name_snapshot, never the live name.

Project Site is the native Delivery Address (partner_shipping_id), printed only when it is a genuinely
distinct site. Because the Delivery Address drives fiscal-position resolution, changing it on an existing
order is refused when it would change the fiscal position or the applicable taxes.

Existing quotations are never backfilled (no hook, no migration).

A legitimate Project Site change that does move the fiscal treatment goes through the Sales-Manager wizard
sipanel.project.site.fiscal.change, which previews the native result, applies it with the native
"Update Taxes" action and records the approval in the chatter. Only that wizard holds the guard token.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard

FISCAL_BLOCK_CODE = 'PROJECT_SITE_CHANGE_BLOCKED_BY_FISCAL_POSITION_IMPACT'
FISCAL_CHANGE_GUARD = 'sipanel_project_site_fiscal_change'


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sipanel_project_name = fields.Char(
        string='Project Name', tracking=True,
        help="Printed on the quotation cover. Copied once from the Opportunity name while empty; "
             "later Opportunity renames do not change it.")
    sipanel_system_plan_id = fields.Many2one(
        'account.analytic.plan', compute='_compute_sipanel_system_plan_id',
        help="Technical: the resolved SIPANEL System plan, used by the Requested System domain.")
    sipanel_requested_system_id = fields.Many2one(
        'account.analytic.account', string='Requested System',
        index='btree_not_null', ondelete='restrict', tracking=True, check_company=True,
        domain="[('plan_id', '=', sipanel_system_plan_id), ('company_id', 'in', [company_id, False])]",
        help="The technical system the customer initially asked for. Copied once from the Opportunity; "
             "the quotation prints the name captured when it was set.")
    sipanel_requested_system_name_snapshot = fields.Char(
        string='Requested System (as printed)', readonly=True,
        help="Name of the Requested System captured in the quotation language when the System was set. "
             "Renaming the System master later does not change it.")

    def _compute_sipanel_system_plan_id(self):
        plan = self.env['sipanel.config'].system_plan_or_empty()
        for order in self:
            order.sipanel_system_plan_id = plan

    @api.constrains('sipanel_requested_system_id')
    def _check_sipanel_requested_system(self):
        self.env['sipanel.config'].check_requested_system(self)

    # ------------------------------------------------------------------ snapshots
    @api.onchange('opportunity_id')
    def _onchange_sipanel_opportunity_project_info(self):
        """Form preview of the one-time initialisation done by create()/write()."""
        opportunity = self.opportunity_id
        if not opportunity:
            return
        if not self.sipanel_project_name:
            self.sipanel_project_name = opportunity.name
        if not self.sipanel_requested_system_id and not self.sipanel_requested_system_name_snapshot:
            self.sipanel_requested_system_id = opportunity.sipanel_requested_system_id

    def _sipanel_system_print_name(self):
        """The System name as the customer reads it: plain name (no analytic code, no partner suffix)
        in the quotation language."""
        self.ensure_one()
        system = self.sipanel_requested_system_id
        if not system:
            return False
        return system.sudo().with_context(lang=self.partner_id.lang or self.env.lang).name

    def _sipanel_refresh_system_snapshot(self):
        for order in self:
            order.write({'sipanel_requested_system_name_snapshot': order._sipanel_system_print_name()})

    def _sipanel_init_from_opportunity(self):
        """Fill the empty snapshots of each order from its Opportunity, once. Never overwrites."""
        for order in self.filtered('opportunity_id'):
            opportunity = order.opportunity_id
            vals = {}
            if not order.sipanel_project_name and opportunity.name:
                vals['sipanel_project_name'] = opportunity.name
            if (not order.sipanel_requested_system_id and not order.sipanel_requested_system_name_snapshot
                    and opportunity.sipanel_requested_system_id):
                vals['sipanel_requested_system_id'] = opportunity.sipanel_requested_system_id.id
            if vals:
                order.write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._sipanel_init_from_opportunity()
        orders.filtered(
            lambda o: o.sipanel_requested_system_id and not o.sipanel_requested_system_name_snapshot
        )._sipanel_refresh_system_snapshot()
        return orders

    def write(self, vals):
        if 'partner_shipping_id' in vals:
            self._sipanel_check_shipping_fiscal_impact(vals)
        # an explicit Requested System change re-captures its printed name, unless the caller sets it too
        refresh_snapshot = 'sipanel_requested_system_id' in vals and 'sipanel_requested_system_name_snapshot' not in vals
        res = super().write(vals)
        if refresh_snapshot:
            self._sipanel_refresh_system_snapshot()
        if vals.get('opportunity_id'):
            self._sipanel_init_from_opportunity()
        return res

    # ------------------------------------------------------------------ fiscal-position guard
    def _sipanel_line_taxes_under(self, fiscal_position):
        """{line: taxes} each priced line would carry under ``fiscal_position``: the computation of the native
        sale.order.line._compute_tax_ids (company-filtered product taxes mapped by the position). Read-only."""
        self.ensure_one()
        Tax = self.env['account.tax']
        result = {}
        for line in self._get_priced_lines():
            taxes = line.product_id.taxes_id._filter_taxes_by_company(line.company_id) if line.product_id else Tax
            if line.product_type == 'combo' or not taxes:
                result[line] = Tax
            else:
                result[line] = fiscal_position.with_company(line.company_id).map_tax(taxes)
        return result

    def _sipanel_amounts_with_taxes(self, line_taxes):
        """(untaxed, tax, total) of the order if its lines carried ``line_taxes``: the native _compute_amounts
        pipeline with the tax_ids override supported by _prepare_base_line_for_taxes_computation. Read-only."""
        self.ensure_one()
        AccountTax = self.env['account.tax']
        base_lines = [line._prepare_base_line_for_taxes_computation(tax_ids=line_taxes.get(line, line.tax_ids))
                      for line in self._get_priced_lines()]
        base_lines += self._add_base_lines_for_early_payment_discount()
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        totals = AccountTax._get_tax_totals_summary(
            base_lines=base_lines, currency=self.currency_id or self.company_id.currency_id, company=self.company_id)
        return totals['base_amount_currency'], totals['tax_amount_currency'], totals['total_amount_currency']

    def _sipanel_fiscal_state(self, fiscal_position):
        """Fiscal position + the sale taxes it maps for every priced line (the 'applicable taxes')."""
        self.ensure_one()
        taxes = self._sipanel_line_taxes_under(fiscal_position)
        return fiscal_position.id, {line.id: tuple(sorted(t.ids)) for line, t in taxes.items()}

    def _sipanel_resolve_fiscal_position(self, shipping):
        """Native resolution of the fiscal position for this order's customer with ``shipping`` as delivery."""
        self.ensure_one()
        return self.env['account.fiscal.position'].with_company(self.company_id)._get_fiscal_position(
            self.partner_id, shipping)

    def _sipanel_check_shipping_fiscal_impact(self, vals):
        """Refuse a Delivery Address (Project Site) change on an existing order when it would change the
        fiscal position or the applicable taxes. A change of customer re-derives every address natively
        and is not a Project Site entry, so it is left to the native flow."""
        if guard(self.env, FISCAL_CHANGE_GUARD):
            return  # the approved Project Site fiscal change wizard (it verifies the native result itself)
        shipping = self.env['res.partner'].browse(vals.get('partner_shipping_id') or [])
        for order in self:
            if order.partner_shipping_id == shipping or not order.partner_id:
                continue
            if vals.get('partner_id') and vals['partner_id'] != order.partner_id.id:
                continue
            company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else order.company_id
            FiscalPosition = self.env['account.fiscal.position'].with_company(company)
            current = order.fiscal_position_id
            proposed = FiscalPosition._get_fiscal_position(order.partner_id, shipping)
            if 'fiscal_position_id' in vals:
                requested = FiscalPosition.browse(vals['fiscal_position_id'] or [])
                if requested != current:
                    proposed = requested
            if order._sipanel_fiscal_state(current) != order._sipanel_fiscal_state(proposed):
                raise UserError(self.env._(
                    "%(code)s: changing the Delivery Address (Project Site) of %(order)s to \"%(site)s\" would "
                    "change its fiscal position from \"%(before)s\" to \"%(after)s\" and with it the sale taxes. "
                    "Project Site entry must not change taxes; the address was not saved. A Sales Manager can apply "
                    "it with \"Change Project Site (fiscal impact)\" after reviewing the new taxes.",
                    code=FISCAL_BLOCK_CODE, order=order.display_name, site=shipping.display_name or '-',
                    before=current.display_name or '-', after=proposed.display_name or '-'))

    def action_sipanel_project_site_fiscal_change(self):
        """Open the controlled Project Site change (Sales Manager only, draft quotations only)."""
        self.ensure_one()
        wizard = self.env['sipanel.project.site.fiscal.change'].create({'order_id': self.id})
        return {
            'type': 'ir.actions.act_window', 'res_model': wizard._name, 'res_id': wizard.id,
            'view_mode': 'form', 'target': 'new', 'name': self.env._("Change Project Site (fiscal impact)"),
        }

    # ------------------------------------------------------------------ Page 1 presentation
    def _sipanel_page1_parties(self):
        """(customer, contact person). The contact is printed only when the partner is an individual
        contact of a real company; the company is never invented."""
        self.ensure_one()
        partner = self.partner_id
        commercial = partner.commercial_partner_id
        if commercial and commercial != partner and commercial.is_company and partner.type == 'contact':
            return commercial, partner
        if commercial and commercial != partner and commercial.is_company:
            # an invoice/delivery/other address of the company is not a contact person
            return commercial, self.env['res.partner']
        return partner, self.env['res.partner']

    def _sipanel_page1_project_site(self):
        """The Delivery Address when it is a genuinely distinct project / delivery location, else empty.
        Odoo defaults the Delivery Address to the customer itself: that is not a Project Site, nor is a
        person of the same customer."""
        self.ensure_one()
        site = self.partner_shipping_id
        partner = self.partner_id
        if not site or site in (partner | partner.commercial_partner_id):
            return self.env['res.partner']
        if site.commercial_partner_id == partner.commercial_partner_id and site.type not in ('delivery', 'other'):
            return self.env['res.partner']
        return site
