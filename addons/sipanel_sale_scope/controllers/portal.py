# -*- coding: utf-8 -*-
"""Governed portal quantity transition (GAP-C02, GAP-S04; SV-03, AM-01-R2)."""
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request, route

from odoo.addons.sale_management.controllers import portal as sale_management_portal


class CustomerPortal(sale_management_portal.CustomerPortal):

    @route(['/my/orders/<int:order_id>/update_line_dict'], type='jsonrpc', auth="public", website=True)
    def portal_quote_option_update(self, order_id, line_id, access_token=None, remove=False, input_quantity=False, **kwargs):
        try:
            order_sudo = self._document_check_access('sale.order', order_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        line = request.env['sale.order.line'].sudo().browse(int(line_id)).exists()
        if not line or line.order_id != order_sudo or not line.sipanel_quote_scope_id:
            return super().portal_quote_option_update(order_id, line_id, access_token=access_token, remove=remove,
                                                      input_quantity=input_quantity, **kwargs)
        if not order_sudo._can_be_edited_on_portal() or not line._can_be_edited_on_portal():
            return {'error': 'not_editable'}
        scope = line.sipanel_quote_scope_id
        if input_quantity is not False:
            new_state = 'accepted' if float(input_quantity or 0) > 0 else 'declined'
        else:
            new_state = 'declined' if remove else 'accepted'
        try:
            scope.sudo()._transition_acceptance(
                new_state, actor='portal', revision_id=kwargs.get('sipanel_revision_id'),
                seal_hash=kwargs.get('sipanel_seal_hash'))
        except UserError:
            # generic message: never reveal whether a newer revision exists
            return {'error': 'stale_link'}
        return {'ok': True, 'acceptance_state': scope.acceptance_state}
