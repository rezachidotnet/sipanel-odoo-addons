# -*- coding: utf-8 -*-
"""PT-05 (percent validity), PT-03 (dimensional families), GAP-A07/A08."""
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import SipanelCoreCase


@tagged('post_install', '-at_install', 'sipanel')
class TestRecipeValidation(SipanelCoreCase):

    def test_percent_rules(self):
        scope, v1 = self._make_master(release=False)
        L = self.env['sipanel.scope.recipe.line']
        base = dict(version_id=v1.id, product_id=self.p_screw.id, uom_id=self.uom_unit.id, dimension_family='count',
                    activity_id=self.act_ins.id, execution_mode='stock_issue')
        # self reference
        line = L.create(dict(base, basis='percent_of_quantity', percent=5, base_line_ids=[(6, 0, [self.l_screw.id])]))
        with self.assertRaises(ValidationError):
            line.write({'base_line_ids': [(6, 0, [line.id])]})
        # percent on percent
        with self.assertRaises(ValidationError):
            L.create(dict(base, basis='percent_of_quantity', percent=5, base_line_ids=[(6, 0, [self.l_allow.id])]))
        # mixed unit family bases
        with self.assertRaises(ValidationError):
            L.create(dict(base, basis='percent_of_quantity', percent=5, base_line_ids=[(6, 0, [self.l_screw.id, self.l_gutter.id])]))
        # percent must be > 0
        with self.assertRaises(ValidationError):
            L.create(dict(base, basis='percent_of_quantity', percent=0, base_line_ids=[(6, 0, [self.l_screw.id])]))
        # cross-version base
        scope2, v_other = self._make_master(code='SIPANEL-PT-OTHER', release=False)
        with self.assertRaises(ValidationError):
            L.create(dict(base, basis='percent_of_quantity', percent=5, base_line_ids=[(6, 0, [v_other.recipe_line_ids[0].id])]))
        # percent_of_cost must be derived
        with self.assertRaises(ValidationError):
            L.create(dict(base, basis='percent_of_cost', percent=2, cost_policy='product_cost', base_line_ids=[(6, 0, [self.l_screw.id])]))
        # no_action needs a reason
        with self.assertRaises(ValidationError):
            L.create(dict(base, basis='fixed', fixed_qty=1, execution_mode='no_action'))
        # base line cannot be deleted while referenced
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.l_screw.unlink()

    def test_uom_family_contract(self):
        Family = self.env['sipanel.uom.family']
        self.assertEqual(Family.family_of(self.uom_m), 'length')
        self.assertEqual(Family.family_of(self.uom_cm), 'length')
        self.assertTrue(Family.check_compatible(self.uom_cm, self.uom_m))
        self.assertFalse(Family.check_compatible(self.uom_unit, self.uom_m, raise_if_failure=False))
        with self.assertRaises(ValidationError):
            Family.check_compatible(self.uom_hour, self.uom_m)
        self.assertAlmostEqual(Family.convert(8500, self.uom_cm, self.uom_m), 85.0, places=6)
        # a line tagged with the wrong family is refused
        scope, v1 = self._make_master(release=False)
        with self.assertRaises(ValidationError):
            self.env['sipanel.scope.recipe.line'].create({
                'version_id': v1.id, 'product_id': self.p_gutter.id, 'uom_id': self.uom_m.id, 'dimension_family': 'count',
                'basis': 'fixed', 'fixed_qty': 1, 'activity_id': self.act_ins.id, 'execution_mode': 'stock_issue'})

    def test_release_r7_r10_r11(self):
        scope, v1 = self._make_master(release=False)
        self.l_gutter.write({'rounding_mode': 'up', 'rounding_increment': 0.0})
        self.l_bracket.write({'customer_eligible': True, 'disclosure': 'customer_eligible'})
        issues = v1._release_validations()
        rules = {i['rule'] for i in issues if i['level'] == 'block'}
        self.assertIn('R11', rules)
        self.l_gutter.write({'rounding_increment': 1.0})
        self.assertNotIn('R11', {i['rule'] for i in v1._release_validations() if i['level'] == 'block'})
