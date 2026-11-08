"""Isolated SQLite authorization regression tests (stdlib only)."""
import sqlite3
import unittest
from authorization import directory_scope_sql

PREFIX = "(t.requester_id=? OR t.assignee_id=? OR t.created_by=? OR EXISTS(SELECT 1 FROM tasks ta0 JOIN task_assignees x0 ON x0.task_id=ta0.id WHERE ta0.ticket_id=t.id AND x0.user_id=?) OR EXISTS(SELECT 1 FROM ticket_steps st0 WHERE st0.ticket_id=t.id AND st0.user_id=?)"

class FakeOrg:
    def __init__(self, ids, global_access=False): self.ids=ids; self.global_access=global_access
    def org_mode(self): return True
    def is_global(self, c, u): return self.global_access
    def scope_ids(self, c, u): return self.ids

class SecuritySQLTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        self.c.executescript('''CREATE TABLE tickets(id INTEGER,requester_id INTEGER,assignee_id INTEGER,created_by INTEGER,unit_id INTEGER,structure TEXT);
        CREATE TABLE tasks(id INTEGER,ticket_id INTEGER); CREATE TABLE task_assignees(task_id INTEGER,user_id INTEGER);
        CREATE TABLE ticket_steps(ticket_id INTEGER,user_id INTEGER);
        CREATE TABLE users(id INTEGER,org_unit_id INTEGER,active INTEGER);
        INSERT INTO tickets VALUES(1,1,NULL,1,10,'Shared'); INSERT INTO tickets VALUES(2,2,NULL,2,20,'Shared');
        INSERT INTO tickets VALUES(3,3,NULL,3,30,'Other');
        INSERT INTO users VALUES(1,10,1); INSERT INTO users VALUES(2,20,1); INSERT INTO users VALUES(3,30,1);''')
    def tearDown(self): self.c.close()
    def test_original_sql_allegation_not_reproduced(self):
        original=PREFIX+" OR (?='Local Administrator' AND t.structure<>'' AND t.structure=?))"
        result=self.c.execute('SELECT id FROM tickets t WHERE '+original,[4]*5+['Requester','']).fetchall()
        self.assertEqual(result,[])
    def test_confirmed_cross_unit_legacy_structure_bypass(self):
        original=PREFIX+" OR (?='Local Administrator' AND t.structure<>'' AND t.structure=?))"
        result=self.c.execute('SELECT id FROM tickets t WHERE '+original,[4]*5+['Local Administrator','Shared']).fetchall()
        self.assertEqual(result,[(1,),(2,)])
    def test_fixed_org_mode_scoped_query(self):
        sql=PREFIX+' OR t.unit_id IN (?))'
        self.assertEqual(self.c.execute('SELECT id FROM tickets t WHERE '+sql,[4]*5+[10]).fetchall(),[(1,)])
    def test_fixed_org_mode_direct_participant(self):
        sql=PREFIX+' OR t.unit_id IN (?))'
        self.assertEqual(self.c.execute('SELECT id FROM tickets t WHERE '+sql,[2]*5+[10]).fetchall(),[(1,),(2,)])
    def test_fixed_org_mode_unassigned(self):
        self.assertEqual(self.c.execute('SELECT id FROM tickets t WHERE '+PREFIX+')',[4]*5).fetchall(),[])
    def test_directory_scoped(self):
        u={'id':1}; sql,args=directory_scope_sql(u,FakeOrg([10]),self.c)
        self.assertEqual(self.c.execute('SELECT id FROM users u WHERE '+sql,args).fetchall(),[(1,)])
    def test_directory_self_only(self):
        u={'id':1}; sql,args=directory_scope_sql(u,FakeOrg([]),self.c)
        self.assertEqual(self.c.execute('SELECT id FROM users u WHERE '+sql,args).fetchall(),[(1,)])
    def test_directory_global(self):
        sql,args=directory_scope_sql({'id':1,'role':'System Administrator'},FakeOrg([],True),self.c)
        self.assertEqual(len(self.c.execute('SELECT id FROM users u WHERE '+sql,args).fetchall()),3)
    def test_directory_without_units_self_only(self):
        sql,args=directory_scope_sql({'id':1},None,self.c)
        self.assertEqual(self.c.execute('SELECT id FROM users u WHERE '+sql,args).fetchall(),[(1,)])

if __name__=='__main__': unittest.main()
