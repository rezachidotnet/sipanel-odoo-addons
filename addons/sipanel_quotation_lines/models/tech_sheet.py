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
- A row may be linked to a product attribute (top-sheet material): it then prints the technical sheet text of the
  value chosen on the quotation lines (product_attribute.py), the row's own description only as a fallback. The
  text is copied into the quotation row when the quotation leaves the draft state (sent / confirmed), so a later
  change of the value's text never changes a sent quotation.
- A quotation with a sheet prints it on its own page between Page 1 and the price table
  (report/sale_report_templates.xml); a quotation without one keeps the earlier layout.
- The System name printed on Page 1 and in the sheet title is captured with every stored translation when the System
  is set, and printed in the document language (owner 2026-10-14: "Standing Seam" in English, «استندینگ سیم» in
  Persian); quotations captured before keep the single-language Page 1 snapshot.
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
    attribute_id = fields.Many2one(
        'product.attribute', string='Option attribute', ondelete='restrict',
        help="The row prints the technical sheet text of the value of this attribute chosen on the quotation lines "
             "(e.g. top-sheet material); the description is the fallback.")


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
    attribute_value_id = fields.Many2one(
        'product.attribute.value', string='Frozen option value', readonly=True, ondelete='restrict',
        help="Set when the quotation left the draft state: the option value whose text was copied into the description.")

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
    sipanel_system_print_name = fields.Char(
        string='Requested System (printed, per language)', translate=True, readonly=True, copy=True,
        help="Name of the Requested System with every stored translation, captured when the System was set.")
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
        if vals.get('state') and vals['state'] != 'draft' and not guard(self.env, SHEET_GUARD):
            # leaving the draft state (sent, confirmed, cancelled): the option rows keep the text printed now
            self.filtered(lambda o: o.state == 'draft')._sipanel_freeze_option_rows()
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
                    'attribute_id': src.attribute_id.id,
                    'title': titles.get('en_US') or src.with_context(lang='en_US').title,
                    'description': descriptions.get('en_US') or False})
                # the other languages exactly as stored on the System (en_US source passed along: Odoo 19 rebuilds
                # the source from a lone non-en_US key)
                for fname, stored in (('title', titles), ('description', descriptions)):
                    others = {lang: value for lang, value in stored.items() if lang != 'en_US' and lang in active}
                    if others and stored.get('en_US'):
                        row.sudo().update_field_translations(fname, dict(others, en_US=stored['en_US']))

    # ------------------------------------------------------------------ options (top-sheet material)
    def _sipanel_selected_values(self, attribute):
        """product.attribute.value(s) of `attribute` chosen on the quotation lines. A line whose product has the
        attribute but no chosen value counts with the product's first value (the default). No line with the
        attribute: the attribute's first value."""
        self.ensure_one()
        values = self.env['product.attribute.value']
        for line in self.order_line.filtered(lambda l: l.product_id and not l.display_type):
            ptal = line.product_id.product_tmpl_id.valid_product_template_attribute_line_ids.filtered(
                lambda l: l.attribute_id == attribute)
            if not ptal:
                continue
            chosen = line.product_no_variant_attribute_value_ids.filtered(lambda v: v.attribute_id == attribute)
            values |= (chosen or ptal.product_template_value_ids.filtered('ptav_active')[:1]).product_attribute_value_id
        return values or attribute.value_ids.sorted(lambda v: (v.sequence, v.id))[:1]

    def _sipanel_freeze_option_rows(self):
        Row = self.env['sipanel.quotation.spec.line']
        active = {code for code, _name in self.env['res.lang'].get_installed()}
        for order in self:
            for row in order.sipanel_tech_spec_ids.filtered(lambda r: r.attribute_id and not r.attribute_value_id):
                value = order._sipanel_selected_values(row.attribute_id)[:1]
                texts = {lang: t for lang, t in stored_translations(value.sudo(), 'sipanel_spec_text').items()
                         if lang in active} if value else {}
                vals = {'attribute_value_id': value.id}
                if texts.get('en_US'):
                    vals['description'] = texts['en_US']
                row = row.with_context(**guard_ctx(SHEET_GUARD))
                row.with_context(lang='en_US').write(vals)
                others = {lang: t for lang, t in texts.items() if lang != 'en_US'}
                if others and texts.get('en_US'):
                    row.sudo().update_field_translations('description', dict(others, en_US=texts['en_US']))

    def _sipanel_option_problems(self):
        """Persian problems that block printing / sending (sale_order_terms.py gate): an option value whose price is
        required but still 0, options of one sheet row chosen differently on different lines, an option changed
        after the sheet was frozen."""
        self.ensure_one()
        problems = []
        for line in self.order_line.filtered(lambda l: l.product_id and not l.display_type):
            for ptav in line.product_no_variant_attribute_value_ids:
                if ptav.product_attribute_value_id.sipanel_price_required and line.currency_id.is_zero(ptav.price_extra):
                    msg = f"قیمت گزینه‌ی {ptav.product_attribute_value_id.with_context(lang='fa_IR').name} تعیین نشده است"
                    if msg not in problems:
                        problems.append(msg)
        for row in self.sipanel_tech_spec_ids.filtered('attribute_id'):
            selected = self._sipanel_selected_values(row.attribute_id)
            name = row.attribute_id.with_context(lang='fa_IR').name
            if len(selected) > 1:
                problems.append(f"«{name}» در سطرهای این پیش‌فاکتور یکسان نیست؛ همه‌ی سطرها باید یک گزینه داشته باشند.")
            elif row.attribute_value_id and selected != row.attribute_value_id:
                problems.append(f"«{name}» پس از ارسال پیش‌فاکتور تغییر کرده است و با مشخصات فنی ارسال‌شده یکسان نیست.")
        return problems

    def _sipanel_customer_document_problems(self):
        problems = super()._sipanel_customer_document_problems()
        if self.state in ('draft', 'sent'):
            problems += self._sipanel_option_problems()
        return problems

    # ------------------------------------------------------------------ System name per language
    def _sipanel_refresh_system_snapshot(self):
        res = super()._sipanel_refresh_system_snapshot()
        self._sipanel_capture_system_print_name()
        return res

    def _sipanel_capture_system_print_name(self):
        active = {code for code, _name in self.env['res.lang'].get_installed()}
        for order in self:
            system = order.sipanel_requested_system_id.sudo()
            names = {lang: n for lang, n in stored_translations(system, 'name').items() if lang in active} if system else {}
            order = order.with_context(**guard_ctx(SHEET_GUARD))
            order.with_context(lang='en_US').sipanel_system_print_name = names.get('en_US') or False
            others = {lang: n for lang, n in names.items() if lang != 'en_US'}
            if others and names.get('en_US'):
                order.update_field_translations('sipanel_system_print_name', dict(others, en_US=names['en_US']))

    def _sipanel_system_print_label(self):
        """System name for Page 1 and the sheet title, in the document language."""
        self.ensure_one()
        return self.sipanel_system_print_name or self.sipanel_requested_system_name_snapshot or ''

    # ------------------------------------------------------------------ report
    def _sipanel_tech_sheet_heading(self):
        """Page title in the document language, with the printed System name (the Page 1 snapshot)."""
        self.ensure_one()
        name = self._sipanel_system_print_label()
        if not name:
            return self.env._("Technical Specification")
        return self.env._("Technical Specification of the %s System", name)

    def _sipanel_tech_sheet_rows(self):
        """Rows as printed, in the document language (the report renders the order in the customer language):
        [(number, title, description)], the liner thickness put in where a description asks for it."""
        self.ensure_one()
        lang = self.env.lang or 'en_US'
        thickness = lang_digits(self.sipanel_liner_thickness or '', lang)
        rows = []
        for row in self.sipanel_tech_spec_ids.sorted(lambda r: (r.sequence, r.number, r.id)):
            text = row.description or ''
            if row.attribute_id and not row.attribute_value_id:
                value = self._sipanel_selected_values(row.attribute_id)[:1]
                text = value.sudo().with_context(lang=lang).sipanel_spec_text or text
            rows.append((lang_digits(row.number, lang), row.title or '', text.replace(THICKNESS_TOKEN, thickness)))
        return rows
