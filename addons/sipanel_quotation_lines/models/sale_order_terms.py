# -*- coding: utf-8 -*-
"""Commercial terms of the customer quotation (requirements 2026-10-08, items 2-5).

- Payment terms: the native payment_term_id, no default added here (Odoo's own partner default stays).
- Delivery time: working days after receipt of the down payment, no default.
- Bank account: an optional line with one of the company's own native bank accounts (res.partner.bank).
- Validity: the native validity_date / is_expired and the native default quotation validity setting.

A quotation (draft / sent) that misses one of them, or whose validity has passed, cannot be printed, sent by
email, marked as sent or opened in the customer preview / portal. Nothing is filled in or moved silently: the
user gets one Persian message listing everything to complete. Confirmed orders are not gated (their printout
is the order, not an offer).
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .sale_order import OPEN_STATES

# The customer quotation reports (print, email attachment, portal download, seal artifact all render these).
QUOTATION_REPORTS = ('sale.report_saleorder', 'sale.report_saleorder_pro_forma')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sipanel_delivery_days = fields.Integer(
        string='زمان تحویل (روز کاری پس از دریافت پیش‌پرداخت)', copy=True, tracking=True,
        help="Printed as «زمان تحویل: <n> روز کاری پس از دریافت پیش‌پرداخت». Required before the quotation is "
             "printed or sent.")
    sipanel_show_bank_account = fields.Boolean(
        string='نمایش شماره حساب در پیش‌فاکتور', default=False, tracking=True,
        help="Print the company bank account for the down payment in the terms of the quotation.")
    sipanel_company_partner_id = fields.Many2one(related='company_id.partner_id', string='Company contact')
    sipanel_bank_account_id = fields.Many2one(
        'res.partner.bank', string='شماره حساب شرکت', tracking=True, ondelete='restrict',
        domain="[('partner_id', '=', sipanel_company_partner_id)]",
        help="One of the company's own bank accounts; required only when the bank account is printed.")

    @api.constrains('sipanel_delivery_days')
    def _check_sipanel_delivery_days(self):
        if any(order.sipanel_delivery_days < 0 for order in self):
            raise ValidationError("زمان تحویل نمی‌تواند منفی باشد.")

    @api.constrains('sipanel_bank_account_id', 'company_id')
    def _check_sipanel_bank_account_company(self):
        for order in self:
            account = order.sipanel_bank_account_id
            if account and account.partner_id != order.company_id.partner_id:
                raise ValidationError(
                    f"شماره حساب «{account.display_name}» متعلق به شرکت «{order.company_id.name}» نیست.")

    # ------------------------------------------------------------------ gate
    def _sipanel_customer_document_problems(self):
        """Persian list of what blocks printing / sending this quotation (empty = printable)."""
        self.ensure_one()
        if self.state not in OPEN_STATES:
            return []
        problems = []
        if not self.payment_term_id:
            problems.append("«شرایط پرداخت» انتخاب نشده است.")
        if self.sipanel_delivery_days <= 0:
            problems.append("«زمان تحویل (روز کاری پس از دریافت پیش‌پرداخت)» وارد نشده است.")
        if self.sipanel_show_bank_account and not self.sipanel_bank_account_id:
            problems.append("«نمایش شماره حساب در پیش‌فاکتور» فعال است اما شماره حساب شرکت انتخاب نشده است.")
        if self.is_expired:
            date = self.validity_date_shamsi or fields.Date.to_string(self.validity_date)
            problems.append(f"اعتبار این پیش‌فاکتور در تاریخ {date} به پایان رسیده است. لطفاً تاریخ پیش‌فاکتور و "
                            "تاریخ اعتبار را به‌روز کنید.")
        return problems

    def _sipanel_check_customer_document(self):
        messages = []
        for order in self:
            problems = order._sipanel_customer_document_problems()
            if problems:
                messages.append(f"پیش‌فاکتور {order.name} قابل چاپ یا ارسال نیست:\n"
                                + "\n".join(f"- {p}" for p in problems))
        if messages:
            raise UserError("\n\n".join(messages))

    def action_quotation_send(self):
        self._sipanel_check_customer_document()
        return super().action_quotation_send()

    def action_quotation_sent(self):
        self._sipanel_check_customer_document()
        return super().action_quotation_sent()

    def action_preview_sale_order(self):
        self._sipanel_check_customer_document()
        return super().action_preview_sale_order()


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """Print, email attachment and portal download of a quotation all go through here."""
        if res_ids:
            report = self._get_report(report_ref)
            if report.model == 'sale.order' and report.report_name in QUOTATION_REPORTS:
                ids = [res_ids] if isinstance(res_ids, int) else res_ids
                self.env['sale.order'].browse(ids).sudo()._sipanel_check_customer_document()
        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
