"""Startup/migration checks in fresh processes and disposable synthetic databases."""
import ast
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest


class Phase0Migrations(unittest.TestCase):
    def test_locked_startup_refuses_without_mutation_then_recovers(self):
        with tempfile.TemporaryDirectory(prefix='openitsm-locked-') as tmp:
            path=Path(tmp)/'locked.db'; c=sqlite3.connect(path)
            c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)'); c.commit()
            before=path.read_bytes(); c.execute('BEGIN EXCLUSIVE')
            try:
                result=self.run_import(path)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(path.read_bytes(),before)
            finally: c.rollback(); c.close()
            result=self.run_import(path)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_production_configuration_fails_closed_and_host_policy_is_enforced(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='openitsm-config-') as tmp:
            from phase0_runtime_cases import certificate
            cert,key=certificate(tmp)
            base=dict(os.environ,ITSM_CERT=cert,ITSM_KEY=key,ITSM_DB=str(Path(tmp)/'config.db'),ITSM_BACKUP='0',ITSM_ENV='production',ITSM_SECRET_KEY='synthetic-production-key-'*3,ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345',ITSM_HTTPS='1',ITSM_TLS='1',ITSM_DEBUG='0',ITSM_ALLOWED_HOSTS='itsm.example.invalid,localhost')
            for field,value in (('ITSM_SECRET_KEY','short'),('ITSM_HTTPS','0'),('ITSM_TLS','0'),('ITSM_DEBUG','1'),('ITSM_ALLOWED_HOSTS',''),('ITSM_CERT','missing-cert')):
                env=dict(base); env[field]=value
                result=subprocess.run([str(root/'.venv/Scripts/python.exe'),'-c','import app'],cwd=root,env=env,capture_output=True,text=True,timeout=30)
                self.assertNotEqual(result.returncode,0,field)
            code="import app; c=app.app.test_client(); assert c.get('/login',base_url='https://evil.invalid').status_code==400; r=c.get('/login',base_url='https://itsm.example.invalid'); assert r.status_code==200; assert 'Secure' in r.headers['Set-Cookie']"
            result=subprocess.run([str(root/'.venv/Scripts/python.exe'),'-c',code],cwd=root,env=base,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def run_import(self, database, code='import app'):
        root=Path(__file__).resolve().parents[1]
        env=dict(os.environ,ITSM_ENV='test',ITSM_ALLOWED_HOSTS='localhost,127.0.0.1',ITSM_DB=str(database),ITSM_SECRET_KEY='synthetic-frozen-migration-'*3,ITSM_BACKUP='0',ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345')
        return subprocess.run([str(root/'.venv/Scripts/python.exe'),'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=45)

    def test_frozen_git_schema_snapshots_upgrade_backup_restore_and_resume(self):
        snapshots=json.loads((Path(__file__).parent/'fixtures/historical_schemas.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory(prefix='openitsm-frozen-') as tmp:
            for index,snapshot in enumerate(snapshots):
                with self.subTest(commit=snapshot['commit']):
                    dbfile=Path(tmp)/('old-'+str(index)+'.db'); backup=Path(tmp)/('backup-'+str(index)+'.db')
                    c=sqlite3.connect(dbfile); c.executescript(snapshot['sql'])
                    c.execute("INSERT INTO users(id,username,full_name,role,active) VALUES(1,'synthetic','Preserved account','Requester',1)")
                    c.execute("INSERT INTO tickets(id,code,title,type,status,priority,requester_id,created_by) VALUES(1,'SYN-HIST','Preserved ticket','Service Request','Open','Medium',1,1)")
                    c.commit(); b=sqlite3.connect(backup); c.backup(b); b.close(); c.close()
                    code="""import app,time
app.app.config['TESTING']=True
c=app.db()
assert c.execute('PRAGMA user_version').fetchone()[0]==1
assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert c.execute('SELECT full_name FROM users WHERE id=1').fetchone()[0]=='Preserved account'
assert c.execute('SELECT title FROM tickets WHERE id=1').fetchone()[0]=='Preserved ticket'
c.close()
client=app.app.test_client()
with client.session_transaction() as s: s.update(uid=1,auth_version=0,issued_at=time.time(),name='Preserved account',role='Requester',csrf='synthetic')
assert client.get('/tickets/1').status_code==200
"""
                    for _ in range(2):
                        result=self.run_import(dbfile,code); self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    # Supported rollback is restoration of a verified SQLite snapshot,
                    # not running a security-obsolete application on an upgraded DB.
                    restored=Path(tmp)/('restored-'+str(index)+'.db')
                    source=sqlite3.connect(backup); target=sqlite3.connect(restored); source.backup(target); target.close(); source.close()
                    result=self.run_import(restored,code); self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_migration_refuses_future_corrupt_and_incompatible_without_changes(self):
        with tempfile.TemporaryDirectory(prefix='openitsm-refusal-') as tmp:
            for kind in ('future','corrupt','incompatible'):
                with self.subTest(kind=kind):
                    path=Path(tmp)/(kind+'.db')
                    if kind=='corrupt': path.write_bytes(b'not a SQLite database, synthetic only')
                    else:
                        c=sqlite3.connect(path)
                        if kind=='future': c.execute('PRAGMA user_version=999')
                        else: c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,unknown TEXT)')
                        c.commit(); c.close()
                    before=path.read_bytes(); result=self.run_import(path)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('RuntimeError',result.stderr)
                    self.assertEqual(path.read_bytes(),before)

    def test_partial_additive_upgrade_resumes_and_persistent_lockout_survives_restart(self):
        snapshot=json.loads((Path(__file__).parent/'fixtures/historical_schemas.json').read_text(encoding='utf-8'))[0]
        with tempfile.TemporaryDirectory(prefix='openitsm-partial-') as tmp:
            path=Path(tmp)/'partial.db'; c=sqlite3.connect(path); c.executescript(snapshot['sql'])
            c.execute("INSERT INTO users(id,username,full_name,role) VALUES(1,'synthetic','Preserved','Requester')")
            if 'auth_version' not in [r[1] for r in c.execute('PRAGMA table_info(users)')]: c.execute('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0')
            c.commit(); c.close()
            result=self.run_import(path,"import app,time; c=app.db(); c.executemany('INSERT INTO login_attempts VALUES(?,?)',[('127.0.0.1',time.time())]*20); c.commit(); c.close()")
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=self.run_import(path,"import app; client=app.app.test_client(); ctx=client.session_transaction(); s=ctx.__enter__(); s['csrf']='synthetic'; ctx.__exit__(None,None,None); response=client.post('/login',data={'csrf_token':'synthetic','username':'missing','password':'invalid'}); assert response.status_code==429")
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_legacy_schema_migrates_preserves_data_and_is_repeatable(self):
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'migration_steps.py').read_text(encoding='utf-8'))
        init=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='init_db')
        schema=next(n.args[0].value for n in ast.walk(init) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='executescript')
        with tempfile.TemporaryDirectory(prefix='openitsm-migration-') as tmp:
            database=Path(tmp)/'synthetic-old.db'
            c=sqlite3.connect(database); c.executescript(schema)
            c.execute("INSERT INTO users(id,username,full_name,role,structure) VALUES(1,'synthetic-old','Legacy Requester','Requester','Same')")
            c.execute("INSERT INTO users(id,username,full_name,role,structure) VALUES(2,'synthetic-other','Foreign Requester','Requester','Same')")
            c.executescript('''
                ALTER TABLE users ADD COLUMN org_unit_id INTEGER;
                ALTER TABLE services ADD COLUMN unit_id INTEGER;
                CREATE TABLE org_units(id INTEGER PRIMARY KEY,parent_id INTEGER,name TEXT,kind TEXT,sort INTEGER);
                INSERT INTO org_units VALUES(1,NULL,'Synthetic root','ORG',0),(2,1,'Synthetic A','UNIT',0),(6,1,'Synthetic B','UNIT',1);
                UPDATE users SET org_unit_id=2 WHERE id=1;
                UPDATE users SET org_unit_id=6 WHERE id=2;
                INSERT INTO services(id,name,unit_id) VALUES(11,'Synthetic foreign service',6),(12,'Synthetic invalid scope service',999);
                INSERT INTO assets(id,name,owner_id,service_id,structure) VALUES
                  (201,'Synthetic owned asset',1,NULL,'Same'),
                  (202,'Synthetic conflicting asset',1,11,'Same'),
                  (203,'Synthetic service asset',NULL,11,'Same'),
                  (204,'Synthetic unscoped asset',NULL,NULL,'Same'),
                  (205,'Synthetic invalid asset',NULL,12,'Same');
            ''')
            c.execute("INSERT INTO tickets(id,code,title,type,status,priority,requester_id,created_by,created_at) VALUES(1,'SYN-OLD','Preserved synthetic ticket','Service Request','Open','Medium',1,1,'2020-01-01 10:00:00')")
            c.execute("INSERT INTO tickets(id,code,title,type,status,priority,requester_id,created_by,created_at) VALUES(2,'SYN-FOREIGN','Foreign synthetic ticket','Service Request','Open','Medium',2,2,'2020-01-01 10:00:00')")
            c.commit(); c.close()
            env=dict(os.environ,ITSM_ENV='test',ITSM_ALLOWED_HOSTS='localhost,127.0.0.1',ITSM_DB=str(database),ITSM_SECRET_KEY='synthetic-migration-secret-'*3,ITSM_BACKUP='0',ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345')
            code='''import json, time, app
app.app.config['TESTING']=True
client=app.app.test_client()
with client.session_transaction() as s: s.update(auth_version=0,issued_at=time.time(),uid=1,csrf='synthetic',name='Legacy Requester',role='Requester')
assert client.get('/tickets/1').status_code==200
assert client.get('/tickets/2').status_code==403
c=app.db()
assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert not c.execute('PRAGMA foreign_key_check').fetchall()
assert c.execute('SELECT title FROM tickets WHERE id=1').fetchone()[0]=='Preserved synthetic ticket'
assert c.execute('SELECT role FROM users WHERE id=1').fetchone()[0]=='Requester'
assert c.execute('SELECT count(*) FROM users').fetchone()[0]==2
assert [tuple(r) for r in c.execute('SELECT id,unit_id FROM assets ORDER BY id')]==[(201,2),(202,None),(203,6),(204,None),(205,None)]
page=client.get('/assets')
assert page.status_code==200
assert b'Synthetic owned asset' in page.data
assert b'Synthetic service asset' not in page.data
assert b'Synthetic conflicting asset' not in page.data
print(json.dumps({t:[r['name'] for r in c.execute('PRAGMA table_info('+t+')')] for t in ('users','tickets','tasks','services','assets')}))
c.close()
'''
            outputs=[]
            for _ in range(2):
                result=subprocess.run([os.fspath(root/'.venv/Scripts/python.exe'),'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=45)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                outputs.append(json.loads(result.stdout.strip().splitlines()[-1]))
            self.assertEqual(outputs[0],outputs[1])
            self.assertIn('org_unit_id',outputs[0]['users'])
            self.assertIn('unit_id',outputs[0]['tickets'])
            self.assertIn('parent_id',outputs[0]['tasks'])
            self.assertIn('unit_id',outputs[0]['assets'])

    def test_empty_database_requires_explicit_strong_bootstrap_password(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='openitsm-bootstrap-') as tmp:
            env=dict(os.environ,ITSM_ENV='test',ITSM_ALLOWED_HOSTS='localhost,127.0.0.1',ITSM_DB=str(Path(tmp)/'synthetic.db'),ITSM_SECRET_KEY='synthetic-bootstrap-secret-'*3,ITSM_BACKUP='0',ITSM_INITIAL_ADMIN_PASSWORD='short')
            result=subprocess.run([os.fspath(root/'.venv/Scripts/python.exe'),'-c','import app'],cwd=root,env=env,capture_output=True,text=True,timeout=30)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('First start requires ITSM_INITIAL_ADMIN_PASSWORD',result.stderr)
