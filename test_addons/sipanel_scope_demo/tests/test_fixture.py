# -*- coding: utf-8 -*-
"""C9 vertical pilot smoke on the shipped fixture: add the released master to a synthetic quotation and check the oracle."""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'sipanel', 'sipanel_pilot')
class TestFixture(TransactionCase):

    def test_c9_oracle_from_fixture(self):
        v1 = self.env.ref('sipanel_scope_demo.version_v1')
        self.assertEqual(v1.state, 'released')
        order = self.env['sale.order'].create({'partner_id': self.env.ref('sipanel_scope_demo.partner_customer').id, 'origin': 'SIPANEL-PT-PILOT'})
        scope = self.env['sipanel.quote.scope']._create_from_version(order, v1, 85.0, self.env.ref('uom.product_uom_meter'))
        rev = scope.current_revision_id.sudo()
        self.assertAlmostEqual(rev.direct_cost_total, 10547.0, places=4)
        self.assertAlmostEqual(rev.derived_cost_total, 187.0, places=4)
        self.assertAlmostEqual(rev.eligible_cost_total, 10734.0, places=4)
        scope.anchor_line_id.write({'price_unit': 12000.0 / 85.0, 'tax_ids': [(5, 0, 0)]})
        self.assertAlmostEqual(rev.net_revenue_projection, 12000.0, delta=0.5)  # price_unit rounded to Product Price precision
        self.assertAlmostEqual(rev.margin_amount, 1266.0, delta=0.5)
        self.assertAlmostEqual(rev.margin_percent, 10.55, delta=0.02)
