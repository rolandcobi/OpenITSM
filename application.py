"""Side-effect-free factory entry point; legacy app.py remains compatible."""
import importlib.util
import threading
import uuid
from pathlib import Path
from app_config import resolve_settings, resolve_secret
from migrations import run_migrations, prepare_application_storage

def create_app(config=None, *, environ=None, start_workers=None, backup_dir=None, secret_path=None):
    """Build an isolated application with an immutable environment snapshot.

    Transitional runtime namespaces preserve legacy helper monkeypatching and URL
    contracts. Handler/transaction extraction belongs to later Phase 1 packages.
    Explicit creation initializes only this instance's configured database.
    """
    settings,testing = resolve_settings(config,environ)
    if start_workers is not None and not isinstance(start_workers,bool):
        raise ValueError('start_workers must be boolean or None')
    base = Path(__file__).resolve().parent
    secret = resolve_secret(settings,secret_path or base/'secret.key')
    database_path = settings.get('ITSM_DB') or str(base/'itsm.db')
    run_migrations(database_path,settings.get('ITSM_INITIAL_ADMIN_PASSWORD',''))
    prepare_application_storage(database_path)
    name = '_openitsm_runtime_'+uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name,base/'_application_runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    runtime._runtime = runtime
    runtime._settings = settings
    runtime._backup_dir = str(backup_dir or base/'backups')
    runtime._secret_key = secret
    runtime._testing = testing
    try:
        spec.loader.exec_module(runtime)
    finally:
        database = getattr(runtime,'_database',None)
        if database is not None:
            database.finish_initialization()
    app = runtime.app
    app.extensions['openitsm'] = dict(runtime=runtime,settings=settings,database=runtime._database,
        worker_lock=threading.Lock(),workers_started=False)
    runtime.create_app = create_app
    enabled = (not testing) if start_workers is None else start_workers
    if enabled:
        start_background_services(app)
    return app

def start_background_services(app):
    """Start configured backup work once, after all schema initializers finish."""
    state = app.extensions['openitsm']
    if state['settings'].get('ITSM_BACKUP','1')!='1':
        return False
    with state['worker_lock']:
        if state['workers_started']:
            return False
        runtime = state['runtime']
        runtime.backup_once()
        thread = threading.Thread(target=runtime.backup_worker,daemon=True)
        thread.start()
        state.update(workers_started=True,backup_thread=thread)
        return True
