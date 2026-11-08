"""P1-04 atomic migration/recovery contracts; synthetic file databases only."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

class MigrationContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='openitsm-p104-')
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.snapshots=json.loads((ROOT/'tests/fixtures/historical_schemas.json').read_text(encoding='utf-8'))

    def old(self,name='old.sqlite',index=0):
        path=self.folder/name
        c=sqlite3.connect(path); c.executescript(self.snapshots[index]['sql'])
        c.execute("INSERT INTO users(id,username,full_name,role,active) VALUES(1,'synthetic','Preserved user','Requester',1)")
        c.execute("INSERT INTO audit(id,actor_id,action,object_type,object_id,new_value,created_at) VALUES(10,1,'SyntheticPreserved','User',1,'PRESERVED AUDIT','2020-01-01')")
        c.commit(); c.close()
        return path

    def dump(self,path):
        c=sqlite3.connect(path)
        try: return '\n'.join(c.iterdump())
        finally: c.close()

    def version(self,path):
        c=sqlite3.connect(path)
        try: return c.execute('PRAGMA user_version').fetchone()[0]
        finally: c.close()

    def test_import_is_pure(self):
        code="""import sqlite3,threading,os
from pathlib import Path
def forbidden(*a,**k): raise AssertionError('Import side effect')
sqlite3.connect=forbidden
threading.Thread.start=forbidden
before=dict(os.environ)
import migrations,migration_steps,application
assert before==dict(os.environ)
assert not list(Path.cwd().iterdir())
"""
        result=subprocess.run([sys.executable,'-c',code],cwd=self.folder,
            env=dict(os.environ,PYTHONPATH=str(ROOT)),capture_output=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_check_is_readonly_and_target_refusal_does_not_create_file(self):
        from migrations import inspect_database,run_migrations
        fresh=self.folder/'missing.sqlite'
        self.assertEqual(inspect_database(fresh)['version'],0); self.assertFalse(fresh.exists())
        for target in (0,2,999):
            with self.assertRaises(RuntimeError): run_migrations(fresh,'SyntheticOnly!12345',target)
        self.assertFalse(fresh.exists())
        for unsupported in (':memory:','file:synthetic?mode=memory&cache=shared'):
            with self.assertRaises(RuntimeError): inspect_database(unsupported)
        with self.assertRaises(RuntimeError): run_migrations(fresh,'short')
        self.assertFalse(fresh.exists())
        path=self.old(); before=path.read_bytes()
        self.assertEqual(len(inspect_database(path)['steps']),4)
        self.assertEqual(path.read_bytes(),before)

    def test_fresh_upgrade_orders_steps_marker_and_immutable_audit(self):
        import migrations
        path=self.folder/'fresh.sqlite'; statements=[]; real=sqlite3.connect
        def connect(*a,**k):
            c=real(*a,**k); c.set_trace_callback(statements.append); return c
        with patch.object(migrations.sqlite3,'connect',side_effect=connect):
            result=migrations.run_migrations(path,'SyntheticOnly!12345')
        self.assertEqual(result['applied'],[n for n,_ in migrations.STEPS])
        self.assertEqual(self.version(path),1)
        self.assertEqual(sum(s.strip().upper()=='COMMIT' for s in statements),1)
        marker=next(i for i,s in enumerate(statements) if s.replace(' ','').upper()=='PRAGMAUSER_VERSION=1')
        self.assertLess(marker,next(i for i,s in enumerate(statements) if s.strip().upper()=='COMMIT'))
        c=sqlite3.connect(path)
        try:
            c.execute("INSERT INTO audit(actor_id,action,object_type,object_id,new_value) VALUES(1,'Synthetic','User',1,'immutable')"); c.commit()
            for sql in ("UPDATE audit SET new_value='forged'","DELETE FROM audit"):
                with self.assertRaises(sqlite3.IntegrityError): c.execute(sql)
                c.rollback()
            self.assertEqual(c.execute('SELECT new_value FROM audit').fetchall(),[('immutable',)])
        finally: c.close()

    def test_completed_version_is_readonly_no_seed_no_backfill(self):
        import migrations
        path=self.folder/'current.sqlite'; migrations.run_migrations(path,'SyntheticOnly!12345')
        c=sqlite3.connect(path)
        c.execute("UPDATE users SET org_unit_id=2 WHERE id=1")
        c.execute("UPDATE services SET unit_id=2 WHERE id=1")
        c.execute("INSERT INTO assets(name,owner_id,service_id,unit_id) VALUES('Synthetic no reclassify',1,1,NULL)")
        c.execute("INSERT INTO audit(action,object_type,new_value) VALUES('Synthetic','User','unchanged')")
        c.execute('DELETE FROM support_groups'); c.commit(); c.close()
        before=path.read_bytes(); logical=self.dump(path); real=sqlite3.connect; modes=[]
        def connect(*a,**k): modes.append(k.get('uri',False)); return real(*a,**k)
        with patch.object(migrations,'apply_step',side_effect=AssertionError('Must not replay')),patch.object(migrations.sqlite3,'connect',side_effect=connect):
            self.assertEqual(migrations.run_migrations(path)['applied'],[])
        self.assertTrue(all(modes)); self.assertEqual(path.read_bytes(),before); self.assertEqual(self.dump(path),logical)

    def test_each_step_failure_rolls_back_schema_rows_audit_and_marker(self):
        import migrations
        real=migrations.apply_step
        for index,(target,_) in enumerate(migrations.STEPS):
            path=self.old('failure-'+str(index)+'.sqlite'); before=self.dump(path)
            def fail(name,function,c,password):
                real(name,function,c,password)
                if name==target:
                    c.execute("UPDATE users SET role='System Administrator' WHERE id=1")
                    c.execute("INSERT INTO audit(action,object_type,new_value) VALUES('SyntheticFailure','User','uncommitted')")
                    raise RuntimeError('Synthetic step failure')
            with self.subTest(step=target),patch.object(migrations,'apply_step',side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,'Synthetic step failure'): migrations.run_migrations(path)
            self.assertEqual(self.dump(path),before); self.assertEqual(self.version(path),0)
            c=sqlite3.connect(path); c.execute('BEGIN IMMEDIATE'); c.rollback(); c.close()

    def test_commit_failure_restores_audit_and_releases_lock(self):
        import migrations
        path=self.old(); before=self.dump(path); real=sqlite3.connect; closed=[]
        class Broken(sqlite3.Connection):
            def commit(self): raise sqlite3.OperationalError('Synthetic commit failure')
            def close(self): closed.append(True); return super().close()
        def connect(*a,**k): return real(*a,**k,factory=Broken)
        with patch.object(migrations.sqlite3,'connect',side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError): migrations.run_migrations(path)
        self.assertEqual(self.dump(path),before); self.assertEqual(self.version(path),0)
        self.assertEqual(len(closed),2)
        c=sqlite3.connect(path); c.execute('BEGIN IMMEDIATE'); c.rollback(); c.close()

    def test_step_cannot_commit_or_advance_marker(self):
        import migrations
        real=migrations.apply_step
        commands=('COMMIT;','-- leading comment\nCOMMIT;','PRAGMA user_version=1;','SAVEPOINT forbidden;')
        for index,command in enumerate(commands):
            path=self.old('control-'+str(index)+'.sqlite'); before=self.dump(path)
            def forbidden(name,function,c,password):
                real(name,function,c,password)
                if name=='0001_core': c.executescript(command)
            with self.subTest(command=command),patch.object(migrations,'apply_step',side_effect=forbidden):
                with self.assertRaises((RuntimeError,sqlite3.DatabaseError)): migrations.run_migrations(path)
            self.assertEqual(self.dump(path),before); self.assertEqual(self.version(path),0)

    def test_migration_cannot_edit_or_append_audit_history(self):
        import migrations
        real=migrations.apply_step
        trigger=json.loads((ROOT/'schema_v1.json').read_text(encoding='utf-8'))['objects']['audit_nu']['sql']
        for action in ('append','edit'):
            path=self.old(action+'.sqlite'); before=self.dump(path)
            def tamper(name,function,c,password):
                real(name,function,c,password)
                if name=='0001_workspace':
                    if action=='append':
                        c.execute("INSERT INTO audit(action,object_type,new_value) VALUES('ForgedMigration','User','forged')")
                    else:
                        c.execute('DROP TRIGGER audit_nu')
                        c.execute("UPDATE audit SET new_value='forged' WHERE id=10")
                        c.execute(trigger)
            with self.subTest(action=action),patch.object(migrations,'apply_step',side_effect=tamper):
                with self.assertRaisesRegex(RuntimeError,'Migration changed application audit history'):
                    migrations.run_migrations(path)
            self.assertEqual(self.dump(path),before); self.assertEqual(self.version(path),0)

    def test_inconsistent_version_one_refuses_without_changes(self):
        import migrations
        path=self.folder/'bad-one.sqlite'; migrations.run_migrations(path,'SyntheticOnly!12345')
        c=sqlite3.connect(path); c.execute('DROP TRIGGER audit_nd'); c.commit(); c.close()
        before=path.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'Invalid schema version 1 object'): migrations.inspect_database(path)
        with self.assertRaises(RuntimeError): migrations.run_migrations(path)
        self.assertEqual(path.read_bytes(),before); self.assertEqual(self.version(path),1)

    def test_foreign_key_violation_rolls_back_upgrade(self):
        import migrations
        path=self.old(); c=sqlite3.connect(path)
        c.executescript('CREATE TABLE synthetic_parent(id INTEGER PRIMARY KEY); CREATE TABLE synthetic_child(id INTEGER PRIMARY KEY,parent_id INTEGER REFERENCES synthetic_parent(id)); INSERT INTO synthetic_child VALUES(1,999);')
        c.close(); before=self.dump(path)
        with self.assertRaisesRegex(RuntimeError,'foreign-key violations'): migrations.run_migrations(path)
        self.assertEqual(self.dump(path),before); self.assertEqual(self.version(path),0)

    def test_all_frozen_snapshot_restores_preserve_audit_and_repeat(self):
        import migrations
        for index in range(4):
            with self.subTest(snapshot=index):
                path=self.old('snapshot-'+str(index)+'.sqlite',index)
                backup=self.folder/('backup-'+str(index)+'.sqlite')
                source=sqlite3.connect(path); target=sqlite3.connect(backup); source.backup(target); target.close(); source.close()
                self.assertEqual(migrations.run_migrations(path)['after'],1)
                before=path.read_bytes(); self.assertEqual(migrations.run_migrations(path)['applied'],[]); self.assertEqual(path.read_bytes(),before)
                c=sqlite3.connect(path); self.assertEqual(c.execute('SELECT new_value FROM audit').fetchall(),[('PRESERVED AUDIT',)]); c.close()
                restored=self.folder/('restore-'+str(index)+'.sqlite')
                source=sqlite3.connect(backup); target=sqlite3.connect(restored); source.backup(target); target.close(); source.close()
                self.assertEqual(migrations.run_migrations(restored)['after'],1)
                c=sqlite3.connect(restored)
                self.assertEqual(c.execute('SELECT new_value FROM audit').fetchall(),[('PRESERVED AUDIT',)])
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok'); c.close()

    def test_locked_runner_refuses_then_recovers(self):
        import migrations
        path=self.old(); before=path.read_bytes(); c=sqlite3.connect(path); c.execute('BEGIN EXCLUSIVE')
        try:
            with self.assertRaises(RuntimeError): migrations.run_migrations(path)
            self.assertEqual(path.read_bytes(),before)
        finally: c.rollback(); c.close()
        self.assertEqual(migrations.run_migrations(path)['after'],1)

    def test_concurrent_runners_recheck_version_under_writer_lock(self):
        import migrations
        path=self.old()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:migrations.run_migrations(path),range(2)))
        self.assertEqual(sorted(len(r['applied']) for r in results),[0,4])
        self.assertEqual(self.version(path),1)
        c=sqlite3.connect(path)
        self.assertEqual(c.execute('SELECT count(*) FROM users').fetchone()[0],1)
        self.assertEqual(c.execute('SELECT new_value FROM audit').fetchall(),[('PRESERVED AUDIT',)]); c.close()

    def test_cli_check_and_apply_use_only_synthetic_storage(self):
        path=self.folder/'cli.sqlite'
        env=dict(os.environ,ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345')
        def run(action):
            return subprocess.run([sys.executable,str(ROOT/'migrations.py'),'--database',str(path),action],cwd=ROOT,env=env,capture_output=True,encoding='utf-8',timeout=30)
        check=run('--check'); self.assertEqual(check.returncode,0,check.stderr); self.assertFalse(path.exists())
        apply=run('--apply'); self.assertEqual(apply.returncode,0,apply.stderr)
        self.assertEqual(json.loads(apply.stdout.splitlines()[-1])['after'],1)
        self.assertNotIn('SyntheticOnly!12345',apply.stdout+apply.stderr)
        before=path.read_bytes(); again=run('--apply')
        self.assertEqual(again.returncode,0,again.stderr); self.assertEqual(json.loads(again.stdout)['applied'],[])
        self.assertEqual(path.read_bytes(),before)

    def test_factory_refuses_bad_marker_before_runtime_workers(self):
        from application import create_app
        import migrations
        path=self.folder/'factory.sqlite'; migrations.run_migrations(path,'SyntheticOnly!12345')
        c=sqlite3.connect(path); c.execute('DROP INDEX ix_assets_unit'); c.commit(); c.close()
        before=path.read_bytes()
        with patch('application.start_background_services') as worker:
            with self.assertRaises(RuntimeError):
                create_app(dict(ITSM_ENV='test',ITSM_DB=str(path),ITSM_SECRET_KEY='synthetic-factory-key-'*4,
                    ITSM_BACKUP='1',TESTING=True),environ={},start_workers=True,backup_dir=self.folder/'must-not-create')
            worker.assert_not_called()
        self.assertEqual(path.read_bytes(),before); self.assertFalse((self.folder/'must-not-create').exists())

    def test_wal_is_prepared_before_first_concurrent_connections(self):
        import migrations
        from application import create_app
        path=self.folder/'first-connections.sqlite'
        migrations.run_migrations(path,'SyntheticOnly!12345')
        for prior in ('wal','delete'):
            with self.subTest(prior_journal=prior):
                c=sqlite3.connect(path)
                self.assertEqual(c.execute('PRAGMA journal_mode='+prior).fetchone()[0],prior); c.close()
                before=path.read_bytes()
                self.assertEqual(migrations.run_migrations(path)['applied'],[])
                self.assertEqual(path.read_bytes(),before)
                create_app(dict(ITSM_ENV='test',ITSM_DB=str(path),ITSM_SECRET_KEY='synthetic-wal-key-'*4,
                    ITSM_BACKUP='0',TESTING=True),environ={},backup_dir=self.folder/'backups')
                c=sqlite3.connect(path)
                self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0],'wal'); c.close()
                def connect(_):
                    c=sqlite3.connect(path,timeout=2)
                    try:
                        return c.execute('PRAGMA journal_mode=WAL').fetchone()[0]
                    finally: c.close()
                with ThreadPoolExecutor(max_workers=4) as pool:
                    self.assertEqual(list(pool.map(connect,range(4))),['wal']*4)
