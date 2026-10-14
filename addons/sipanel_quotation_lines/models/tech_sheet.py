# -*- coding: utf-8 -*-
"""System technical sheet (owner requirements 2026-10-14, items 1-3).

- The SIPANEL System (analytic account of the System plan) carries the sheet: a schematic image and ordered
  specification rows (row number, title, description; title and description translated natively, fa_IR / en_US).
- Each quotation keeps its own SNAPSHOT of the sheet (image + rows): copied from its Requested System when the
  quotation is created or its System changes, editable while the quotation is a draft, frozen as soon as it is
  sent or confirmed. A later change of the System sheet never changes an existing quotation; "Reload technical
  sheet" copies it again on a draft.
- Liner thickness (0.5 / 0.7 mm, default 0.7) is a quotation field; a row description prints it where it contains
  the placeholder {liner_thickness} (Standing Seam row 2), in the digits of the document language.
- A quotation with a sheet prints it on its own page between Page 1 and the price table
  (report/sale_report_templates.xml); a quotation without one keeps the earlier layout.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.sipanel_commercial_scope_core.models.sipanel_tools import guard, guard_ctx, stored_translations

SHEET_GUARD = 'sipanel_tech_sheet_load'
EDITABLE_STATES = ('draft',)
THICKNESS_TOKEN = '{liner_thickness}'
LINER_THICKNESSES = [('0.5', '0.5 mm'), ('0.7', '0.7 mm')]
FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def lang_digits(text, lang):
    return str(text).translate(FA_DIGITS) if (lang or '').startswith('fa') else str(text)


class SipanelSpecLineMixin(models.AbstractModel):
    _name = 'sipanel.spec.line.mixin'
    _description = 'SIPANEL technical specification row'
    _order = 'sequence, number, id'

    sequence = fields.Integer(default=10)
    number = fields.Integer(string='Row', required=True, help="Row number printed in the sheet (and on the schematic).")
    title = fields.Char(string='Title', required=True, translate=True)
    description = fields.Text(
        string='Description', translate=True,
        help="Printed next to the title. {liner_thickness} is replaced by the quotation's liner thickness.")


class SipanelSystemSpecLine(models.Model):
    _name = 'sipanel.system.spec.line'
    _inherit = 'sipanel.spec.line.mixin'
    _description = 'SIPANEL System technical specification row'

    system_id = fields.Many2one('account.analytic.account', string='System', required=True, index=True,
                                ondelete='cascade')

    @api.constrains('system_id')
    def _check_sipanel_system(self):
        self.system_id._check_sipanel_tech_sheet()


class SipanelQuotationSpecLine(models.Model):
    _name = 'sipanel.quotation.spec.line'
    _inherit = 'sipanel.spec.line.mixin'
    _description = 'Quotation technical specification row (snapshot)'

    order_id = fields.Many2one('sale.order', string='Quotation', required=True, index=True, ondelete='cascade')

    def _sipanel_check_editable(self, orders):
        if guard(self.env, SHEET_GUARD):
            return
        frozen = orders.filtered(lambda o: o.state not in EDITABLE_STATES)
        if frozen:
            raise UserError(f"مشخصات فنی پیش‌فاکتور {frozen[0].name} پس از ارسال یا تأیید قابل تغییر نیست.")

    @api.model_create_multi
    def create(self, vals_list):
        self._sipanel_check_editable(self.env['sale.order'].browse({v.get('order_id') for v in vals_list} - {None}))
        return super().create(vals_list)

    def write(self, vals):
        orders = self.order_id
        if 'order_id' in vals:
            orders |= self.env['sale.order'].browse(vals['order_id'])
        self._sipanel_check_editable(orders)
        return super().write(vals)

    def unlink(self):
        self._sipanel_check_editable(self.order_id)
        return super().unlink()


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    sipanel_tech_image = fields.Image(string='Technical sheet schematic', attachment=True)
    sipanel_tech_spec_ids = fields.One2many('sipanel.system.spec.line', 'system_id', string='Technical specification',
                                            copy=True)

    @api.constrains('sipanel_tech_image', 'plan_id')
    def _check_sipanel_tech_sheet(self):
        for account in self.filtered(lambda a: a.sipanel_tech_image or a.sipanel_tech_spec_ids):
            if account.plan_id != self.env['sipanel.config'].system_plan():
                raise ValidationError(self.env._(
                    "A technical sheet can only be set on a SIPANEL System (analytic account of the SIPANEL System "
                    "plan); \"%s\" is not one.", account.display_name))


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sipanel_tech_image = fields.Image(string='Technical sheet schematic', attachment=True, copy=True)
    sipanel_tech_spec_ids = fields.One2many('sipanel.quotation.spec.line', 'order_id', string='Technical specification',
                                            copy=True)
    sipanel_has_tech_sheet = fields.Boolean(compute='_compute_sipanel_has_tech_sheet')
    sipanel_liner_thickness = fields.Selection(
        LINER_THICKNESSES, string='Liner thickness', default='0.7', required=True, tracking=True,
        help="Printed in the technical specification where a row contains {liner_thickness}.")

    @api.depends('sipanel_tech_spec_ids', 'sipanel_tech_image')
    def _compute_sipanel_has_tech_sheet(self):
        for order in self:
            order.sipanel_has_tech_sheet = bool(order.sipanel_tech_spec_ids or order.sipanel_tech_image)

    # ------------------------------------------------------------------ snapshot
    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        given = [bool(v.get('sipanel_tech_spec_ids') or v.get('sipanel_tech_image')) for v in vals_list]
        orders.filtered(lambda o: not given[orders.ids.index(o.id)]
                        and o.sipanel_requested_system_id)._sipanel_load_tech_sheet()
        return orders

    def write(self, vals):
        if not guard(self.env, SHEET_GUARD):
            sheet_fields = {'sipanel_tech_image', 'sipanel_tech_spec_ids', 'sipanel_liner_thickness'} & set(vals)
            frozen = self.filtered(lambda o: o.state not in EDITABLE_STATES)
            if sheet_fields and frozen:
                raise UserError(f"مشخصات فنی پیش‌فاکتور {frozen[0].name} پس از ارسال یا تأیید قابل تغییر نیست.")
            if 'sipanel_requested_system_id' in vals:
                new = self.env['account.analytic.account'].browse(vals['sipanel_requested_system_id'] or [])
                moved = frozen.filtered(lambda o: o.sipanel_requested_system_id != new
                                        and (o.sipanel_has_tech_sheet or new.sudo().sipanel_tech_spec_ids))
                if moved:
                    raise UserError(f"سیستم درخواستی پیش‌فاکتور {moved[0].name} پس از ارسال یا تأیید قابل تغییر نیست؛ "
                                    "مشخصات فنی آن ثابت شده است.")
        changed = self.filtered(lambda o: 'sipanel_requested_system_id' in vals
                                and o.sipanel_requested_system_id.id != (vals['sipanel_requested_system_id'] or False))
        res = super().write(vals)
        if not guard(self.env, SHEET_GUARD) and not {'sipanel_tech_image', 'sipanel_tech_spec_ids'} & set(vals):
            changed.filtered(lambda o: o.state in EDITABLE_STATES)._sipanel_load_tech_sheet()
        return res

    def action_sipanel_load_tech_sheet(self):
        """Button "Reload technical sheet": the System sheet replaces this draft's snapshot (and its edits)."""
        frozen = self.filtered(lambda o: o.state not in EDITABLE_STATES)
        if frozen:
            raise UserError(f"مشخصات فنی پیش‌فاکتور {frozen[0].name} پس از ارسال یا تأیید قابل تغییر نیست.")
        self._sipanel_load_tech_sheet()
        return True

    def _sipanel_load_tech_sheet(self):
        """Copy the Requested System's sheet (image + rows with every stored translation) into the quotation.
        A System without a sheet clears the snapshot: the quotation keeps the layout without a sheet page."""
        Row = self.env['sipanel.quotation.spec.line'].with_context(**guard_ctx(SHEET_GUARD))
        # an archived language (ru_RU) is refused by update_field_translations; it is not printed anyway
        active = {code for code, _name in self.env['res.lang'].get_installed()}
        for order in self:
            system = order.sipanel_requested_system_id.sudo()
            if order.sipanel_tech_spec_ids:
                order.sipanel_tech_spec_ids.with_context(**guard_ctx(SHEET_GUARD)).unlink()
            # written only when it changes: a System without a sheet costs no write on every new quotation
            if (order.sipanel_tech_image or False) != (system.sipanel_tech_image or False):
                order.with_context(**guard_ctx(SHEET_GUARD)).sipanel_tech_image = system.sipanel_tech_image or False
            for src in system.sipanel_tech_spec_ids:
                titles = stored_translations(src, 'title')
                descriptions = stored_translations(src, 'description')
                row = Row.with_context(lang='en_US').create({
                    'order_id': order.id, 'sequence': src.sequence, 'number': src.number,
                    'title': titles.get('en_US') or src.with_context(lang='en_US').title,
                    'description': descriptions.get('en_US') or False})
                # the other languages exactly as stored on the System (en_US source passed along: Odoo 19 rebuilds
                # the source from a lone non-en_US key)
                for fname, stored in (('title', titles), ('description', descriptions)):
                    others = {lang: value for lang, value in stored.items() if lang != 'en_US' and lang in active}
                    if others and stored.get('en_US'):
                        row.sudo().update_field_translations(fname, dict(others, en_US=stored['en_US']))

    # ------------------------------------------------------------------ report
    def _sipanel_tech_sheet_heading(self):
        """Page title in the document language, with the printed System name (the Page 1 snapshot)."""
        self.ensure_one()
        name = self.sipanel_requested_system_name_snapshot
        if not name:
            return self.env._("Technical Specification")
        return self.env._("Technical Specification of the %s System", name)

    def _sipanel_tech_sheet_rows(self):
        """Rows as printed, in the document language (the report renders the order in the customer language):
        [(number, title, description)], the liner thickness put in where a description asks for it."""
        self.ensure_one()
        lang = self.env.lang or 'en_US'
        thickness = lang_digits(self.sipanel_liner_thickness or '', lang)
        return [(lang_digits(row.number, lang), row.title or '',
                 (row.description or '').replace(THICKNESS_TOKEN, thickness))
                for row in self.sipanel_tech_spec_ids.sorted(lambda r: (r.sequence, r.number, r.id))]
