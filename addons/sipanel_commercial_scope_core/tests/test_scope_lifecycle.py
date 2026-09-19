# -*- coding: utf-8 -*-
"""PT-02 (version isolation), PT-24 (immutability via ORM/RPC/import), GAP-A02/A03/A09/A13."""
from unittest.mock import patch

from odoo.exceptions import LockError, UserError, ValidationError
from odoo.tests import tagged

from .common import SipanelCoreCase


@tagged('post_install', '-at_install', 'sipanel')
class TestScopeLifecycle(SipanelCoreCase):

    def test_release_and_supersede(self):
        scope, v1 = self._make_master()
        self.assertEqual(v1.state, 'released')
        self.assertEqual(scope.current_version_id, v1)
        self.assertTrue(v1.release_checksum)
        audit = self.env['sipanel.scope.audit.event'].search([('res_model', '=', 'sipanel.scope.version'), ('res_id', '=', v1.id), ('action', '=', 'release')])
        self.assertEqual(len(audit), 1)
        # new version copies content, release supersedes V1
        v2 = self.env['sipanel.scope.version'].browse(v1.action_new_version()['res_id'])
        self.assertEqual(v2.state, 'draft')
        self.assertEqual(v2.revision, 2)
        self.assertEqual(len(v2.recipe_line_ids), 8)
        self.assertEqual(v2.parent_version_id, v1)
        allowance = v2.recipe_line_ids.filtered(lambda l: l.basis == 'percent_of_quantity')
        self.assertTrue(allowance.base_line_ids)
        self.assertTrue(all(b.version_id == v2 for b in allowance.base_line_ids))
        # occurrence keys are new (unique) but count preserved
        self.assertFalse(set(v1.recipe_line_ids.mapped('occurrence_key')) & set(v2.recipe_line_ids.mapped('occurrence_key')))
        v2.action_release()
        self.assertEqual(v1.state, 'superseded')
        self.assertEqual(v1.superseded_by_id, v2)
        self.assertEqual(scope.current_version_id, v2)

    def test_released_version_is_immutable(self):
        """PT-24: released content cannot be changed through write (UI, RPC and import all reach write)."""
        scope, v1 = self._make_master()
        with self.assertRaises(UserError):
            v1.write({'label_fa': 'x'})
        with self.assertRaises(UserError):
            v1.with_user(self.steward).write({'label_en': 'y'})
        with self.assertRaises(UserError):
            v1.recipe_line_ids[0].write({'rate': 9})
        with self.assertRaises(UserError):
            v1.recipe_line_ids[0].unlink()
        with self.assertRaises(UserError):
            self.env['sipanel.scope.recipe.line'].create({'version_id': v1.id, 'product_id': self.p_screw.id, 'uom_id': self.uom_unit.id})
        with self.assertRaises(UserError):
            v1.unlink()
        with self.assertRaises(UserError):
            v1.write({'state': 'draft'})
        # sudo does not bypass Python guards
        with self.assertRaises(UserError):
            v1.sudo().write({'label_fa': 'z'})
        # base_import path: load() -> write()
        xid = v1.recipe_line_ids[0].export_data(['id'])['datas'][0][0]
        res = self.env['sipanel.scope.recipe.line'].load(['id', 'rate'], [[xid, '99']])
        self.assertTrue(res.get('messages'), "import must be refused on a released version")
        self.assertEqual(v1.recipe_line_ids[0].rate, 1.0)

    def test_release_validations_block(self):
        scope = self.env['sipanel.scope'].create({'code': 'SIPANEL-PT-EMPTY', 'name': 'empty'})
        v = self.env['sipanel.scope.version'].create({'scope_id': scope.id, 'base_uom_id': self.uom_m.id, 'dimension_family': 'length'})
        with self.assertRaises(ValidationError) as cm:
            v.action_release()
        msg = str(cm.exception)
        for rule in ('R2', 'R4', 'R5', 'R6'):
            self.assertIn(rule, msg)
        self.assertEqual(v.state, 'draft')
        self.assertFalse(scope.current_version_id)

    def test_scope_unlink_and_copy_guards(self):
        scope, v1 = self._make_master()
        with self.assertRaises(UserError):
            scope.unlink()
        with self.assertRaises(UserError):
            scope.copy()
        with self.assertRaises(UserError):
            v1.copy()
        scope.action_archive()
        self.assertFalse(scope.active)

    def test_duplicate_as_new_scope(self):
        scope, v1 = self._make_master()
        new = self.env['sipanel.scope'].browse(scope.action_duplicate_as_new_scope(code='SIPANEL-PT-GUTTER-2')['res_id'])
        self.assertEqual(new.duplicated_from_id, scope)
        self.assertEqual(len(new.version_ids), 1)
        self.assertEqual(new.version_ids.state, 'draft')
        self.assertEqual(len(new.version_ids.recipe_line_ids), 8)

    def test_acl_plain_user_read_only(self):
        scope, v1 = self._make_master()
        from odoo.exceptions import AccessError
        with self.assertRaises(AccessError):
            scope.with_user(self.plain_user).write({'name': 'x'})
        with self.assertRaises(AccessError):
            self.env['sipanel.scope'].with_user(self.plain_user).create({'code': 'X', 'name': 'x'})
        self.assertEqual(scope.with_user(self.plain_user).read(['code'])[0]['code'], scope.code)
        # audit events are append-only for everybody, including admin
        ev = self.env['sipanel.scope.audit.event'].search([], limit=1)
        with self.assertRaises(UserError):
            ev.write({'reason': 'x'})
        with self.assertRaises(UserError):
            ev.sudo().unlink()

    def test_concurrent_release_lock(self):
        """GAP-A03: the identity is row-locked during release; a second cursor gets LockError -> UserError."""
        scope, v1 = self._make_master(release=False)
        with patch.object(type(scope), 'lock_for_update', side_effect=LockError('locked by another transaction')):
            with self.assertRaises(UserError):
                v1.action_release()
        self.assertEqual(v1.state, 'draft')
        self.assertFalse(scope.current_version_id)
