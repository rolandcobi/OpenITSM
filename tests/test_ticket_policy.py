"""Synthetic, isolated SQLite regression tests for centralized ticket policy."""
import sqlite3
import unittest
from authorization import ticket_scope_sql

class Org:
    def org_mode(self): return True
    def scope_ids(self, conn, user): return [10] if user['id']==4 else [20]

class TicketPolicyTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.executescript('''
        CREATE TABLE tickets(id INTEGER,requester_id INTEGER,assignee_id INTEGER,created_by INTEGER,unit_id INTEGER,structure TEXT);
        CREATE TABLE tasks(id INTEGER,ticket_id INTEGER);
        CREATE TABLE task_assignees(task_id INTEGER,user_id INTEGER);
        CREATE TABLE ticket_steps(ticket_id INTEGER,user_id INTEGER);
        INSERT INTO tickets VALUES(1,1,3,1,10,'Shared');
        INSERT INTO tickets VALUES(2,2,5,2,20,'Shared');
        INSERT INTO tickets VALUES(3,2,NULL,2,20,'Other');
        INSERT INTO tasks VALUES(1,2);
        INSERT INTO task_assignees VALUES(1,3);
        ''')
    def tearDown(self): self.db.close()
    def ids(self,role,uid,org=None,structure='Shared'):
        sql,params=ticket_scope_sql({'role':role,'id':uid,'structure':structure},org,self.db)
        return [r[0] for r in self.db.execute('SELECT t.id FROM tickets t WHERE '+sql+' ORDER BY t.id',params)]
    def test_requester_own_only(self): self.assertEqual(self.ids('Requester',1),[1])
    def test_requester_other_unit_and_idor_denied(self): self.assertEqual(self.ids('Requester',2),[2,3])
    def test_technician_assigned_and_task_queue(self): self.assertEqual(self.ids('Operational Operator',3),[1,2])
    def test_technician_other_denied(self): self.assertEqual(self.ids('Operational Operator',6),[])
    def test_manager_org_scope(self): self.assertEqual(self.ids('Service Desk Manager',4,Org()),[1])
    def test_manager_cross_org_denied_even_matching_structure(self): self.assertNotIn(2,self.ids('Service Desk Manager',4,Org()))
    def test_admin_all(self): self.assertEqual(self.ids('System Administrator',7),[1,2,3])
    def test_central_admin_scope_required(self): self.assertEqual(self.ids('Central Administrator',7),[])
    def test_central_admin_unit_scope(self): self.assertEqual(self.ids('Central Administrator',7,Org()),[2,3])
    def test_auditor_no_ticket_data_by_default(self): self.assertEqual(self.ids('Auditor',8),[])
    def test_manager_no_text_scope_bypass(self): self.assertEqual(self.ids('Local Administrator',4),[])
    def test_manager_without_structure_denied(self): self.assertEqual(self.ids('Local Administrator',4,structure=''),[])
    def test_unknown_role_fail_closed(self): self.assertEqual(self.ids('Unexpected',9),[])
    def test_unknown_role_own_ticket_denied(self): self.assertEqual(self.ids('Unexpected',1),[])

if __name__=='__main__': unittest.main()
