"""P1-03 integration/fault contracts, all against temporary synthetic databases."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from flask import Response, has_request_context

class DatabaseContracts(unittest.TestCase):
    def setUp(self):
        from application import create_app
        self.tmp=tempfile.TemporaryDirectory(prefix='openitsm-p103-')
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.app=create_app(dict(ITSM_ENV='test',ITSM_DB=str(self.folder/'one.sqlite'),
            ITSM_SECRET_KEY='synthetic-p103-key-'*4,ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345',
            ITSM_BACKUP='0',ITSM_TLS='1',ITSM_HTTPS='0',TESTING=True),environ={},backup_dir=self.folder/'backups')
        self.runtime=self.app.extensions['openitsm']['runtime']
        self.db=self.app.extensions['openitsm']['database']

    def rows(self, query, args=(), path=None):
        c=sqlite3.connect(path or self.folder/'one.sqlite')
        try: return c.execute(query,args).fetchall()
        finally: c.close()

    def post(self, client=None, **data):
        client=client or self.app.test_client()
        with client.session_transaction() as s: s.update(csrf='synthetic-p103',uid=1)
        return client.post('/contract',data=dict(csrf_token='synthetic-p103',**data))

    def route(self, function):
        self.app.add_url_rule('/contract','contract',function,methods=['POST'])

    def test_raw_background_connections_have_explicit_commit_and_close(self):
        self.assertFalse(self.db.initializing); self.assertEqual(self.db.startup_connections,[])
        with self.app.app_context():
            raw=self.db.connection()
            self.assertIsInstance(raw,sqlite3.Connection)
            self.assertEqual(raw.execute('PRAGMA foreign_keys').fetchone()[0],1)
            self.assertEqual(raw.execute('PRAGMA journal_mode').fetchone()[0],'wal')
            raw.execute("INSERT INTO support_groups(name) VALUES('synthetic raw rollback')")
            raw.close()
            self.assertEqual(self.rows("SELECT name FROM support_groups WHERE name LIKE 'synthetic raw%'"),[])
            raw=self.db.connection()
            raw.execute("INSERT INTO support_groups(name) VALUES('synthetic raw commit')")
            raw.commit(); raw.close()
            self.assertEqual(self.rows("SELECT name FROM support_groups WHERE name LIKE 'synthetic raw%'"),[('synthetic raw commit',)])

    def test_request_proxy_defers_commit_close_and_closes_at_teardown(self):
        captured=[]; observations=[]
        def handler():
            proxy=self.db.connection(); captured.append(proxy)
            self.assertIs(proxy,self.db.connection())
            proxy.execute("INSERT INTO support_groups(name) VALUES('synthetic deferred')")
            proxy.commit(); proxy.close()
            self.assertEqual(self.rows("SELECT name FROM support_groups WHERE name='synthetic deferred'"),[])
            self.db.after_commit(lambda:observations.append(self.rows("SELECT name FROM support_groups WHERE name='synthetic deferred'")))
            return '',201
        self.route(handler); self.assertEqual(self.post().status_code,201)
        self.assertEqual(observations,[[('synthetic deferred',)]])
        with self.assertRaises(sqlite3.ProgrammingError): captured[0].raw.execute('SELECT 1')

    def test_response_status_controls_business_audit_and_callback_commit(self):
        events=[]
        def handler():
            from flask import request
            code=int(request.form['status'])
            self.db.connection().execute('INSERT INTO support_groups(name) VALUES(?)',('synthetic status '+str(code),))
            self.runtime.audit('SyntheticBusiness','User',1,new=str(code))
            self.runtime.audit('AccessDenied','User',1,new=str(code))
            self.db.after_commit(lambda:events.append(code))
            return '',code
        self.route(handler)
        for code in (200,302,400,403,500):
            with self.subTest(status=code):
                self.assertEqual(self.post(status=str(code)).status_code,code)
                self.assertEqual(len(self.rows('SELECT name FROM support_groups WHERE name=?',('synthetic status '+str(code),))),int(code<400))
                actions=self.rows('SELECT action FROM audit WHERE new_value=? ORDER BY id',(str(code),))
                self.assertEqual(actions,[('SyntheticBusiness',),('AccessDenied',)] if code<400 else [('AccessDenied',)])
        self.assertEqual(events,[200,302])

    def test_commit_failure_and_security_replay_failure_clear_session_without_dispatch(self):
        events=[]; status=[201]
        def handler():
            self.db.connection().execute("INSERT INTO support_groups(name) VALUES('synthetic failed commit')")
            self.runtime.audit('AccessDenied','User',1,new='synthetic replay')
            self.db.after_commit(lambda:events.append('forbidden'))
            return '',status[0]
        self.route(handler)
        for code in (201,403):
            status[0]=code; client=self.app.test_client()
            with patch.object(self.runtime,'commit_request_connection',side_effect=sqlite3.OperationalError('Synthetic storage failure')),self.assertLogs(self.app.logger,level='ERROR'):
                self.assertEqual(self.post(client).status_code,503)
            self.assertEqual(events,[])
            self.assertEqual(self.rows("SELECT name FROM support_groups WHERE name='synthetic failed commit'"),[])
            self.assertEqual(self.rows("SELECT action FROM audit WHERE new_value='synthetic replay'"),[])
            with client.session_transaction() as session: self.assertNotIn('uid',session)
        status[0]=201; self.assertEqual(self.post().status_code,201)
        self.assertEqual(events,['forbidden'])

    def test_explicit_rollback_discards_prior_audit_and_callbacks(self):
        events=[]
        def handler():
            self.runtime.audit('AccessDenied','User',1,new='synthetic rolled back')
            self.db.after_commit(lambda:events.append('old'))
            self.db.connection().rollback()
            self.db.connection().execute("INSERT INTO support_groups(name) VALUES('synthetic after rollback')")
            self.db.after_commit(lambda:events.append('new'))
            return '',201
        self.route(handler); self.assertEqual(self.post().status_code,201)
        self.assertEqual(events,['new'])
        self.assertEqual(self.rows("SELECT action FROM audit WHERE new_value='synthetic rolled back'"),[])
        self.assertEqual(self.rows("SELECT name FROM support_groups WHERE name='synthetic after rollback'"),[('synthetic after rollback',)])

    def test_callback_exception_does_not_undo_commit_or_skip_later_callback(self):
        events=[]
        def fail(): raise RuntimeError('Synthetic dispatch failure')
        def handler():
            self.db.connection().execute("INSERT INTO support_groups(name) VALUES('synthetic callback')")
            self.db.after_commit(fail)
            self.db.after_commit(lambda:events.append(self.rows("SELECT name FROM support_groups WHERE name='synthetic callback'")))
            return '',201
        self.route(handler)
        with self.assertLogs(self.app.logger,level='ERROR'): self.assertEqual(self.post().status_code,201)
        self.assertEqual(events,[[('synthetic callback',)]])

    def test_callback_without_database_runs_once_and_only_on_success(self):
        events=[]; code=[201]
        def handler():
            self.db.after_commit(lambda:events.append('once'))
            self.assertIsNone(self.db._state().proxy)
            return self.db.finish(Response(status=code[0]))
        self.route(handler)
        self.assertEqual(self.post().status_code,201)
        self.assertEqual(events,['once'])
        code[0]=403; self.assertEqual(self.post().status_code,403)
        self.assertEqual(events,['once'])

    def test_real_background_dispatch_has_clean_context_and_committed_visibility(self):
        done=threading.Event(); observed=[]; failures=[]
        def worker():
            try:
                observed.append(has_request_context())
                c=self.runtime.db()
                try:
                    observed.append(isinstance(c,sqlite3.Connection))
                    observed.append(c.execute("SELECT name FROM support_groups WHERE name='synthetic thread'").fetchone()[0])
                finally: c.close()
            except Exception as error: failures.append(repr(error))
            finally: done.set()
        def handler():
            self.db.connection().execute("INSERT INTO support_groups(name) VALUES('synthetic thread')")
            self.db.dispatch_after_commit(worker)
            self.assertFalse(done.is_set())
            return '',201
        self.route(handler); self.assertEqual(self.post().status_code,201)
        self.assertTrue(done.wait(5)); self.assertEqual(failures,[])
        self.assertEqual(observed,[False,True,'synthetic thread'])

    def test_concurrent_requests_use_separate_connections_and_callbacks(self):
        barrier=threading.Barrier(4); lock=threading.Lock(); raws=[]; observations=[]
        def handler():
            from flask import request
            marker='synthetic concurrent '+request.form['marker']
            raw=self.db.connection()
            with lock: raws.append(raw.raw)
            barrier.wait(timeout=10)
            raw.execute('INSERT INTO support_groups(name) VALUES(?)',(marker,))
            self.runtime.audit('SyntheticConcurrent','User',1,new=marker)
            self.db.after_commit(lambda:observations.append(self.rows('SELECT name FROM support_groups WHERE name=?',(marker,))))
            return '',201
        self.route(handler)
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses=list(pool.map(lambda i:self.post(self.app.test_client(),marker=str(i)).status_code,range(4)))
        self.assertEqual(statuses,[201]*4); self.assertEqual(len({id(c) for c in raws}),4)
        self.assertEqual(len(observations),4); self.assertTrue(all(len(r)==1 for r in observations))
        self.assertEqual(len(self.rows("SELECT name FROM support_groups WHERE name LIKE 'synthetic concurrent %'")),4)
        self.assertEqual(len(self.rows("SELECT id FROM audit WHERE action='SyntheticConcurrent'")),4)
        for raw in raws:
            with self.assertRaises(sqlite3.ProgrammingError): raw.execute('SELECT 1')

    def test_nested_same_application_requests_do_not_share_state_or_close_outer(self):
        events=[]
        with self.app.test_request_context('/outer'):
            outer=self.db.connection(); self.db.after_commit(lambda:events.append('outer'))
            with self.app.test_request_context('/inner'):
                inner=self.db.connection(); self.assertIsNot(inner,outer)
                inner.execute("INSERT INTO support_groups(name) VALUES('synthetic inner')")
                self.db.after_commit(lambda:events.append('inner'))
                self.db.finish(Response(status=201))
            with self.assertRaises(sqlite3.ProgrammingError): inner.raw.execute('SELECT 1')
            self.assertIs(self.db.connection(),outer)
            self.assertEqual(events,['inner'])
            outer.execute("INSERT INTO support_groups(name) VALUES('synthetic outer')")
            self.db.finish(Response(status=201))
        self.assertEqual(events,['inner','outer'])
        with self.assertRaises(sqlite3.ProgrammingError): outer.raw.execute('SELECT 1')

    def test_other_app_and_factory_startup_cannot_reuse_active_request(self):
        from application import create_app
        events=[]
        with self.app.test_request_context('/outer'):
            outer=self.db.connection(); outer.execute("INSERT INTO support_groups(name) VALUES('synthetic only A')")
            self.db.after_commit(lambda:events.append('A'))
            # Construction is raw/schema work even inside an existing request.
            other=create_app(dict(ITSM_ENV='test',ITSM_DB=str(self.folder/'two.sqlite'),
                ITSM_SECRET_KEY='synthetic-other-app-'*4,ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345',
                ITSM_BACKUP='0',TESTING=True),environ={},backup_dir=self.folder/'other-backups')
            second=other.extensions['openitsm']['database']
            with self.assertRaises(RuntimeError): second.connection()
            with other.test_request_context('/inner'):
                with self.assertRaises(RuntimeError): self.db.connection()
                second.connection().execute("INSERT INTO support_groups(name) VALUES('synthetic only B')")
                second.after_commit(lambda:events.append('B')); second.finish(Response(status=201))
            self.assertIs(self.db.connection(),outer); self.assertEqual(events,['B'])
            self.db.finish(Response(status=201))
        self.assertEqual(events,['B','A'])
        self.assertEqual(self.rows("SELECT name FROM support_groups WHERE name LIKE 'synthetic only%'"),[('synthetic only A',)])
        self.assertEqual(self.rows("SELECT name FROM support_groups WHERE name LIKE 'synthetic only%'",path=self.folder/'two.sqlite'),[('synthetic only B',)])

    def test_connection_configuration_failure_closes_real_sqlite_handle(self):
        import database
        closed=[]; real_connect=sqlite3.connect
        class Broken(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if sql=='PRAGMA journal_mode=WAL': raise sqlite3.OperationalError('Synthetic WAL refusal')
                return super().execute(sql,*args,**kwargs)
            def close(self):
                closed.append(True); return super().close()
        def connect(*args,**kwargs): return real_connect(*args,**kwargs,factory=Broken)
        with self.app.test_request_context('/fault'),patch.object(database.sqlite3,'connect',side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError): self.db.connection()
        self.assertEqual(closed,[True])
        self.assertEqual(self.rows('PRAGMA integrity_check'),[('ok',)])

    def test_exception_teardown_closes_even_if_explicit_rollback_fails(self):
        import database
        closed=[]; real_connect=sqlite3.connect
        class BrokenRollback(sqlite3.Connection):
            def rollback(self): raise sqlite3.OperationalError('Synthetic rollback failure')
            def close(self): closed.append(True); return super().close()
        def connect(*args,**kwargs): return real_connect(*args,**kwargs,factory=BrokenRollback)
        def handler():
            self.db.connection().execute("INSERT INTO support_groups(name) VALUES('synthetic exception')")
            self.db.after_commit(lambda:self.fail('No callback after exception'))
            raise RuntimeError('Synthetic handler failure')
        self.route(handler)
        with patch.object(database.sqlite3,'connect',side_effect=connect),self.assertLogs(self.app.logger,level='ERROR'):
            with self.assertRaisesRegex(RuntimeError,'Synthetic handler failure'): self.post()
        self.assertEqual(closed,[True])
        self.assertEqual(self.rows("SELECT name FROM support_groups WHERE name='synthetic exception'"),[])

    def test_database_module_import_has_no_db_or_worker_side_effect(self):
        with tempfile.TemporaryDirectory(prefix='openitsm-p103-import-') as tmp:
            root=Path(__file__).resolve().parents[1]
            code="""import sqlite3,threading,os
from pathlib import Path
def forbidden(*a,**k): raise AssertionError('Import side effect')
sqlite3.connect=forbidden
threading.Thread.start=forbidden
before=dict(os.environ)
import database
assert before==dict(os.environ)
assert not list(Path.cwd().iterdir())
"""
            result=subprocess.run([sys.executable,'-c',code],cwd=tmp,
                env=dict(os.environ,PYTHONPATH=str(root)),capture_output=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
