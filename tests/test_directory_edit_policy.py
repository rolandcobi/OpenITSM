"""Synthetic tests for directory update authorization without production dependencies."""
import sqlite3
import unittest
from authorization import directory_can_edit_target

class Org:
    def org_mode(self): return True
    def scope_ids(self, conn, actor): return [10,11] if actor['id']==1 else []

class DirectoryEditPolicyTests(unittest.TestCase):
    def setUp(self): self.db=sqlite3.connect(':memory:')
    def actor(self,role,uid=1): return {'id':uid,'role':role}
    def target(self,unit=10,role='Requester'): return {'org_unit_id':unit,'role':role}
    def allowed(self,role,unit=10,target_role='Requester',uid=1,org=None):
        return directory_can_edit_target(self.actor(role,uid),self.target(unit,target_role),Org() if org is None else org,self.db)
    def test_global_admin_any_unit(self): self.assertTrue(self.allowed('System Administrator',20))
    def test_central_admin_same_unit(self): self.assertTrue(self.allowed('Central Administrator',10))
    def test_central_admin_child_unit(self): self.assertTrue(self.allowed('Central Administrator',11))
    def test_central_admin_other_unit_denied(self): self.assertFalse(self.allowed('Central Administrator',20))
    def test_central_admin_unassigned_denied(self): self.assertFalse(self.allowed('Central Administrator',None))
    def test_central_admin_without_scope_denied(self): self.assertFalse(self.allowed('Central Administrator',10,uid=2))
    def test_central_admin_cannot_edit_system_admin(self): self.assertFalse(self.allowed('Central Administrator',10,'System Administrator'))
    def test_requester_denied(self): self.assertFalse(self.allowed('Requester'))
    def test_technician_denied(self): self.assertFalse(self.allowed('Operational Operator'))
    def test_manager_denied(self): self.assertFalse(self.allowed('Service Desk Manager'))
    def test_unknown_role_denied(self): self.assertFalse(self.allowed('unknown'))
    def tearDown(self): self.db.close()

if __name__=='__main__': unittest.main()
