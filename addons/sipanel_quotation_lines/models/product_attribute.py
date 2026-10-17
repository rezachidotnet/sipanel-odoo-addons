# -*- coding: utf-8 -*-
"""Quotation options as native product attributes (owner requirements 2026-10-14, top-sheet material).

The option is a native product attribute with create_variant = never (no_variant): the chosen value is stored on
the quotation line (product_no_variant_attribute_value_ids) and its price_extra is native (per product template).
No new products, no variants. Two additions:

- product.attribute.value: the text the technical sheet prints for this value (translated), and a flag "price extra
  required": a quotation carrying such a value with a price extra of 0 cannot be printed or sent (the price of the
  option is not decided yet).
- sale.order.line: Odoo 19 recomputes the price and the description of a line only when its PRODUCT changes, so a
  value changed later on an existing line (or on a line with a typed price) would keep the old price extra and the
  old "attribute: value" text. While the order is a quotation, a change of the values moves the unit price by the
  difference of the price extras (a typed price stays typed: base price + extra) and replaces the native
  "attribute: value" lines of the description.
"""
from odoo import fields, models

from .sale_order import OPEN_STATES

EXTRA_VALUES = 'product_no_variant_attribute_value_ids'


class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'

    sipanel_spec_text = fields.Text(
        string='Technical sheet text', translate=True,
        help="Printed in the quotation's technical sheet, in the row linked to this attribute, when this value is "
             "the one chosen on the quotation.")
    sipanel_price_required = fields.Boolean(
        string='Price extra required to print',
        help="A quotation carrying this value with a price extra of 0 cannot be printed or sent: the price of the "
             "option is not decided yet.")


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _sipanel_option_extra(self, ptavs):
        """Price extra of the given no_variant values in the line's currency and unit of measure."""
        self.ensure_one()
        product = self.product_id
        extra = product._get_no_variant_attributes_price_extra(ptavs) if ptavs else 0.0
        if not extra:
            return 0.0
        if self.product_uom_id and product.uom_id and self.product_uom_id != product.uom_id:
            extra = product.uom_id._compute_price(extra, self.product_uom_id)
        currency = product.currency_id or self.company_id.currency_id
        if currency and self.currency_id and currency != self.currency_id:
            extra = currency._convert(extra, self.currency_id, self.company_id or self.env.company,
                                      self.order_id.date_order or fields.Date.today())
        return extra

    def write(self, vals):
        if EXTRA_VALUES not in vals:
            return super().write(vals)
        before = {line.id: (line[EXTRA_VALUES], line._sipanel_option_description())
                  for line in self if line.product_id and not line.display_type}
        res = super().write(vals)
        for line in self.filtered(lambda l: l.id in before and l.state in OPEN_STATES):
            old_values, old_text = before[line.id]
            if old_values == line[EXTRA_VALUES]:
                continue
            update = {}
            delta = line._sipanel_option_extra(line[EXTRA_VALUES]) - line._sipanel_option_extra(old_values)
            if not line.currency_id.is_zero(delta) and 'price_unit' not in vals:
                manual = line.currency_id.compare_amounts(line.technical_price_unit, line.price_unit)
                update['price_unit'] = line.price_unit + delta
                if not manual:
                    update['technical_price_unit'] = update['price_unit']
            new_text = line._sipanel_option_description()
            name = line.name or ''
            if 'name' not in vals and old_text != new_text:
                if old_text and old_text in name:
                    name = name.replace(old_text, new_text)
                elif new_text and new_text not in name:
                    name += new_text
                update['name'] = name
            if update:
                line.write(update)
        return res

    def _sipanel_option_description(self):
        """The native "\\n<attribute>: <value>" lines of the no_variant values, in the order language."""
        self.ensure_one()
        lang = self.order_id._get_lang()
        return self.with_context(lang=lang)._get_sale_order_line_multiline_description_variants()
