r"""Flask integration checks using only a disposable synthetic database.

Run with .venv\Scripts\python.exe -m unittest discover -s tests -v.
"""
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
import io
import time
import zipfile
from unittest.mock import patch


from phase0_blocker_cases import BlockerCases
from phase0_runtime_cases import RuntimeCases
from phase0_closure_cases import ClosureCases


class Phase0HTTP(ClosureCases,BlockerCases,RuntimeCases,unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'app' in sys.modules:
            raise RuntimeError('Run integration tests in a fresh interpreter to guarantee database isolation.')
        cls.http_matrix = []
        cls.runtime_evidence = []
        cls.tmp = tempfile.TemporaryDirectory(prefix='openitsm-phase0-')
        cls.env = patch.dict(os.environ, {
            'ITSM_ENV':'test','ITSM_HTTPS':'0','ITSM_TLS':'1','ITSM_DEBUG':'0','ITSM_ALLOWED_HOSTS':'localhost,127.0.0.1',
            'ITSM_DB': os.path.join(cls.tmp.name, 'synthetic.db'),
            'ITSM_BACKUP': '0', 'ITSM_SECRET_KEY': 'synthetic-test-secret-' * 3,
            'ITSM_INITIAL_ADMIN_PASSWORD': 'SyntheticOnly!12345',
        })
        cls.env.start()
        cls.m = importlib.import_module('app')
        cls.m.app.config.update(TESTING=True)
        cls.real_send_async = staticmethod(cls.m.send_async)
        cls.mail = patch.object(cls.m, 'send_async')
        cls.mail.start()
        cls.real_send_email = staticmethod(cls.m.send_email)
        cls.sync_mail = patch.object(cls.m, 'send_email', return_value=(True, 'Synthetic delivery'))
        cls.sync_mail.start()
        cls.bulk_mail = patch.object(cls.m, 'send_bulk')
        cls.bulk_mail.start()
        c = cls.m.db()
        for i, role in enumerate(cls.m.ROLES, 1):
            if i == 1:
                c.execute('UPDATE users SET profile_done=1 WHERE id=1')
            else:
                c.execute('INSERT INTO users(id,username,full_name,role,structure,profile_done,org_unit_id) VALUES(?,?,?,?,?,1,?)',
                          (i, 'synthetic'+str(i), 'Synthetic '+role, role, 'Unit A', 2))
        c.execute("INSERT INTO users(id,username,full_name,role,structure,profile_done,org_unit_id) VALUES(99,'other','FOREIGN_USER','Requester','Unit B',1,6)")
        for tid, uid, unit in ((101,8,2),(102,99,6)):
            c.execute("INSERT INTO tickets(id,code,title,description,type,status,priority,requester_id,created_by,unit_id,structure,created_at) VALUES(?,?,?,'synthetic','Service Request','Open','Medium',?,?,?,?,'2026-11-04 10:00:00')",
                      (tid, 'SYN-'+str(tid), 'SECRET_'+str(tid), uid, uid, unit, 'Unit A' if unit==2 else 'Unit B'))
            c.execute("INSERT INTO tasks(id,ticket_id,title,status,created_at) VALUES(?,?,?,'Open','2026-11-04 10:00:00')", (tid,tid,'TASK_SECRET_'+str(tid)))
        c.execute("INSERT INTO boards(id,name,owner_id) VALUES(901,'PRIVATE_BOARD',99)")
        c.execute("INSERT INTO board_lists(id,board_id,name) VALUES(901,901,'Private')")
        c.execute("INSERT INTO cards(id,board_id,list_id,title,creator_id) VALUES(901,901,901,'PRIVATE_CARD',99)")
        c.execute("INSERT INTO teams(id,name,owner_id) VALUES(901,'PRIVATE_TEAM',99)")
        c.execute("INSERT INTO chat_messages(from_id,to_id,body) VALUES(99,1,'PRIVATE_CHAT')")
        c.execute("INSERT INTO timeline(ticket_id,event_type,details,created_at) VALUES(102,'Comment','FOREIGN_ACTIVITY_SECRET','2026-11-04 10:00:00')")
        c.execute('UPDATE tickets SET service_id=1 WHERE id=102')
        c.commit()
        cls.baseline=sqlite3.connect(':memory:')
        c.backup(cls.baseline)
        c.close()

    @classmethod
    def tearDownClass(cls):
        cls.baseline.close(); cls.mail.stop(); cls.sync_mail.stop(); cls.bulk_mail.stop(); cls.env.stop(); cls.tmp.cleanup()

    def setUp(self):
        self.client = self.m.app.test_client()
        self.m.FAILS.clear()
        c = self.m.db()
        self.baseline.backup(c)
        c.execute("INSERT OR REPLACE INTO settings VALUES('visibility_mode','org')")
        c.commit(); c.close()

    def actor(self, uid):
        with self.client.session_transaction() as s:
            s.clear(); s.update(auth_version=self.rows('SELECT auth_version FROM users WHERE id=?',(uid,))[0][0],issued_at=time.time(),uid=uid, csrf='synthetic-csrf', role='System Administrator', name='Synthetic')

    def post(self, path, **data):
        return self.client.post(path, data=dict(csrf_token='synthetic-csrf', **data))

    def routes(self):
        for r in self.m.app.url_map.iter_rules():
            if r.endpoint == 'static': continue
            path = str(r)
            for key in r.arguments:
                value = '101' if key in ('tid','taskid') else '901' if key in ('bid','kid') else 'tickets' if key=='kind' else 'csv' if key=='fmt' else '901'
                path = path.replace('<int:'+key+'>',value).replace('<'+key+'>',value)
            yield r, path

    def test_all_routes_require_authentication(self):
        for r, path in self.routes():
            if r.endpoint in ('login','logout'): continue
            with self.subTest(path=path):
                with self.client.session_transaction() as s:
                    s.clear(); s['csrf']='synthetic-csrf'
                response = self.client.get(path) if 'GET' in r.methods else self.post(path)
                self.assertEqual(response.status_code,302)
                self.assertIn('/login',response.location)

    def test_csrf_every_post_route(self):
        self.actor(1)
        c=self.m.db(); before='\n'.join(c.iterdump()); c.close()
        for r, path in self.routes():
            if 'POST' not in r.methods: continue
            for data in ({}, {'csrf_token':'wrong'}):
                with self.subTest(path=path, data=data):
                    self.assertEqual(self.client.post(path,data=data).status_code,403)
        c=self.m.db(); after='\n'.join(c.iterdump()); c.close()
        self.assertEqual(before,after)
        self.assertEqual(self.client.post('/api/chat/send',json={'to':99,'body':'synthetic'},headers={'X-CSRF':'synthetic-csrf'}).status_code,201)

    def test_unsupported_methods(self):
        self.actor(1)
        for r,path in self.routes():
            for method in ('PUT','PATCH','DELETE'):
                with self.subTest(path=path,method=method):
                    self.assertEqual(self.client.open(path,method=method).status_code,405)

    def test_get_matrix_all_roles(self):
        c=self.m.db(); mode=c.execute("SELECT value FROM settings WHERE key='visibility_mode'").fetchone()[0]; c.close()
        for uid,role in enumerate(self.m.ROLES,1):
            self.actor(uid)
            for r,path in self.routes():
                if 'GET' not in r.methods or r.endpoint in ('logout','login'): continue
                with self.subTest(role=role,path=path):
                    response=self.client.get(path)
                    self.http_matrix.append((mode,role,str(r),response.status_code))
                    self.assertIn(response.status_code,(200,302,403,404))

    def test_requester_ticket_task_idor_and_exports(self):
        self.actor(8)
        self.assertEqual(self.client.get('/tickets/101').status_code,200)
        for path in ('/tickets/102','/tasks/102'):
            self.assertEqual(self.client.get(path).status_code,403)
        for action in ('comment','status','step_add','step_done','task'):
            self.assertEqual(self.post('/tickets/102',action=action,comment='attack').status_code,403)
        for path in ('/tasks/102/complete','/tasks/102/do'):
            self.assertEqual(self.post(path,action='start',completion_notes='attack').status_code,403)
        for path in ('/','/tickets','/tasks?scope=all','/calendar','/reports','/reports/export/tickets/csv','/reports/export/tasks/csv','/reports/export/summary/csv'):
            with self.subTest(path=path):
                self.assertNotIn(b'SECRET_102',self.client.get(path).data)
        for action in ('status','task','step_add','step_done'):
            self.assertEqual(self.post('/tickets/101',action=action).status_code,403)
        self.assertEqual(self.post('/tickets/101',action='comment',comment='synthetic allowed comment').status_code,302)
        self.assertEqual(self.post('/tickets/new',assignee_id='1').status_code,403)

    def test_privileged_endpoint_denials(self):
        for uid in (2,3,4,6,7,8,9):
            self.actor(uid)
            for path in ('/users','/admin','/admin/test-email','/directory','/org','/assets','/services'):
                if path=='/assets' and uid in (2,3): continue
                with self.subTest(uid=uid,path=path):
                    self.assertEqual(self.post(path,action='rename_service',service_id='1',name='attack').status_code,403)

    def test_private_workspace_and_chat_idor(self):
        self.actor(8)
        for path in ('/space/team/901','/space/team/901/dashboard','/space/board/901'):
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.post('/space/card/901/move',list_id='901').status_code,403)
        for path in ('/api/chat/state','/api/chat/poll','/api/chat/thread?with=99'):
            self.assertNotIn(b'PRIVATE_CHAT',self.client.get(path).data)

    def test_directory_cross_unit_does_not_mutate(self):
        self.actor(5)
        self.post('/directory',user_id='99',full_name='ATTACK')
        c=self.m.db()
        self.assertEqual(c.execute('SELECT full_name FROM users WHERE id=99').fetchone()[0],'FOREIGN_USER')
        c.close()

    def rows(self, sql, args=()):
        c=self.m.db()
        try: return [tuple(r) for r in c.execute(sql,args)]
        finally: c.close()

    def execute(self, sql, args=()):
        c=self.m.db()
        try: c.execute(sql,args); c.commit()
        finally: c.close()

    def session_token(self, client=None):
        with (client or self.client).session_transaction() as s: return s.get('csrf')

    def login_admin(self):
        self.client.get('/login')
        return self.client.post('/login',data={'csrf_token':self.session_token(),'username':'admin','password':'SyntheticOnly!12345'})

    def test_login_rotation_invalid_credentials_and_lockout(self):
        self.client.get('/login'); old=self.session_token()
        self.assertEqual(self.login_admin().status_code,302)
        self.assertNotEqual(self.session_token(),old)
        with self.client.session_transaction() as s:
            self.assertEqual(s['uid'],1); self.assertTrue(s.permanent)
        self.client.post('/logout',data={'csrf_token':self.session_token()})
        for _ in range(5):
            self.client.get('/login')
            self.client.post('/login',data={'csrf_token':self.session_token(),'username':'admin','password':'wrong'})
            with self.client.session_transaction() as s: self.assertNotIn('uid',s)
        self.assertTrue(self.rows('SELECT locked_until FROM users WHERE id=1')[0][0])
        self.assertEqual(self.login_admin().status_code,200)
        with self.client.session_transaction() as s: self.assertNotIn('uid',s)
        self.execute("UPDATE users SET locked_until='2000-01-01 00:00:00' WHERE id=1")
        self.assertEqual(self.login_admin().status_code,302)
        self.assertEqual(self.rows('SELECT failed,locked_until FROM users WHERE id=1'),[(0,None)])

    def test_ip_throttling_and_inactive_login(self):
        self.client.get('/login')
        for _ in range(20):
            self.client.post('/login',data={'csrf_token':self.session_token(),'username':'missing-synthetic','password':'wrong'})
        self.assertEqual(self.login_admin().status_code,429)
        self.m.FAILS.clear(); self.execute('DELETE FROM login_attempts'); self.execute('UPDATE users SET active=0 WHERE id=1')
        self.login_admin()
        with self.client.session_transaction() as s: self.assertNotIn('uid',s)

    def test_disabled_deleted_and_demoted_sessions(self):
        for change in ('UPDATE users SET active=0 WHERE id=1','DELETE FROM users WHERE id=1'):
            self.setUp(); self.actor(1); self.execute(change)
            self.assertEqual(self.client.get('/admin').status_code,302)
            with self.client.session_transaction() as s: self.assertNotIn('uid',s)
        self.setUp(); self.actor(1); self.execute("UPDATE users SET role='Requester' WHERE id=1")
        self.assertEqual(self.post('/admin',form='group',name='FORGED_GROUP').status_code,403)
        self.assertEqual(self.rows("SELECT id FROM support_groups WHERE name='FORGED_GROUP'"),[])

    def test_tampered_expired_cookie_and_cookie_attributes(self):
        self.login_admin()
        cookie=self.client.get_cookie('session').value
        client=self.m.app.test_client(); client.set_cookie('session',cookie+'tampered')
        self.assertEqual(client.get('/users').status_code,302)
        serializer=self.m.app.session_interface.get_signing_serializer(self.m.app)
        with patch('time.time',return_value=time.time()-3600):
            expired=serializer.dumps({'uid':1,'auth_version':0,'issued_at':time.time(),'csrf':'synthetic-csrf','_permanent':True})
        client.set_cookie('session',expired)
        self.assertEqual(client.get('/users').status_code,302)
        response=self.client.get('/account')
        cookies=';'.join(response.headers.getlist('Set-Cookie'))
        self.assertIn('HttpOnly',cookies); self.assertIn('SameSite=Lax',cookies)
        with patch.dict(self.m.app.config,SESSION_COOKIE_SECURE=True):
            self.assertIn('Secure',';'.join(self.client.get('/account').headers.getlist('Set-Cookie')))

    def test_must_change_gate_on_all_protected_routes(self):
        self.execute('UPDATE users SET must_change=1 WHERE id=1')
        for rule,path in self.routes():
            if rule.endpoint in ('login','logout','account'): continue
            self.actor(1)
            response=self.client.get(path) if 'GET' in rule.methods else self.post(path)
            with self.subTest(path=path):
                self.assertEqual(response.status_code,302); self.assertIn('/account',response.location)

    def test_password_validation_rotation_and_self_only(self):
        self.actor(1)
        before=self.rows('SELECT password_hash FROM users WHERE id=1')
        for fields in (dict(current='wrong',new='SyntheticNew!12345',confirm='SyntheticNew!12345'),dict(current='SyntheticOnly!12345',new='short',confirm='short'),dict(current='SyntheticOnly!12345',new='SyntheticNew!12345',confirm='mismatch')):
            self.post('/account',**fields)
            self.assertEqual(self.rows('SELECT password_hash FROM users WHERE id=1'),before)
        foreign=self.rows('SELECT password_hash FROM users WHERE id=99')
        self.assertEqual(self.post('/account',current='SyntheticOnly!12345',new='SyntheticNew!12345',confirm='SyntheticNew!12345',user_id='99').status_code,302)
        self.assertNotEqual(self.session_token(),'synthetic-csrf')
        self.assertEqual(self.client.get('/account').status_code,200)
        self.assertEqual(self.rows('SELECT password_hash FROM users WHERE id=99'),foreign)
        self.assertEqual(self.post('/profile',action='skip').status_code,403)
        self.assertTrue(self.m.check_password_hash(self.rows('SELECT password_hash FROM users WHERE id=1')[0][0],'SyntheticNew!12345'))

    def test_csrf_session_binding_json_and_no_mutation(self):
        self.actor(8)
        before=self.rows('SELECT * FROM chat_messages')
        for headers in ({},{'X-CSRF':'other-session-token'}):
            self.assertEqual(self.client.post('/api/chat/send',json={'to':2,'body':'forged'},headers=headers).status_code,403)
        self.assertEqual(self.rows('SELECT * FROM chat_messages'),before)
        self.assertEqual(self.client.post('/api/chat/send',json={'to':2,'body':'allowed'},headers={'X-CSRF':'synthetic-csrf'}).status_code,201)
        self.assertEqual(self.rows('SELECT from_id,to_id,body FROM chat_messages ORDER BY id DESC LIMIT 1'),[(8,2,'allowed')])
        other=self.m.app.test_client(); other.get('/login')
        self.assertEqual(other.post('/login',data={'csrf_token':'synthetic-csrf','username':'admin','password':'SyntheticOnly!12345'}).status_code,403)

    def test_users_all_existing_target_actions_cross_unit(self):
        for target in (1,99):
            for action in ('update','reset','activate','deactivate','delete'):
                self.actor(5); before=self.rows('SELECT * FROM users WHERE id=?',(target,))
                with self.subTest(target=target,action=action):
                    self.assertEqual(self.post('/users',action=action,user_id=str(target),role='Requester',password='SyntheticReset!12345',full_name='FORGED').status_code,403)
                    self.assertEqual(self.rows('SELECT * FROM users WHERE id=?',(target,)),before)

    def test_users_create_update_reset_activate_delete(self):
        self.actor(1)
        self.assertEqual(self.post('/users',action='create',username='synthetic-created',full_name='Synthetic created',role='Requester',password='SyntheticCreated!12345').status_code,302)
        uid=self.rows("SELECT id FROM users WHERE username='synthetic-created'")[0][0]
        self.assertEqual(self.rows('SELECT must_change FROM users WHERE id=?',(uid,)),[(1,)])
        self.post('/users',action='update',user_id=str(uid),role='Requester',full_name='Synthetic updated')
        self.assertEqual(self.rows('SELECT full_name FROM users WHERE id=?',(uid,)),[('Synthetic updated',)])
        self.post('/users',action='reset',user_id=str(uid),password='SyntheticReset!12345')
        self.assertTrue(self.m.check_password_hash(self.rows('SELECT password_hash FROM users WHERE id=?',(uid,))[0][0],'SyntheticReset!12345'))
        self.post('/users',action='deactivate',user_id=str(uid)); self.assertEqual(self.rows('SELECT active FROM users WHERE id=?',(uid,)),[(0,)])
        self.post('/users',action='activate',user_id=str(uid)); self.assertEqual(self.rows('SELECT active FROM users WHERE id=?',(uid,)),[(1,)])
        self.post('/users',action='delete',user_id=str(uid)); self.assertEqual(self.rows('SELECT id FROM users WHERE id=?',(uid,)),[])
        self.post('/users',action='deactivate',user_id='1'); self.assertEqual(self.rows('SELECT active FROM users WHERE id=1'),[(1,)])

    def test_service_owner_object_permissions(self):
        self.execute('UPDATE services SET owner_id=2,unit_id=2 WHERE id=1')
        self.execute('UPDATE services SET unit_id=6 WHERE id=2')
        self.actor(2)
        before=self.rows('SELECT * FROM services WHERE id=2')
        self.assertEqual(self.post('/services',action='update',service_id='2',status='Degraded',owner_id='2').status_code,403)
        self.assertEqual(self.post('/services',action='add_subsection',parent_service_id='2',name='FORGED').status_code,403)
        self.assertEqual(self.rows('SELECT * FROM services WHERE id=2'),before)
        self.assertEqual(self.post('/services',action='update',service_id='1',status='Degraded',owner_id='2').status_code,200)
        self.assertEqual(self.rows('SELECT status FROM services WHERE id=1'),[('Degraded',)])
        self.assertEqual(self.post('/services',action='add_subsection',parent_service_id='1',name='Synthetic subsection').status_code,302)
        self.assertEqual(self.rows("SELECT parent_service_id FROM services WHERE name='Synthetic subsection'"),[(1,)])

    def test_infra_capability_cannot_mutate_foreign_service(self):
        self.execute('UPDATE users SET can_infra=1 WHERE id=4')
        self.execute('UPDATE services SET unit_id=6 WHERE id=2')
        self.actor(4); before=self.rows('SELECT * FROM services WHERE id=2')
        response=self.post('/services',action='rename_service',service_id='2',name='FORGED FOREIGN SERVICE')
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.rows('SELECT * FROM services WHERE id=2'),before)

    def test_central_admin_cannot_self_grant_infra_capability(self):
        self.actor(5); before=self.rows('SELECT * FROM users WHERE id=5')
        self.assertEqual(self.post('/users',action='update',user_id='5',role='Central Administrator',can_infra='1').status_code,403)
        self.assertEqual(self.rows('SELECT * FROM users WHERE id=5'),before)

    def test_service_foreign_mutations_denied_in_both_modes(self):
        self.execute('UPDATE users SET can_infra=1 WHERE id=4')
        self.execute('UPDATE services SET unit_id=6,owner_id=2 WHERE id=2')
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            for uid in (2,4):
                self.actor(uid)
                for fields in (dict(action='rename_service',service_id='2'),dict(action='update',service_id='2',status='Major Outage'),dict(action='add_subsection',parent_service_id='2')):
                    before=self.rows('SELECT * FROM services ORDER BY id')
                    with self.subTest(mode=mode,uid=uid,action=fields['action']):
                        self.assertEqual(self.post('/services',name='FORGED',**fields).status_code,403)
                        self.assertEqual(self.rows('SELECT * FROM services ORDER BY id'),before)

    def test_service_local_creation_subsection_and_system_global(self):
        self.execute('UPDATE users SET can_infra=1 WHERE id=4'); self.actor(4)
        self.assertEqual(self.post('/services',action='add_service',name='Synthetic scoped service').status_code,302)
        sid,unit=self.rows("SELECT id,unit_id FROM services WHERE name='Synthetic scoped service'")[0]
        self.assertEqual(unit,2)
        self.assertEqual(self.post('/services',action='rename_service',service_id=str(sid),name='Synthetic renamed local').status_code,302)
        self.assertEqual(self.post('/services',action='add_subsection',parent_service_id=str(sid),name='Synthetic scoped child',owner_id='2').status_code,302)
        self.assertEqual(self.rows("SELECT parent_service_id,unit_id FROM services WHERE name='Synthetic scoped child'"),[(sid,2)])
        self.assertEqual(self.post('/services',action='update',service_id=str(sid),status='Degraded',owner_id='2').status_code,200)
        self.assertEqual(self.rows('SELECT status,owner_id FROM services WHERE id=?',(sid,)),[('Degraded',2)])
        self.actor(1); self.execute('UPDATE services SET unit_id=6 WHERE id=2')
        self.assertEqual(self.post('/services',action='rename_service',service_id='2',name='Synthetic global rename').status_code,302)
        self.assertEqual(self.rows('SELECT name FROM services WHERE id=2'),[('Synthetic global rename',)])

    def test_service_unassigned_shared_rebinding_and_malformed_ids(self):
        from werkzeug.datastructures import MultiDict
        self.execute('UPDATE users SET can_infra=1 WHERE id=4'); self.actor(4)
        self.execute('UPDATE services SET unit_id=2 WHERE id=1')
        before=self.rows('SELECT * FROM services ORDER BY id')
        for fields in (dict(action='add_service',unit_id='6'),dict(action='update',service_id='1',owner_id='99',status='Degraded'),dict(action='update',service_id='1',unit_id='6',status='Degraded'),dict(action='rename_service',service_id='2')):
            self.assertEqual(self.post('/services',name='FORGED',**fields).status_code,403)
        for fields in (dict(action='rename_service',service_id='bad'),dict(action='add_subsection',parent_service_id=''),dict(action='update',service_id='1',owner_id='99999'),dict(action='add_service',unit_id='-1')):
            self.assertEqual(self.post('/services',name='FORGED',**fields).status_code,400)
        self.assertEqual(self.client.post('/services',data=MultiDict([('csrf_token','synthetic-csrf'),('action','rename_service'),('service_id','1'),('service_id','2'),('name','FORGED')])).status_code,400)
        self.assertEqual(self.rows('SELECT * FROM services ORDER BY id'),before)
        self.execute('UPDATE users SET org_unit_id=NULL WHERE id=4')
        self.assertEqual(self.post('/services',action='add_service',name='FORGED').status_code,403)

    def test_capability_delegation_is_system_only_and_revocation_effective(self):
        self.actor(5)
        self.assertEqual(self.post('/users',action='create',username='FORGED_CAP',full_name='FORGED',role='Operational Operator',password='SyntheticOnly!12345',can_infra='1').status_code,403)
        self.assertEqual(self.rows("SELECT id FROM users WHERE username='FORGED_CAP'"),[])
        self.assertEqual(self.post('/users',action='update',user_id='4',role='Operational Operator',can_infra='1').status_code,403)
        self.actor(1)
        self.assertEqual(self.post('/users',action='update',user_id='4',role='Operational Operator',can_infra='1').status_code,302)
        self.assertEqual(self.rows('SELECT can_infra FROM users WHERE id=4'),[(1,)])
        self.assertEqual(self.rows("SELECT old_value,new_value FROM audit WHERE action='InfrastructureCapability' AND object_id=4"),[('0','1')])
        self.actor(5)
        self.assertEqual(self.post('/users',action='update',user_id='4',role='Operational Operator',full_name='Synthetic normal edit').status_code,302)
        self.assertEqual(self.rows('SELECT can_infra FROM users WHERE id=4'),[(1,)])
        self.assertEqual(self.post('/users',action='update',user_id='4',role='Operational Operator',can_infra='').status_code,403)
        self.assertNotIn(b'name="can_infra"',self.client.get('/users').data)
        self.execute('UPDATE services SET unit_id=2 WHERE id=1')
        self.actor(4)
        self.assertEqual(self.post('/services',action='rename_service',service_id='1',name='Synthetic allowed capability').status_code,302)
        admin=self.m.app.test_client()
        with admin.session_transaction() as session: session.update(auth_version=0,issued_at=time.time(),uid=1,csrf='admin-csrf',role='System Administrator',name='Synthetic admin')
        self.assertEqual(admin.post('/users',data={'csrf_token':'admin-csrf','action':'update','user_id':'4','role':'Operational Operator'}).status_code,302)
        self.assertEqual(self.post('/services',action='rename_service',service_id='1',name='FORGED REVOKED').status_code,403)
        self.assertEqual(self.rows('SELECT name FROM services WHERE id=1'),[('Synthetic allowed capability',)])

    def test_assets_update_delete_role_and_capability(self):
        self.actor(1); self.post('/assets',name='Synthetic asset',unit_id='2')
        aid=self.rows("SELECT id FROM assets WHERE name='Synthetic asset'")[0][0]
        for uid in (4,6,7,8,9):
            self.actor(uid)
            for action in ('update','delete'):
                self.assertEqual(self.post('/assets',action=action,asset_id=str(aid),name='FORGED',confirm='1').status_code,403)
                self.assertEqual(self.rows('SELECT name FROM assets WHERE id=?',(aid,)),[('Synthetic asset',)])
        self.execute('UPDATE users SET can_infra=1 WHERE id=4'); self.actor(4)
        self.assertEqual(self.post('/assets',action='update',asset_id=str(aid),name='Synthetic updated').status_code,302)
        self.assertEqual(self.rows('SELECT name FROM assets WHERE id=?',(aid,)),[('Synthetic updated',)])
        self.post('/assets',action='delete',asset_id=str(aid),confirm='1')
        self.assertEqual(self.rows('SELECT id FROM assets WHERE id=?',(aid,)),[])

    def test_org_bulk_rollback_and_foreign_preservation(self):
        self.actor(5)
        before=self.rows('SELECT id,org_unit_id,org_head FROM users ORDER BY id')
        self.assertEqual(self.post('/org',action='assign_users',unit_2='2',head_2='1',unit_3='6').status_code,403)
        self.assertEqual(self.rows('SELECT id,org_unit_id,org_head FROM users ORDER BY id'),before)
        fields={'unit_'+str(uid):'2' for uid in (2,3,4,5,6,7,9)}
        fields['unit_99']='2'; fields['unit_1']='2'
        self.assertEqual(self.post('/org',action='assign_users',**fields).status_code,302)
        self.assertEqual(self.rows('SELECT org_unit_id FROM users WHERE id=99'),[(6,)])
        self.assertEqual(self.rows('SELECT org_unit_id FROM users WHERE id=1'),[(None,)])
        self.execute('UPDATE services SET unit_id=2 WHERE id IN (1,2)')
        self.execute('UPDATE services SET unit_id=6 WHERE id=3')
        before=self.rows('SELECT id,unit_id FROM services ORDER BY id')
        self.assertEqual(self.post('/org',action='service_map',svc_1='2',svc_2='6',svc_3='2').status_code,403)
        self.assertEqual(self.rows('SELECT id,unit_id FROM services ORDER BY id'),before)
        self.assertEqual(self.post('/org',action='service_map',svc_1='2',svc_2='2',svc_3='2').status_code,302)
        self.assertEqual(self.rows('SELECT unit_id FROM services WHERE id=3'),[(6,)])

    def test_org_unit_add_delete_and_cycle_guard(self):
        self.actor(5)
        self.assertEqual(self.post('/org',action='unit_add',parent_id='6',name='FORGED').status_code,403)
        self.assertEqual(self.post('/org',action='unit_delete',id='6',confirm='1').status_code,403)
        self.assertEqual(self.post('/org',action='unit_add',parent_id='2',name='Synthetic leaf').status_code,302)
        leaf=self.rows("SELECT id FROM org_units WHERE name='Synthetic leaf'")[0][0]
        self.actor(1)
        parent=self.rows('SELECT parent_id FROM org_units WHERE id=2')
        self.post('/org',action='unit_move',id='2',parent_id=str(leaf))
        self.assertEqual(self.rows('SELECT parent_id FROM org_units WHERE id=2'),parent)
        self.post('/org',action='unit_delete',id=str(leaf),confirm='1')
        self.assertEqual(self.rows('SELECT id FROM org_units WHERE id=?',(leaf,)),[])

    def test_private_workspace_all_dispatchers_deny_without_mutation(self):
        self.actor(8)
        tables=('cards','boards','board_lists','teams','team_members')
        before={t:self.rows('SELECT * FROM '+t) for t in tables}
        for path,actions in (('/space',('task_done',)),('/space/team/901',('add_member','add_sector','remove_member','set_role','board_create','board_archive','team_update','team_delete')),('/space/board/901',('list_add','list_delete','card_add','card_update','card_delete','board_rename','board_delete'))):
            for action in actions:
                with self.subTest(path=path,action=action):
                    self.assertEqual(self.post(path,action=action,card_id='901',list_id='901',user_id='8',name='FORGED',title='FORGED',confirm='1',role='Lead').status_code,403)
        self.assertEqual(self.post('/space',action='task_add',title='FORGED',dest='t:901:8').status_code,403)
        self.assertEqual({t:self.rows('SELECT * FROM '+t) for t in tables},before)

    def test_workspace_allowed_card_and_foreign_list_binding(self):
        self.actor(8)
        self.post('/space',action='board_create',name='Synthetic board')
        bid=self.rows("SELECT id FROM boards WHERE name='Synthetic board'")[0][0]
        lid=self.rows('SELECT id FROM board_lists WHERE board_id=? ORDER BY pos',(bid,))[0][0]
        self.post('/space/board/'+str(bid),action='card_add',list_id=str(lid),title='Synthetic card')
        kid=self.rows("SELECT id FROM cards WHERE title='Synthetic card'")[0][0]
        self.assertEqual(self.client.post('/space/card/'+str(kid)+'/move',json={'list_id':901},headers={'X-CSRF':'synthetic-csrf'}).status_code,400)
        self.assertEqual(self.rows('SELECT board_id,list_id FROM cards WHERE id=?',(kid,)),[(bid,lid)])
        self.assertEqual(self.client.post('/space/card/'+str(kid)+'/move',json={'list_id':lid,'pos':0},headers={'X-CSRF':'synthetic-csrf'}).status_code,200)
        self.post('/space/board/'+str(bid),action='card_delete',card_id='901')
        self.assertEqual(self.rows('SELECT title FROM cards WHERE id=901'),[('PRIVATE_CARD',)])
        self.post('/space',action='task_done',card_id=str(kid))
        self.assertIsNotNone(self.rows('SELECT completed_at FROM cards WHERE id=?',(kid,))[0][0])

    def test_task_update_reopen_subtask_and_parent_binding(self):
        self.actor(1)
        self.assertEqual(self.post('/tasks/101/do',action='update',note='Synthetic update').status_code,302)
        self.assertEqual(self.post('/tasks/101/do',action='subtask',task_title='Synthetic child',task_assignees='4',ticket_id='102',parent_id='102').status_code,302)
        child=self.rows("SELECT id,ticket_id,parent_id FROM tasks WHERE title='Synthetic child'")[0]
        self.assertEqual(child[1:],(101,101))
        self.post('/tasks/101/complete',completion_notes='Synthetic completion')
        self.assertEqual(self.rows('SELECT status FROM tasks WHERE id=101'),[('Open',)])
        self.post('/tasks/'+str(child[0])+'/complete',completion_notes='Synthetic child complete')
        self.post('/tasks/101/complete',completion_notes='Synthetic completion')
        self.assertEqual(self.rows('SELECT status FROM tasks WHERE id=101'),[('Completed',)])
        self.post('/tasks/101/do',action='reopen',note='Synthetic reopen reason')
        self.assertEqual(self.rows('SELECT status FROM tasks WHERE id=101'),[('In Progress',)])

    def test_workflow_step_identity_and_ticket_binding(self):
        self.actor(1)
        self.post('/tickets/101',action='step_add',step_user='4')
        self.assertEqual(self.rows('SELECT user_id,status FROM ticket_steps WHERE ticket_id=101'),[(4,'Active')])
        self.actor(3)
        before=self.rows('SELECT * FROM ticket_steps WHERE ticket_id=101')
        self.assertEqual(self.post('/tickets/101',action='step_done',note='Synthetic signed',step_id='999').status_code,403)
        self.assertEqual(self.rows('SELECT * FROM ticket_steps WHERE ticket_id=101'),before)
        self.actor(4)
        self.assertEqual(self.post('/tickets/101',action='step_done',note='Synthetic signed',ticket_id='102').status_code,302)
        self.assertEqual(self.rows('SELECT status FROM ticket_steps WHERE ticket_id=101'),[('Done',)])
        self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=102'),[('Open',)])

    def test_profile_and_notifications_ignore_forged_user_ids(self):
        self.execute("INSERT INTO notifications(user_id,title,message) VALUES(99,'PRIVATE_NOTIFICATION','PRIVATE_NOTIFICATION')")
        self.actor(8); before=self.rows('SELECT full_name FROM users WHERE id=99')
        self.post('/profile',user_id='99',full_name='Synthetic requester',email='synthetic@example.invalid')
        self.assertEqual(self.rows('SELECT full_name FROM users WHERE id=99'),before)
        for path in ('/notifications?user_id=99','/api/poll?user_id=99&since=-1','/directory','/api/users/search?q=FOREIGN_USER'):
            self.assertNotIn(b'PRIVATE_NOTIFICATION',self.client.get(path).data)
        self.assertEqual(self.rows('SELECT is_read FROM notifications WHERE user_id=99'),[(0,)])
        self.assertNotIn(b'FOREIGN_USER',self.client.get('/directory').data)
        self.assertNotIn(b'FOREIGN_USER',self.client.get('/api/users/search?q=FOREIGN_USER').data)

    def test_xlsx_exports_filter_foreign_ticket_data(self):
        self.actor(8)
        for kind in ('tickets','tasks','summary'):
            response=self.client.get('/reports/export/'+kind+'/xlsx')
            self.assertEqual(response.status_code,200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as z:
                content=b''.join(z.read(name) for name in z.namelist())
                self.assertNotIn(b'SECRET_102',content)
        self.assertEqual(self.client.get('/reports/export/invalid/csv').status_code,404)

    def test_admin_forms_and_mock_email(self):
        self.actor(1)
        self.assertEqual(self.post('/admin',form='group',name='Synthetic group').status_code,302)
        self.assertEqual(len(self.rows("SELECT id FROM support_groups WHERE name='Synthetic group'")),1)
        self.assertEqual(self.post('/admin',form='announcement',title='Synthetic announcement',message='Synthetic message',kind='info').status_code,302)
        self.assertEqual(len(self.rows("SELECT id FROM announcements WHERE title='Synthetic announcement'")),1)
        self.assertEqual(self.post('/admin',form='smtp',smtp_host='synthetic.invalid',smtp_security='tls').status_code,302)
        with patch.object(self.m,'send_email',return_value=(True,'Synthetic only')) as mail:
            self.assertEqual(self.post('/admin/test-email',to='synthetic@example.invalid').status_code,302)
            mail.assert_called_once()

    def test_acceptance_get_logout_must_not_mutate_session(self):
        """Regression: GET logout permits cross-site forced logout."""
        self.actor(8); self.client.get('/logout')
        with self.client.session_transaction() as s: self.assertEqual(s.get('uid'),8)

    def test_acceptance_logout_revokes_copied_cookie(self):
        """Regression: signed cookies survive logout when replayed."""
        self.login_admin(); cookie=self.client.get_cookie('session').value
        self.client.post('/logout',data={'csrf_token':self.session_token()})
        replay=self.m.app.test_client(); replay.set_cookie('session',cookie)
        self.assertEqual(replay.get('/users').status_code,302)

    def test_acceptance_password_change_revokes_other_sessions(self):
        """Regression: old cookies survive a password change."""
        self.login_admin(); cookie=self.client.get_cookie('session').value
        self.client.post('/account',data={'csrf_token':self.session_token(),'current':'SyntheticOnly!12345','new':'SyntheticNew!12345','confirm':'SyntheticNew!12345'})
        replay=self.m.app.test_client(); replay.set_cookie('session',cookie)
        self.assertEqual(replay.get('/users').status_code,302)

    def test_admin_reset_and_reactivation_do_not_restore_old_sessions(self):
        self.actor(8); cookie=self.client.get_cookie('session').value
        admin=self.m.app.test_client()
        with admin.session_transaction() as s: s.update(auth_version=0,issued_at=time.time(),uid=1,csrf='synthetic-admin',role='System Administrator',name='Synthetic admin')
        self.assertEqual(admin.post('/users',data={'csrf_token':'synthetic-admin','action':'reset','user_id':'8','password':'SyntheticReset!12345'}).status_code,302)
        self.assertEqual(self.client.get('/account').status_code,302)
        self.assertIn('/login',self.client.get('/account').location)
        self.actor(8); self.execute('UPDATE users SET must_change=0 WHERE id=8')
        # The old epoch must not become valid again after disable/enable.
        self.client.set_cookie('session',cookie)
        admin.post('/users',data={'csrf_token':'synthetic-admin','action':'deactivate','user_id':'8'})
        admin.post('/users',data={'csrf_token':'synthetic-admin','action':'activate','user_id':'8'})
        self.assertEqual(self.client.get('/tickets/101').status_code,302)

    def test_unsupported_methods_anonymous_and_no_database_mutation(self):
        c=self.m.db(); before='\n'.join(c.iterdump()); c.close()
        for rule,path in self.routes():
            for method in ('PUT','PATCH','DELETE'):
                self.assertEqual(self.client.open(path,method=method,data={'action':'delete','confirm':'1'}).status_code,405)
        c=self.m.db(); after='\n'.join(c.iterdump()); c.close()
        self.assertEqual(before,after)

    def test_team_and_board_actions_with_member_viewer_boundaries(self):
        self.actor(8)
        self.post('/space',action='team_create',name='Synthetic team')
        tid=self.rows("SELECT id FROM teams WHERE name='Synthetic team'")[0][0]
        path='/space/team/'+str(tid)
        bid=self.rows('SELECT id FROM boards WHERE team_id=?',(tid,))[0][0]
        board='/space/board/'+str(bid)
        self.post(path,action='add_member',user_id='4')
        self.assertEqual(self.rows('SELECT role FROM team_members WHERE team_id=? AND user_id=4',(tid,)),[('Member',)])
        self.actor(4)
        self.assertEqual(self.post(path,action='set_role',user_id='4',role='Lead').status_code,403)
        self.actor(9)
        self.assertEqual(self.client.get(board).status_code,200)
        self.assertEqual(self.post(board,action='board_rename',name='FORGED').status_code,403)
        self.actor(8)
        self.post(path,action='set_role',user_id='4',role='Lead')
        self.assertEqual(self.rows('SELECT role FROM team_members WHERE team_id=? AND user_id=4',(tid,)),[('Lead',)])
        self.execute("UPDATE users SET sector='Synthetic sector' WHERE id=3")
        self.post(path,action='add_sector',sector='Synthetic sector')
        self.assertEqual(len(self.rows('SELECT * FROM team_members WHERE team_id=? AND user_id=3',(tid,))),1)
        self.post(path,action='board_create',name='Synthetic extra board')
        self.post(path,action='board_archive',board_id='901',v='1')
        self.assertEqual(self.rows('SELECT archived FROM boards WHERE id=901'),[(0,)])
        self.post(path,action='board_archive',board_id=str(bid),v='1')
        self.assertEqual(self.rows('SELECT archived FROM boards WHERE id=?',(bid,)),[(1,)])
        self.post(path,action='team_update',name='Synthetic renamed team')
        self.assertEqual(self.rows('SELECT name FROM teams WHERE id=?',(tid,)),[('Synthetic renamed team',)])
        self.post(board,action='list_add',name='Synthetic list')
        lid=self.rows("SELECT id FROM board_lists WHERE board_id=? AND name='Synthetic list'",(bid,))[0][0]
        self.post(board,action='card_add',list_id=str(lid),title='Synthetic team card')
        kid=self.rows("SELECT id FROM cards WHERE title='Synthetic team card'")[0][0]
        self.post(board,action='card_update',card_id=str(kid),list_id='901',title='FORGED')
        self.assertEqual(self.rows('SELECT title FROM cards WHERE id=?',(kid,)),[('Synthetic team card',)])
        self.post(board,action='card_update',card_id=str(kid),list_id=str(lid),title='Synthetic updated card')
        self.assertEqual(self.rows('SELECT title FROM cards WHERE id=?',(kid,)),[('Synthetic updated card',)])
        self.post(board,action='board_rename',name='Synthetic renamed board')
        self.assertEqual(self.rows('SELECT name FROM boards WHERE id=?',(bid,)),[('Synthetic renamed board',)])
        self.post(board,action='card_delete',card_id=str(kid))
        self.post(board,action='list_delete',list_id=str(lid))
        self.assertEqual(self.rows('SELECT id FROM board_lists WHERE id=?',(lid,)),[])
        self.post(path,action='remove_member',user_id='4')
        self.assertEqual(self.rows('SELECT * FROM team_members WHERE team_id=? AND user_id=4',(tid,)),[])
        self.post(path,action='team_delete',confirm='1')
        self.assertEqual(self.rows('SELECT id FROM teams WHERE id=?',(tid,)),[])
        self.assertEqual(self.rows('SELECT id FROM boards WHERE team_id=?',(tid,)),[])

    def test_acceptance_auditor_cannot_create_ticket(self):
        """Regression: read-only Auditor currently creates tickets."""
        self.actor(9)
        response=self.post('/tickets/new',type='Service Request',priority='Medium',title='Synthetic auditor mutation',description='Synthetic only')
        self.assertEqual(response.status_code,403)

    def seed_asset_scope(self):
        for aid,unit,owner in ((201,2,8),(202,6,99),(203,None,None)):
            self.execute("INSERT INTO assets(id,name,unit_id,owner_id,structure) VALUES(?,?,?,?,?)",(aid,'ASSET_SECRET_'+str(aid),unit,owner,'Same structure'))
        self.execute('UPDATE services SET unit_id=2 WHERE id=1')
        self.execute('UPDATE services SET unit_id=6 WHERE id=2')

    def test_assets_read_scope_and_dashboard_count_in_both_modes(self):
        from flask import template_rendered
        self.seed_asset_scope()
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            for uid in range(1,10):
                self.actor(uid)
                contexts=[]
                def capture(sender,template,context,**extra): contexts.append(context)
                with template_rendered.connected_to(capture,self.m.app):
                    response=self.client.get('/assets')
                    self.assertEqual(response.status_code,200)
                    self.client.get('/')
                with self.subTest(mode=mode,uid=uid):
                    self.assertEqual([r['id'] for r in contexts[0]['assets']],[203,202,201] if uid==1 else [201])
                    self.assertEqual(contexts[1]['asset_count'],3 if uid==1 else 1)
                    if uid!=1:
                        self.assertNotIn(b'ASSET_SECRET_202',response.data)
                        self.assertNotIn(b'FOREIGN_USER',response.data)
                        self.assertNotIn(2,[s['id'] for s in contexts[0]['services']])

    def test_assets_cross_unit_update_delete_create_denied_without_writes(self):
        self.seed_asset_scope()
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            for uid in range(2,10):
                self.actor(uid)
                for aid in (202,203,9999):
                    for action in ('update','delete'):
                        before=self.rows('SELECT * FROM assets ORDER BY id')
                        with self.subTest(mode=mode,uid=uid,aid=aid,action=action):
                            self.assertEqual(self.post('/assets',action=action,asset_id=str(aid),name='FORGED',confirm='1',unit_id='2').status_code,403)
                            self.assertEqual(self.rows('SELECT * FROM assets ORDER BY id'),before)
            self.actor(5)
            for fields in (dict(unit_id='6'),dict(owner_id='99'),dict(service_id='2')):
                before=self.rows('SELECT * FROM assets ORDER BY id')
                self.assertEqual(self.post('/assets',name='FORGED',**fields).status_code,403)
                self.assertEqual(self.rows('SELECT * FROM assets ORDER BY id'),before)

    def test_assets_local_write_capability_and_system_global_access(self):
        self.seed_asset_scope()
        for uid in (2,3,5):
            self.actor(uid)
            self.assertEqual(self.post('/assets',name='Synthetic local '+str(uid),owner_id='8',service_id='1').status_code,302)
            aid=self.rows('SELECT id FROM assets WHERE name=?',('Synthetic local '+str(uid),))[0][0]
            self.assertEqual(self.rows('SELECT unit_id FROM assets WHERE id=?',(aid,)),[(2,)])
            self.assertEqual(self.post('/assets',action='update',asset_id=str(aid),name='Synthetic local edited').status_code,302)
            self.assertEqual(self.post('/assets',action='delete',asset_id=str(aid),confirm='1').status_code,302)
            self.assertEqual(self.rows('SELECT id FROM assets WHERE id=?',(aid,)),[])
        self.execute('UPDATE users SET can_infra=1 WHERE id=4'); self.actor(4)
        self.assertEqual(self.post('/assets',action='update',asset_id='201',name='Synthetic capability edit').status_code,302)
        self.assertEqual(self.post('/assets',action='update',asset_id='202',name='FORGED').status_code,403)
        self.actor(1)
        self.assertEqual(self.post('/assets',action='update',asset_id='202',name='Synthetic global edit').status_code,302)
        self.assertEqual(self.post('/assets',action='delete',asset_id='202',confirm='1').status_code,302)
        self.assertEqual(self.rows('SELECT id FROM assets WHERE id=202'),[])

    def test_assets_rebinding_missing_scope_and_subtree(self):
        self.seed_asset_scope(); self.actor(5)
        for fields in (dict(unit_id='6'),dict(owner_id='99'),dict(service_id='2')):
            before=self.rows('SELECT * FROM assets WHERE id=201')
            self.assertEqual(self.post('/assets',action='update',asset_id='201',name='FORGED',**fields).status_code,403)
            self.assertEqual(self.rows('SELECT * FROM assets WHERE id=201'),before)
        self.execute("INSERT INTO assets(id,name,unit_id) VALUES(204,'Synthetic descendant',3)")
        self.assertNotIn(b'Synthetic descendant',self.client.get('/assets').data)
        self.execute('UPDATE users SET org_head=1 WHERE id=5')
        self.assertIn(b'Synthetic descendant',self.client.get('/assets').data)
        self.assertEqual(self.post('/assets',action='update',asset_id='204',name='Synthetic scoped child').status_code,302)
        self.execute('UPDATE users SET org_unit_id=NULL WHERE id=5')
        self.assertNotIn(b'ASSET_SECRET_',self.client.get('/assets').data)
        self.assertEqual(self.post('/assets',name='FORGED').status_code,403)
        self.execute("UPDATE users SET role='Unexpected',can_infra=1,org_unit_id=2 WHERE id=5")
        self.assertEqual(self.post('/assets',name='FORGED').status_code,403)

    def test_assets_malformed_duplicate_and_conflicting_links(self):
        from werkzeug.datastructures import MultiDict
        self.seed_asset_scope(); self.actor(5)
        before=self.rows('SELECT * FROM assets ORDER BY id')
        for fields in (dict(asset_id='bad',action='delete'),dict(owner_id='99999'),dict(service_id='not-a-number'),dict(unit_id='-1')):
            self.assertEqual(self.post('/assets',name='FORGED',**fields).status_code,400)
        self.assertEqual(self.client.post('/assets',data=MultiDict([('csrf_token','synthetic-csrf'),('name','FORGED'),('unit_id','2'),('unit_id','6')])).status_code,400)
        self.assertEqual(self.rows('SELECT * FROM assets ORDER BY id'),before)

        self.actor(1)
        self.assertEqual(self.post('/assets',name='FORGED',owner_id='8',service_id='2').status_code,400)
        self.assertEqual(self.rows('SELECT * FROM assets ORDER BY id'),before)

    def test_asset_admin_classification_transfer_and_persisted_scope(self):
        self.seed_asset_scope(); self.actor(1)
        self.assertEqual(self.post('/assets',action='update',asset_id='203',name='Synthetic classified',unit_id='2').status_code,302)
        self.assertEqual(self.rows('SELECT unit_id FROM assets WHERE id=203'),[(2,)])
        self.actor(5)
        self.assertIn(b'Synthetic classified',self.client.get('/assets').data)
        self.actor(1)
        self.assertEqual(self.post('/assets',action='update',asset_id='203',name='Synthetic transferred',unit_id='6',owner_id='99').status_code,302)
        self.actor(5)
        self.assertNotIn(b'Synthetic transferred',self.client.get('/assets').data)
        self.assertEqual(self.post('/assets',action='delete',asset_id='203',confirm='1').status_code,403)
        # Mutating owner metadata never silently moves an explicitly classified asset.
        self.execute('UPDATE users SET org_unit_id=2 WHERE id=99')
        self.assertNotIn(b'Synthetic transferred',self.client.get('/assets').data)
        self.assertEqual(self.rows('SELECT unit_id FROM assets WHERE id=203'),[(6,)])

    def test_requester_routing_override_and_foreign_service_denied(self):
        self.seed_asset_scope(); self.actor(8)
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            for fields in (dict(unit_id='6'),dict(unit_id='2'),dict(unit_id='not-a-unit'),dict(service_id='2'),dict(assignee_id='99'),dict(chain_users='99')):
                before=self.rows('SELECT * FROM tickets ORDER BY id')
                self.assertEqual(self.post('/tickets/new',type='Service Request',priority='Medium',title='FORGED',description='Synthetic only',**fields).status_code,400 if fields.get('unit_id')=='not-a-unit' else 403)
                self.assertEqual(self.rows('SELECT * FROM tickets ORDER BY id'),before)
        self.assertEqual(self.rows("SELECT id FROM timeline WHERE details LIKE '%FORGED%'"),[])
        self.assertEqual(self.rows('SELECT * FROM ticket_steps'),[])

    def test_requester_intake_ignores_service_mapping_and_structure(self):
        self.seed_asset_scope(); self.actor(8)
        self.execute("UPDATE settings SET value='3' WHERE key='intake_unit_id'")
        for service in ('','1','3'):
            title='Synthetic intake '+service
            self.assertEqual(self.post('/tickets/new',type='Service Request',priority='Medium',title=title,description='Synthetic only',service_id=service,structure='FORGED STRUCTURE',requester_id='99',created_by='99').status_code,302)
            self.assertEqual(self.rows('SELECT unit_id,structure,requester_id,created_by,assignee_id FROM tickets WHERE title=?',(title,)),[(3,'Unit A',8,8,None)])
        form=self.client.get('/tickets/new')
        self.assertNotIn(b'name="unit_id"',form.data)
        from flask import template_rendered
        contexts=[]
        def capture(sender,template,context,**extra): contexts.append(context)
        with template_rendered.connected_to(capture,self.m.app): self.client.get('/tickets/new')
        self.assertNotIn(2,[s['id'] for s in contexts[0]['services']])
        self.assertEqual(self.rows('SELECT * FROM ticket_steps'),[])

    def test_requester_invalid_config_and_duplicate_ids_fail_before_insert(self):
        from werkzeug.datastructures import MultiDict
        self.seed_asset_scope(); self.actor(8)
        fields=dict(type='Service Request',priority='Medium',title='FORGED',description='Synthetic only')
        before=self.rows('SELECT * FROM tickets ORDER BY id')
        for service in ('999999','bad','-1'):
            self.assertEqual(self.post('/tickets/new',service_id=service,**fields).status_code,400)
        data=MultiDict([('csrf_token','synthetic-csrf'),*fields.items(),('unit_id',''),('unit_id','6')])
        self.assertEqual(self.client.post('/tickets/new',data=data).status_code,400)
        for intake in ('','999999','malformed'):
            self.execute("UPDATE settings SET value=? WHERE key='intake_unit_id'",(intake,))
            self.assertEqual(self.post('/tickets/new',**fields).status_code,503)
        self.assertEqual(self.rows('SELECT * FROM tickets ORDER BY id'),before)

    def test_unassigned_requester_uses_intake_and_staff_explicit_routing_remains(self):
        self.seed_asset_scope(); self.execute('UPDATE users SET org_unit_id=NULL WHERE id=8'); self.actor(8)
        self.assertEqual(self.post('/tickets/new',type='Service Request',priority='Medium',title='Synthetic unassigned',description='Synthetic',service_id='3').status_code,302)
        self.assertEqual(self.rows("SELECT unit_id FROM tickets WHERE title='Synthetic unassigned'"),[(3,)])
        self.assertEqual(self.post('/tickets/new',type='Service Request',priority='Medium',title='FORGED',description='Synthetic',service_id='1').status_code,403)
        self.actor(1)
        self.assertEqual(self.post('/tickets/new',type='Service Request',priority='Medium',title='Synthetic staff route',description='Synthetic',unit_id='6',service_id='2').status_code,302)
        self.assertEqual(self.rows("SELECT unit_id FROM tickets WHERE title='Synthetic staff route'"),[(6,)])

    def test_requester_assigned_task_cannot_mutate(self):
        c=self.m.db()
        c.execute('INSERT OR IGNORE INTO task_assignees VALUES(101,8)')
        c.commit(); c.close()
        self.actor(8)
        self.assertEqual(self.post('/tasks/101/do',action='start').status_code,403)
        self.assertEqual(self.post('/tasks/101/complete',completion_notes='synthetic completion').status_code,403)
        c=self.m.db()
        self.assertEqual(c.execute('SELECT status FROM tasks WHERE id=101').fetchone()[0],'Open')
        c.close()

    def test_central_admin_user_cross_scope(self):
        self.actor(5)
        self.assertEqual(self.post('/users',action='deactivate',user_id='99').status_code,403)
        c=self.m.db()
        self.assertEqual(c.execute('SELECT active FROM users WHERE id=99').fetchone()[0],1)
        c.close()

    def test_unknown_role_cannot_read_own_ticket(self):
        c=self.m.db(); c.execute("UPDATE users SET role='Unexpected' WHERE id=8"); c.commit(); c.close()
        try:
            self.actor(8)
            self.assertEqual(self.client.get('/tickets/101').status_code,403)
        finally:
            c=self.m.db(); c.execute("UPDATE users SET role='Requester' WHERE id=8"); c.commit(); c.close()

    def test_dashboard_activity_and_service_counts_scoped(self):
        from flask import template_rendered
        contexts=[]
        def capture(sender, template, context, **extra): contexts.append(context)
        self.actor(8)
        with template_rendered.connected_to(capture,self.m.app):
            self.assertEqual(self.client.get('/').status_code,200)
            self.assertEqual(self.client.get('/services').status_code,200)
        self.assertFalse(any(r['ticket_id']==102 for r in contexts[0]['activity']))
        for ctx in contexts:
            self.assertEqual(next(s['open_count'] for s in ctx['services'] if s['id']==1),0)

    def test_ticket_role_matrix_and_technician_assignment(self):
        for uid in range(1,10):
            self.actor(uid)
            for tid in (101,102):
                allowed=uid==1 or (tid==101 and uid in (2,3,5,6,7,8))
                with self.subTest(uid=uid,tid=tid):
                    self.assertEqual(self.client.get('/tickets/'+str(tid)).status_code,200 if allowed else 403)
        c=self.m.db(); c.execute('INSERT INTO task_assignees VALUES(102,4)'); c.commit(); c.close()
        self.actor(4)
        self.assertEqual(self.client.get('/tickets/102').status_code,200)
        self.assertEqual(self.post('/tasks/102/do',action='start').status_code,302)
        self.assertEqual(self.post('/tasks/102/complete',completion_notes='Synthetic completed work').status_code,302)
        c=self.m.db(); self.assertEqual(c.execute('SELECT status FROM tasks WHERE id=102').fetchone()[0],'Completed'); c.close()

    def test_role_guards_and_stale_session(self):
        for uid in range(1,10):
            self.actor(uid)
            for path,allowed in (('/users',uid in (1,5)),('/admin',uid==1),('/audit',uid in (1,5,7,9)),('/org',uid in (1,5,7,9))):
                with self.subTest(uid=uid,path=path):
                    self.assertEqual(self.client.get(path).status_code,200 if allowed else 403)

    def test_legacy_get_matrix(self):
        c=self.m.db(); c.execute("UPDATE settings SET value='legacy' WHERE key='visibility_mode'"); c.commit(); c.close()
        self.test_get_matrix_all_roles()

    def test_central_org_cross_scope_and_mode_downgrade(self):
        self.actor(5)
        for data in (dict(action='unit_rename',id='6',name='ATTACK'),dict(action='settings',mode='legacy'),dict(action='unit_move',id='2',parent_id='6')):
            self.assertEqual(self.post('/org',**data).status_code,403)
        c=self.m.db()
        self.assertEqual(c.execute("SELECT value FROM settings WHERE key='visibility_mode'").fetchone()[0],'org')
        c.close()

    def test_workload_does_not_count_hidden_work(self):
        from flask import template_rendered
        contexts=[]
        def capture(sender,template,context,**extra): contexts.append(context)
        c=self.m.db()
        c.execute('UPDATE tickets SET assignee_id=3 WHERE id=102')
        c.execute('INSERT INTO task_assignees VALUES(102,3)')
        c.execute('UPDATE cards SET assignee_id=3 WHERE id=901')
        c.commit(); c.close()
        self.actor(8)
        with template_rendered.connected_to(capture,self.m.app): self.client.get('/reports')
        row=next(r for r in contexts[0]['workload'] if r['id']==3)
        self.assertEqual((row['tk'],row['ts'],row['cd'],row['total']),(0,0,0,0))

    def test_allowed_administrative_actions(self):
        self.actor(1)
        self.assertEqual(self.post('/services',action='rename_service',service_id='1',name='Synthetic renamed service').status_code,302)
        self.assertEqual(self.post('/assets',name='Synthetic asset').status_code,302)
        self.actor(5)
        self.assertEqual(self.post('/org',action='unit_rename',id='2',name='Synthetic unit').status_code,302)
        self.assertEqual(self.post('/directory',user_id='8',full_name='Synthetic updated requester').status_code,302)
        c=self.m.db()
        self.assertEqual(c.execute('SELECT name FROM services WHERE id=1').fetchone()[0],'Synthetic renamed service')
        self.assertEqual(c.execute('SELECT name FROM org_units WHERE id=2').fetchone()[0],'Synthetic unit')
        self.assertEqual(c.execute('SELECT full_name FROM users WHERE id=8').fetchone()[0],'Synthetic updated requester')
        c.close()
