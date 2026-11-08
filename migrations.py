"""Explicit schema-v1 migration planning and atomic execution; import is pure."""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import weakref
from migration_steps import init_db, organization, chat, workspace

REQUIRED_CORE = {'users': ['active', 'email', 'full_name', 'id', 'password_hash', 'role', 'structure', 'username'], 'tickets': ['assignee_id', 'category', 'closed_at', 'code', 'created_at', 'created_by', 'description', 'due_at', 'id', 'priority', 'requester_id', 'resolved_at', 'service_id', 'status', 'structure', 'title', 'type'], 'services': ['category', 'id', 'name', 'status'], 'tasks': ['completed_at', 'completion_notes', 'created_at', 'description', 'due_at', 'id', 'priority', 'status', 'ticket_id', 'title'], 'assets': ['asset_type', 'created_at', 'criticality', 'hostname', 'id', 'ip_address', 'location', 'name', 'notes', 'owner_id', 'service_id', 'status', 'structure']}

TARGET_VERSION = 1
# One schema version, with explicit ordered steps; no new schema/ledger is added.
STEPS = (('0001_core',init_db),('0001_organization',organization),
         ('0001_chat',chat),('0001_workspace',workspace))

def _target(target):
    if target != TARGET_VERSION:
        raise RuntimeError('Unsupported migration target')

def _schema():
    return json.loads(Path(__file__).with_name('schema_v1.json').read_text(encoding='utf-8'))

def _normalize(sql):
    return re.sub(r'\s+','',re.sub(r'IF\s+NOT\s+EXISTS\s+','',sql,flags=re.I)).casefold()

def validate_version_one(connection):
    expected = _schema()
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table,columns in expected['tables'].items():
        if table not in tables or not set(columns).issubset({r[1] for r in connection.execute('PRAGMA table_info('+table+')')}):
            raise RuntimeError('Incomplete schema version 1: '+table)
    objects = {r[0]:(r[1],r[2]) for r in connection.execute("SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL")}
    for name,item in expected['objects'].items():
        if name not in objects or objects[name][0]!=item['type'] or _normalize(objects[name][1])!=_normalize(item['sql']):
            raise RuntimeError('Invalid schema version 1 object: '+name)
    if connection.execute('PRAGMA foreign_key_check').fetchone():
        raise RuntimeError('Database contains foreign-key violations')

def _inspect(connection):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version not in (0,TARGET_VERSION):
        raise RuntimeError('Unsupported database schema version')
    if connection.execute('PRAGMA quick_check').fetchone()[0]!='ok':
        raise RuntimeError('Database integrity check failed')
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table,columns in REQUIRED_CORE.items():
        if table in tables and not set(columns).issubset({r[1] for r in connection.execute('PRAGMA table_info('+table+')')}):
            raise RuntimeError('Unsupported historical schema: '+table)
    if version==TARGET_VERSION:
        validate_version_one(connection)
    bootstrap = version<TARGET_VERSION and ('users' not in tables or not connection.execute('SELECT 1 FROM users LIMIT 1').fetchone())
    return dict(version=version,target=TARGET_VERSION,needs_bootstrap=bool(bootstrap),
                steps=[name for name,_ in STEPS] if version<TARGET_VERSION else [])

def inspect_database(path, target=TARGET_VERSION):
    """Read-only preflight; never create/repair storage."""
    _target(target)
    if str(path)==':memory:' or str(path).startswith('file:'):
        raise RuntimeError('Database must be a local SQLite file path')
    path = Path(path)
    if not path.exists() or path.is_file() and path.stat().st_size==0:
        return dict(version=0,target=TARGET_VERSION,needs_bootstrap=True,steps=[name for name,_ in STEPS])
    if not path.is_file():
        raise RuntimeError('Database must be a local SQLite file')
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        return _inspect(connection)
    except sqlite3.Error as error:
        raise RuntimeError('Database preflight failed; restore a verified backup') from error
    finally:
        if connection is not None:
            connection.close()

class MigrationConnection:
    """Execute scripts statement by statement without executescript's commit."""
    def __init__(self, connection):
        self._connection = connection
    def execute(self, sql, *args):
        first = sql.lstrip().split(None,1)[0].rstrip(';').upper()
        if first in ('COMMIT','ROLLBACK','BEGIN','END','SAVEPOINT','RELEASE','VACUUM','ATTACH','DETACH'):
            raise RuntimeError('Migration transaction control belongs to runner')
        return self._connection.execute(sql,*args)
    def executescript(self, script):
        pending = ''
        for char in script:
            pending += char
            if char==';' and sqlite3.complete_statement(pending):
                self.execute(pending)
                pending = ''
        if pending.strip():
            raise RuntimeError('Incomplete migration SQL')
    def commit(self):
        raise RuntimeError('Migration transaction control belongs to runner')
    rollback = commit
    close = commit

def apply_step(name, function, connection, bootstrap_password):
    if name=='0001_core':
        function(connection,bootstrap_password)
    else:
        function(connection)

def _step_authorizer(action, first, second, database, trigger):
    if action in (sqlite3.SQLITE_TRANSACTION,sqlite3.SQLITE_SAVEPOINT,sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    if action==sqlite3.SQLITE_PRAGMA and first.lower() in ('user_version','writable_schema','foreign_keys','journal_mode') and second is not None:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK

def _audit_snapshot(connection):
    exists=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit'").fetchone()
    return [tuple(r) for r in connection.execute('SELECT * FROM audit ORDER BY id')] if exists else []

def _run_migrations_locked(path, bootstrap_password='', target=TARGET_VERSION):
    """Upgrade only versions 0->1; completed version 1 is a read-only no-op."""
    plan = inspect_database(path,target)
    if plan['version']==TARGET_VERSION:
        return dict(before=TARGET_VERSION,after=TARGET_VERSION,applied=[])
    if plan['needs_bootstrap'] and len(bootstrap_password)<12:
        raise RuntimeError('First start requires ITSM_INITIAL_ADMIN_PASSWORD with at least 12 characters. See README.md.')
    connection = None
    try:
        connection = sqlite3.connect(path,timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('BEGIN IMMEDIATE')
        # Recheck under the writer reservation so a stale plan cannot apply twice.
        current = _inspect(connection)
        if current['version']==TARGET_VERSION:
            connection.rollback()
            return dict(before=TARGET_VERSION,after=TARGET_VERSION,applied=[])
        proxy = MigrationConnection(connection)
        applied = []
        audit_before = _audit_snapshot(connection)
        connection.set_authorizer(_step_authorizer)
        try:
            for name,function in STEPS:
                apply_step(name,function,proxy,bootstrap_password)
                applied.append(name)
            validate_version_one(connection)
            if _audit_snapshot(connection)!=audit_before:
                raise RuntimeError('Migration changed application audit history')
            if connection.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise RuntimeError('Migrated database integrity check failed')
        finally:
            connection.set_authorizer(None)
        connection.execute('PRAGMA user_version=1')
        connection.commit()
        if current['needs_bootstrap']:
            print('OpenITSM: administrator account initialized from environment.')
        return dict(before=0,after=TARGET_VERSION,applied=applied)
    except BaseException:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()

_locks_guard = threading.Lock()
_path_locks = weakref.WeakValueDictionary()

def _lock_for(path):
    key = os.path.normcase(str(Path(path).resolve()))
    with _locks_guard:
        lock = _path_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _path_locks[key] = lock
        return lock

def run_migrations(path, bootstrap_password='', target=TARGET_VERSION):
    _target(target)
    if str(path)==':memory:' or str(path).startswith('file:'):
        raise RuntimeError('Database must be a local SQLite file path')
    # Serialize same-process factories before the journal-mode transition.
    # SQLite still controls cross-process writer locking/revalidation.
    with _lock_for(path):
        return _run_migrations_locked(path,bootstrap_password,target)

def prepare_application_storage(path):
    """Configure application WAL before requests, separate from schema no-op."""
    with _lock_for(path):
        if inspect_database(path)['version']!=TARGET_VERSION:
            raise RuntimeError('Migrate database before preparing application storage')
        connection = sqlite3.connect(path,timeout=2)
        try:
            if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]!='wal':
                raise RuntimeError('Application requires local SQLite WAL mode')
        finally:
            connection.close()

def main(argv=None):
    parser = argparse.ArgumentParser(description='OpenITSM schema-v1 migration maintenance')
    parser.add_argument('--database',required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check',action='store_true')
    action.add_argument('--apply',action='store_true')
    parser.add_argument('--target',type=int,default=TARGET_VERSION)
    args = parser.parse_args(argv)
    result = inspect_database(args.database,args.target) if args.check else run_migrations(
        args.database,os.environ.get('ITSM_INITIAL_ADMIN_PASSWORD',''),args.target)
    print(json.dumps(result))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
