"""P1-02 factory contracts using only temporary synthetic instances/subprocesses."""
import json
import os
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]

class FactoryTests(unittest.TestCase):
    def settings(self, folder, name='one', **extra):
        values=dict(ITSM_ENV='test',ITSM_DB=str(Path(folder)/(name+'.sqlite')),
            ITSM_SECRET_KEY=('synthetic-'+name+'-')*8,
            ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345',ITSM_BACKUP='0',
            ITSM_TLS='1',ITSM_HTTPS='0',ITSM_DEBUG='0',
            ITSM_ALLOWED_HOSTS='localhost,127.0.0.1',TESTING=True)
        values.update(extra)
        return values

    def make(self, folder, name='one', **extra):
        from application import create_app
        return create_app(self.settings(folder,name,**extra),environ={},
            backup_dir=Path(folder)/(name+'-backups'))

    def test_helper_imports_have_no_storage_or_worker_side_effects(self):
        with tempfile.TemporaryDirectory(prefix='openitsm-p102-import-') as tmp:
            code="""import sqlite3,threading,os
from pathlib import Path
def forbidden(*a,**k): raise AssertionError('Import side effect')
sqlite3.connect=forbidden
threading.Thread.start=forbidden
before=dict(os.environ)
import application,app_config,authorization,org,space,chat
assert before==dict(os.environ)
assert not list(Path.cwd().iterdir())
"""
            env=dict(os.environ,PYTHONPATH=str(ROOT),ITSM_DB=str(Path(tmp)/'forbidden.sqlite'),ITSM_BACKUP='1')
            env.pop('ITSM_SECRET_KEY',None)
            r=subprocess.run([sys.executable,'-c',code],cwd=tmp,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_instances_isolate_database_secrets_routes_and_concurrent_requests(self):
        with tempfile.TemporaryDirectory(prefix='openitsm-p102-pair-') as tmp:
            a=self.make(tmp,'one'); b=self.make(tmp,'two')
            ra=a.extensions['openitsm']['runtime']; rb=b.extensions['openitsm']['runtime']
            self.assertIsNot(ra,rb); self.assertIsNot(ra.FAILS,rb.FAILS); self.assertIsNot(ra.ORG,rb.ORG)
            self.assertNotEqual(a.secret_key,b.secret_key)
            self.assertEqual([(str(r),r.endpoint,r.methods) for r in a.url_map.iter_rules()],
                             [(str(r),r.endpoint,r.methods) for r in b.url_map.iter_rules()])
            ca=ra.db(); ca.execute("UPDATE users SET full_name='ONLY INSTANCE A' WHERE id=1"); ca.commit(); ca.close()
            cb=rb.db(); self.assertNotEqual(cb.execute('SELECT full_name FROM users WHERE id=1').fetchone()[0],'ONLY INSTANCE A'); cb.close()
            clients=[a.test_client(),b.test_client()]
            def login(pair):
                app,client=pair
                client.get('/login')
                with client.session_transaction() as s: token=s['csrf']
                r=client.post('/login',data=dict(csrf_token=token,username='admin',password='SyntheticOnly!12345'))
                return r.status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(login,zip((a,b),clients))),[302,302])
            cookie=clients[0].get_cookie('session').value
            other=b.test_client(); other.set_cookie('session',cookie)
            self.assertIn('/login',other.get('/tickets').location)
            encrypted=ra.enc_secret('Synthetic SMTP secret')
            self.assertEqual(ra.dec_secret(encrypted),'Synthetic SMTP secret')
            self.assertEqual(rb.dec_secret(encrypted),'')
            self.assertFalse(a.extensions['openitsm']['workers_started'])
            self.assertFalse(b.extensions['openitsm']['workers_started'])

    def test_configuration_is_snapshot_not_process_global(self):
        from application import create_app
        with tempfile.TemporaryDirectory(prefix='openitsm-p102-config-') as tmp:
            supplied=self.settings(tmp)
            before=dict(os.environ)
            app=create_app(supplied,environ={},backup_dir=Path(tmp)/'backups')
            self.assertEqual(dict(os.environ),before)
            runtime=app.extensions['openitsm']['runtime']
            supplied['ITSM_DB']=str(Path(tmp)/'forged.sqlite')
            with patch.dict(os.environ,ITSM_DB=supplied['ITSM_DB'],ITSM_SECRET_KEY='foreign-secret-'*4,ITSM_ENV='production'):
                c=runtime.db(); self.assertEqual(c.execute('SELECT count(*) FROM users').fetchone()[0],1); c.close()
                self.assertNotEqual(app.secret_key,os.environ['ITSM_SECRET_KEY'])
            self.assertFalse(Path(supplied['ITSM_DB']).exists())
            with self.assertRaises(TypeError): app.extensions['openitsm']['settings']['ITSM_DB']='forged'
    def test_invalid_production_configuration_refuses_before_files_even_testing(self):
        from application import create_app
        with tempfile.TemporaryDirectory(prefix='openitsm-p102-invalid-') as tmp:
            for values in ({'ITSM_ENV':'production'}, {'ITSM_ENV':'Production'},
                           {'ITSM_BACKUP':'maybe'}, {'PORT':'bad'}, {'ITSM_THREADS':'0'},
                           {'ITSM_SECRET_KEY':'short'}):
                config=self.settings(tmp,**values)
                with self.subTest(values=values):
                    with self.assertRaises(RuntimeError):
                        create_app(config,environ={},backup_dir=Path(tmp)/'backups',secret_path=Path(tmp)/'secret.key')
                    self.assertEqual(list(Path(tmp).iterdir()),[])
            with self.assertRaises(ValueError): create_app({'SECRET_KEY':'override'},environ={})

    def test_production_smtp_and_cookies_keep_snapshot_guards(self):
        from application import create_app
        from phase0_runtime_cases import certificate
        with tempfile.TemporaryDirectory(prefix='openitsm-p102-production-') as tmp:
            cert,key=certificate(tmp)
            app=self.make(tmp,ITSM_ENV='production',ITSM_TLS='1',ITSM_HTTPS='1',ITSM_CERT=cert,ITSM_KEY=key)
            runtime=app.extensions['openitsm']['runtime']
            self.assertTrue(app.config['SESSION_COOKIE_SECURE'])
            with patch.dict(os.environ,ITSM_ENV='development'):
                response=app.test_client().get('/login',base_url='https://localhost')
                self.assertIn('Strict-Transport-Security',response.headers)
                self.assertIn('Secure',response.headers['Set-Cookie'])
                self.assertEqual(app.test_client().get('/login',base_url='https://foreign.invalid').status_code,400)
                c=runtime.db()
                for k,v in (('smtp_host','localhost'),('smtp_security','none'),('smtp_verify','0')):
                    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,v))
                c.commit(); c.close()
                with patch.object(runtime.smtplib,'SMTP') as smtp:
                    self.assertFalse(runtime.send_email('synthetic@example.invalid','Synthetic','Body')[0])
                    smtp.assert_not_called()

    def test_backups_are_explicit_idempotent_and_after_complete_schema(self):
        from application import create_app,start_background_services
        with tempfile.TemporaryDirectory(prefix='openitsm-p102-workers-') as tmp:
            app=create_app(self.settings(tmp,ITSM_BACKUP='1'),environ={},
                backup_dir=Path(tmp)/'backups',start_workers=False)
            runtime=app.extensions['openitsm']['runtime']
            self.assertEqual(list((Path(tmp)/'backups').iterdir()),[])
            with patch.object(runtime.threading,'Thread') as thread:
                self.assertTrue(start_background_services(app))
                self.assertFalse(start_background_services(app))
                self.assertEqual(thread.call_count,1)
                thread.return_value.start.assert_called_once()
            snapshots=list((Path(tmp)/'backups').glob('*.db')); self.assertEqual(len(snapshots),1)
            c=sqlite3.connect(snapshots[0])
            try:
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],1)
                tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({'org_units','chat_messages','cards'}.issubset(tables))
                self.assertIn('unit_id',{r[1] for r in c.execute('PRAGMA table_info(assets)')})
            finally: c.close()

    def test_failed_initialization_never_starts_workers(self):
        from application import create_app
        with tempfile.TemporaryDirectory(prefix='openitsm-p102-failed-') as tmp:
            with patch('threading.Thread.start') as start:
                with self.assertRaises(RuntimeError):
                    create_app(self.settings(tmp,ITSM_BACKUP='1',ITSM_INITIAL_ADMIN_PASSWORD='short'),
                        environ={},backup_dir=Path(tmp)/'backups',start_workers=True)
                start.assert_not_called()

    def test_legacy_script_entry_calls_server_once(self):
        fake=Mock(); runtime=Mock()
        fake.extensions={'openitsm':{'runtime':runtime}}
        with patch('application.create_app',return_value=fake) as factory:
            runpy.run_path(str(ROOT/'app.py'),run_name='__main__')
        factory.assert_called_once_with()
        runtime.run_server.assert_called_once_with()

    def test_unconfigured_flask_debug_cannot_override_instance_policy(self):
        from phase0_runtime_cases import certificate
        with tempfile.TemporaryDirectory(prefix='openitsm-p102-debug-') as tmp:
            cert,key=certificate(tmp)
            with patch.dict(os.environ,FLASK_DEBUG='1'):
                app=self.make(tmp,ITSM_ENV='production',ITSM_TLS='1',ITSM_HTTPS='1',
                    ITSM_CERT=cert,ITSM_KEY=key,TESTING=False)
                self.assertFalse(app.debug)
                self.assertFalse(app.config['DEBUG'])
