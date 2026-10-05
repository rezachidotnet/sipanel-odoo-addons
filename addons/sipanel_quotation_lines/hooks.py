# -*- coding: utf-8 -*-
"""v1 master data of the installation line (work order 2026-10-05, B1 + B2), applied once at install.

- B1: the Standing Seam supply products are the installation base.
- B2: SIPANEL System "Standing Seam" -> installation product SIP-000075.

Records are resolved by their stable business keys (internal reference, System name in the
configured SIPANEL System plan), never by database id. Anything missing is logged and skipped: a
database without these records (a test database, another company) installs cleanly and is configured
by hand. Quotations are never touched.
"""
import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

INSTALLATION_BASE_CODES = ('SIP-000074', 'SIP-000076', 'SIP-000077')
SYSTEM_INSTALLATION_PRODUCTS = {'Standing Seam': 'SIP-000075'}


def post_init_hook(env):
    Product = env['product.product'].sudo().with_context(active_test=False)
    for code in INSTALLATION_BASE_CODES:
        products = Product.search([('default_code', '=', code)])
        if len(products.product_tmpl_id) != 1:
            _logger.warning("sipanel_quotation_lines: installation base product %s not found or ambiguous "
                            "(%s templates); not flagged", code, len(products.product_tmpl_id))
            continue
        products.product_tmpl_id.sipanel_installation_base = True
        _logger.info("sipanel_quotation_lines: %s flagged as installation base", code)
    try:
        plan = env['sipanel.config'].resolve_system_plan()
    except UserError as exc:
        _logger.warning("sipanel_quotation_lines: SIPANEL System plan unresolved (%s); no installation "
                        "product mapped", exc)
        return
    Account = env['account.analytic.account'].sudo().with_context(active_test=False, lang='en_US')
    for system_name, code in SYSTEM_INSTALLATION_PRODUCTS.items():
        systems = Account.search([('plan_id', '=', plan.id), ('name', '=', system_name), ('active', '=', True)])
        product = Product.search([('default_code', '=', code), ('active', '=', True)])
        if len(systems) != 1 or len(product) != 1:
            _logger.warning("sipanel_quotation_lines: System %r (%s found) or product %s (%s found) not "
                            "unique; installation product not mapped", system_name, len(systems), code, len(product))
            continue
        if not systems.sipanel_installation_product_id:
            systems.sipanel_installation_product_id = product
            _logger.info("sipanel_quotation_lines: System %r -> installation product %s", system_name, code)
