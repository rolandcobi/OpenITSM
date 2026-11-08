"""P1-05 registration/semantic contracts; synthetic per-instance databases only."""
import ast
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from flask import Flask, url_for

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=json.loads((ROOT/'tests/fixtures/p1_05_handler_contracts.json').read_text())

class Unbind(ast.NodeTransformer):
    def visit_Attribute(self,node):
        node=self.generic_visit(node)
        if isinstance(node.value,ast.Name) and node.value.id=='runtime' and node.attr in CONTRACT['runtime_symbols']:
            return ast.copy_location(ast.Name(id=node.attr,ctx=node.ctx),node)
        return node

def fingerprint(node):
    return hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()

class HandlerContracts(unittest.TestCase):
    def setUp(self):
        from application import create_app
        self.tmp=tempfile.TemporaryDirectory(prefix='openitsm-p105-')
        self.addCleanup(self.tmp.cleanup); self.folder=Path(self.tmp.name)
        self.app=self.make('one')
        self.runtime=self.app.extensions['openitsm']['runtime']
        c=self.runtime.db()
        for uid,unit in ((8,2),(99,6)):
            c.execute("INSERT INTO users(id,username,full_name,role,org_unit_id,active,profile_done) VALUES(?,?,?,'Requester',?,1,1)",(uid,'synthetic'+str(uid),'Synthetic requester '+str(uid),unit))
        for tid,uid,unit,title in ((101,8,2,'SYNTHETIC_LOCAL_READ'),(102,99,6,'FOREIGN_HANDLER_SECRET')):
            c.execute("INSERT INTO tickets(id,code,title,description,type,status,priority,requester_id,created_by,unit_id,created_at) VALUES(?,?,?,'synthetic','Service Request','Open','Medium',?,?,?,'2026-11-04 10:00:00')",(tid,'SYN-HANDLER-'+str(tid),title,uid,uid,unit))
        c.commit(); c.close(); self.client=self.app.test_client()

    def make(self,name):
        from application import create_app
        return create_app(dict(ITSM_ENV='test',ITSM_DB=str(self.folder/(name+'.sqlite')),
            ITSM_SECRET_KEY=('synthetic-handler-'+name+'-')*4,
            ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345',ITSM_BACKUP='0',
            ITSM_TLS='1',ITSM_HTTPS='0',ITSM_ALLOWED_HOSTS='localhost,127.0.0.1',TESTING=True),
            environ={},backup_dir=self.folder/(name+'-backups'))

    def actor(self,uid=8,client=None):
        with (client or self.client).session_transaction() as s:
            s.clear(); s.update(uid=uid,auth_version=0,issued_at=time.time(),csrf='synthetic-handler-token',role='System Administrator',name='Synthetic requester')

    def rows(self,query,args=()):
        c=sqlite3.connect(self.folder/'one.sqlite')
        try: return c.execute(query,args).fetchall()
        finally: c.close()

    def test_imports_are_pure_without_database_or_worker(self):
        modules=[p.stem for p in (ROOT/'handlers').glob('*.py') if p.stem!='__init__']
        code="""import sqlite3,threading,os,importlib
from pathlib import Path
def forbidden(*a,**k): raise AssertionError('Import side effect')
sqlite3.connect=forbidden; threading.Thread.start=forbidden
before=dict(os.environ)
import handler_registry,handlers
for name in NAMES: importlib.import_module('handlers.'+name)
assert before==dict(os.environ)
assert not list(Path.cwd().iterdir())
""".replace('NAMES',repr(modules))
        with tempfile.TemporaryDirectory(prefix='openitsm-p105-import-') as folder:
            r=subprocess.run([sys.executable,'-c',code],cwd=folder,
                env=dict(os.environ,PYTHONPATH=str(ROOT)),capture_output=True,encoding='utf-8',timeout=30)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_exact_route_order_endpoints_and_methods_preserved(self):
        expected=json.loads((ROOT/'evidence/p1-04/regression_results.json').read_text())['routes']
        actual=[dict(route=str(r),methods=sorted(set(r.methods)-{'HEAD','OPTIONS'}),handler=r.endpoint) for r in self.app.url_map.iter_rules() if r.endpoint!='static']
        self.assertEqual(actual,expected); self.assertEqual(len(actual),38)

    def test_url_for_names_and_converter_values_remain_compatible(self):
        with self.app.test_request_context('/'):
            for route in self.app.url_map.iter_rules():
                if route.endpoint=='static': continue
                values={key:'tickets' if key=='kind' else 'csv' if key=='fmt' else 101 for key in route.arguments}
                target=str(route)
                for key,value in values.items():
                    target=target.replace('<int:'+key+'>',str(value)).replace('<'+key+'>',str(value))
                self.assertEqual(url_for(route.endpoint,**values),target)

    def test_family_order_aliases_and_real_handler_ownership(self):
        import handler_registry
        self.assertEqual(tuple(self.runtime._handler_families),handler_registry.FAMILIES)
        for group in handler_registry.FAMILIES:
            if group not in CONTRACT['groups']: continue
            for name in CONTRACT['groups'][group]:
                function=getattr(self.runtime,name)
                self.assertEqual(inspect.unwrap(function).__module__,'handlers.'+group)
            module=importlib.import_module('handlers.'+group)
            self.assertNotIn('runtime',vars(module))
        for path,name,methods in handler_registry.CORE_ROUTES:
            self.assertIs(self.app.view_functions[name],getattr(self.runtime,name))

    def test_extracted_function_asts_and_exporter_registry_preserved(self):
        import handler_registry
        for group in handler_registry.FAMILIES:
            if group not in CONTRACT['groups']: continue
            tree=ast.parse((ROOT/'handlers'/(group+'.py')).read_text(encoding='utf-8'))
            register=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='register')
            found={n.name:n for n in register.body if isinstance(n,ast.FunctionDef)}
            self.assertEqual(set(found),set(CONTRACT['groups'][group]))
            for name,node in found.items():
                normalized=Unbind().visit(node)
                self.assertEqual(fingerprint(normalized),CONTRACT['function_ast_sha256'][name],name)
            if group=='read':
                exporter=next(n for n in register.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Attribute) and t.attr=='EXPORTERS' for t in n.targets))
                self.assertEqual(fingerprint(Unbind().visit(exporter)),CONTRACT['exporters_ast_sha256'])

    def test_duplicate_family_refuses_before_mutating_aliases_or_data(self):
        from handler_registry import register_family
        before=list(self.app.url_map.iter_rules()); function=self.runtime.dashboard
        data=self.rows('SELECT * FROM tickets ORDER BY id')
        with self.assertRaises(RuntimeError): register_family(self.runtime,'read')
        self.assertEqual(list(self.app.url_map.iter_rules()),before)
        self.assertIs(self.runtime.dashboard,function)
        self.assertEqual(self.rows('SELECT * FROM tickets ORDER BY id'),data)

    def test_duplicate_core_registration_refuses_without_partial_rules(self):
        from handler_registry import register_core_routes
        before=list(self.app.url_map.iter_rules())
        with self.assertRaises(RuntimeError): register_core_routes(self.app,vars(self.runtime))
        self.assertEqual(list(self.app.url_map.iter_rules()),before)

    def test_missing_handler_is_rejected_before_any_route_registration(self):
        from handler_registry import register_core_routes,CORE_ROUTES
        app=Flask('synthetic-registration',root_path=str(ROOT))
        namespace=dict(vars(self.runtime)); namespace.pop(CORE_ROUTES[-1][1])
        before=list(app.url_map.iter_rules())
        with self.assertRaises(RuntimeError): register_core_routes(app,namespace)
        self.assertEqual(list(app.url_map.iter_rules()),before)

    def test_instances_have_own_bindings_exports_and_cookies(self):
        second=self.make('two'); other=second.extensions['openitsm']['runtime']
        self.assertIsNot(self.runtime._handler_families,other._handler_families)
        self.assertIsNot(self.runtime.EXPORTERS,other.EXPORTERS)
        for name in ('dashboard','tickets','export_tickets'):
            self.assertIsNot(getattr(self.runtime,name),getattr(other,name))
            self.assertIs(inspect.getclosurevars(inspect.unwrap(getattr(self.runtime,name))).nonlocals['runtime'],self.runtime)
            self.assertIs(inspect.getclosurevars(inspect.unwrap(getattr(other,name))).nonlocals['runtime'],other)
        self.actor()
        self.client.get('/tickets')
        cookie=self.client.get_cookie('session').value
        client=second.test_client(); client.set_cookie('session',cookie)
        self.assertIn('/login',client.get('/tickets').location)

    def test_moved_handlers_keep_late_bound_policy_and_audit_dependencies(self):
        self.actor()
        with patch.object(self.runtime,'ticket_scope_sql',return_value=('0=1',[])):
            self.assertNotIn(b'SYNTHETIC_LOCAL_READ',self.client.get('/tickets').data)
        with patch.object(self.runtime,'audit',wraps=self.runtime.audit) as audit:
            response=self.client.get('/reports/export/tickets/csv')
            self.assertEqual(response.status_code,200)
            self.assertIn(b'SYNTHETIC_LOCAL_READ',response.data)
            self.assertNotIn(b'FOREIGN_HANDLER_SECRET',response.data)
            self.assertEqual(audit.call_args.args,('Export','Report',0))

    def test_read_and_export_payloads_do_not_leak_foreign_objects(self):
        self.actor()
        for path in ('/tickets','/reports/export/tickets/csv'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertIn(b'SYNTHETIC_LOCAL_READ',response.data)
            self.assertNotIn(b'FOREIGN_HANDLER_SECRET',response.data)
        self.assertEqual(self.client.get('/tickets/102').status_code,403)

    def test_post_csrf_foreign_denial_and_own_comment_contract(self):
        self.actor(); before=self.rows('SELECT * FROM timeline')
        response=self.client.post('/tickets/101',data=dict(action='comment',comment='Synthetic no token'))
        self.assertEqual(response.status_code,403); self.assertEqual(self.rows('SELECT * FROM timeline'),before)
        response=self.client.post('/tickets/102',data=dict(csrf_token='synthetic-handler-token',action='comment',comment='Synthetic forged foreign'))
        self.assertEqual(response.status_code,403); self.assertEqual(self.rows('SELECT * FROM timeline'),before)
        response=self.client.post('/tickets/101',data=dict(csrf_token='synthetic-handler-token',action='comment',comment='Synthetic accepted own'))
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.rows("SELECT ticket_id FROM timeline WHERE details='Synthetic accepted own'"),[(101,)])

    def test_registered_mutation_keeps_transaction_failure_rollback(self):
        self.actor(); before=self.rows('SELECT * FROM timeline')
        with patch.object(self.runtime,'commit_request_connection',side_effect=sqlite3.OperationalError('Synthetic commit failure')),self.assertLogs(self.app.logger,level='ERROR'):
            response=self.client.post('/tickets/101',data=dict(csrf_token='synthetic-handler-token',action='comment',comment='Synthetic rollback'))
        self.assertEqual(response.status_code,503); self.assertEqual(self.rows('SELECT * FROM timeline'),before)
        self.assertEqual(self.rows("SELECT id FROM audit WHERE action='Comment'"),[])
        with self.client.session_transaction() as session: self.assertNotIn('uid',session)

    def test_static_root_and_template_contract_stay_compatible(self):
        self.assertEqual(Path(self.app.root_path),ROOT)
        response=self.client.get('/static/chat.js'); self.assertEqual(response.status_code,200)
        self.assertEqual(response.data,(ROOT/'static/chat.js').read_bytes())
        response.close()
        self.actor()
        response=self.client.get('/tickets/101')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'SYNTHETIC_LOCAL_READ',response.data)
