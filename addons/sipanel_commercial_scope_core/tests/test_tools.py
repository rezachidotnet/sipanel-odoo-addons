# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

from ..models.sipanel_tools import find_cycle, preset_from_axes, round_to_increment, sha256_of


@tagged('post_install', '-at_install', 'sipanel')
class TestTools(TransactionCase):

    def test_rounding(self):
        self.assertEqual(round_to_increment(17.2, 1, 'up'), 18)
        self.assertEqual(round_to_increment(17.2, 1, 'down'), 17)
        self.assertEqual(round_to_increment(17.5, 1, 'nearest'), 18)
        self.assertEqual(round_to_increment(17.2, 0, 'up'), 17.2)
        self.assertEqual(round_to_increment(17.2, 5, 'up'), 20)
        self.assertEqual(round_to_increment(17.2, 1, 'none'), 17.2)

    def test_presets(self):
        self.assertEqual(preset_from_axes('sipanel', 'included_parent', 'base', 'firm', 'customer_eligible'), 'included')
        self.assertEqual(preset_from_axes('sipanel', 'own_line', 'base', 'firm', 'customer_eligible'), 'separately_billable')
        self.assertEqual(preset_from_axes('sipanel', 'own_line', 'offered', 'firm', 'customer_eligible'), 'optional')
        self.assertEqual(preset_from_axes('sipanel', 'own_line', 'offered', 'provisional', 'customer_eligible'), 'provisional')
        self.assertEqual(preset_from_axes('customer', 'included_parent', 'base', 'firm', 'customer_eligible'), 'customer_scope')
        self.assertEqual(preset_from_axes('sipanel', 'included_parent', 'base', 'firm', 'internal_only'), 'internal_only')
        self.assertEqual(preset_from_axes('sipanel', 'no_customer_line', 'base', 'firm', 'customer_eligible'), 'custom')

    def test_cycle(self):
        self.assertFalse(find_cycle({1: {2}, 2: set()}))
        self.assertTrue(find_cycle({1: {2}, 2: {1}}))
        self.assertTrue(find_cycle({1: {1}}))

    def test_hash_deterministic(self):
        self.assertEqual(sha256_of({'b': 1, 'a': [1, 2]}), sha256_of({'a': [1, 2], 'b': 1}))
