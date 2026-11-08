"""Pure discovery/reporting helpers for explicit isolated suite commands."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime,timezone
from importlib.metadata import version

ROOT=Path(__file__).resolve().parents[1]
SUITES=('policy','http','migration','browser','runtime','compatibility','tooling','all')
BROWSER_TEST='test_phase0_http.Phase0HTTP.test_b08_edge_and_chrome_real_browser_csrf_cookie_and_read_flows'
RUNTIME_TESTS=frozenset((
 'test_phase0_http.Phase0HTTP.test_b08_controlled_tls_smtp_success_and_failure',
 'test_phase0_http.Phase0HTTP.test_b08_real_tls_thread_workers_preserve_scope'))
BROWSER_PATHS={
 'Edge':Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'),
 'Chrome':Path('C:/Program Files/Google/Chrome/Application/chrome.exe')}

def inventory():
    return json.loads((ROOT/'tests/fixtures/p1_06_test_inventory.json').read_text(encoding='utf-8'))

def classify(name):
    module=name.split('.')[0]
    if name==BROWSER_TEST: return 'browser'
    if name in RUNTIME_TESTS: return 'runtime'
    if module in ('test_directory_edit_policy','test_ticket_policy','test_phase0_sql'): return 'policy'
    if module in ('test_phase0_migrations','test_p1_04_migrations'): return 'migration'
    if module in ('test_p1_02_factory','test_p1_03_database','test_p1_05_handlers'): return 'compatibility'
    if module in ('test_phase0_http','test_english_ui'): return 'http'
    if module=='test_p1_06_runner': return 'tooling'
    raise ValueError('Unclassified test identity: '+name)

def flatten(node):
    if isinstance(node,unittest.TestSuite):
        return [case for child in node for case in flatten(child)]
    return [node]

def discover():
    if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
    cases=flatten(unittest.defaultTestLoader.discover(str(ROOT/'tests')))
    names=[case.id() for case in cases]
    if len(names)!=len(set(names)): raise ValueError('Duplicate discovered test identity')
    for name in names: classify(name)
    missing=set(inventory()['baseline_test_names'])-set(names)
    if missing: raise ValueError('Missing accepted test identities: '+', '.join(sorted(missing)))
    return cases

def baseline_sources():
    expected=inventory()['baseline_test_source_sha256']
    return all((ROOT/name).is_file() and hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest for name,digest in expected.items())

def browser_prerequisites():
    return [name+': '+str(path) for name,path in BROWSER_PATHS.items() if not path.is_file()]

def prepare_output(path):
    requested=Path(path).absolute()
    resolved=requested.resolve()
    if any(p in ('.git','.venv','venv','__pycache__') for p in requested.parts+resolved.parts):
        raise ValueError('Output must not be in Git/venv/cache paths')
    if resolved==ROOT or resolved==Path(sys.prefix).resolve():
        raise ValueError('Output must be a separate empty directory')
    if resolved.is_relative_to(ROOT) and resolved.relative_to(ROOT).parts[0] not in ('test-results','evidence'):
        raise ValueError('Repository output must be under test-results or evidence')
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise ValueError('Output directory must be empty; no overwrite is supported')
    resolved.mkdir(parents=True,exist_ok=True)
    return resolved

class RecordingResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.executed=[]
    def startTest(self,test):
        self.executed.append(test.id())
        super().startTest(test)

def collect_metadata(selected, suite):
    app=None; matrix=[]; evidence=[]; source='not_executed'
    if any(n.startswith('test_phase0_http.') for n in selected):
        module=sys.modules.get('test_phase0_http')
        fixture=getattr(module,'Phase0HTTP',None)
        runtime=getattr(fixture,'m',None)
        if runtime is not None:
            app=runtime.app
            matrix=list(fixture.http_matrix); evidence=list(fixture.runtime_evidence)
            source='executed_isolated_http_fixture'
    if app is None and suite=='compatibility':
        # Inventory probe is explicit and synthetic, never default import app.
        from application import create_app
        with tempfile.TemporaryDirectory(prefix='openitsm-suite-inventory-') as tmp:
            app=create_app(dict(ITSM_ENV='test',ITSM_DB=str(Path(tmp)/'probe.sqlite'),
                ITSM_SECRET_KEY='synthetic-suite-probe-'*4,ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345',
                ITSM_BACKUP='0',TESTING=True),environ={},backup_dir=Path(tmp)/'backups')
            source='post_suite_synthetic_inventory_probe'
    routes=None if app is None else [dict(route=str(r),methods=sorted(set(r.methods)-{'HEAD','OPTIONS'}),handler=r.endpoint) for r in app.url_map.iter_rules() if r.endpoint!='static']
    return dict(routes=routes,get_matrix=matrix,runtime_evidence=evidence,inventory_source=source)

def compatibility_checks(suite, metadata):
    expected=inventory()
    routes=metadata.get('routes')
    checks=dict(routes='NOT_EXECUTED' if routes is None else 'PASS' if routes==expected['routes'] else 'FAIL',
        get_matrix='NOT_EXECUTED',browser='NOT_EXECUTED',smtp_tls='NOT_EXECUTED',tls_workers='NOT_EXECUTED')
    if suite in ('all','http'):
        checks['get_matrix']='PASS' if [list(row) for row in metadata.get('get_matrix',[])]==expected['get_matrix'] else 'FAIL'
    evidence=metadata.get('runtime_evidence',[])
    if suite in ('all','browser'):
        browser={e.get('browser'):e for e in evidence if e.get('kind')=='browser'}
        checks['browser']='PASS' if all(browser.get(name,{}).get('ok') is True and browser[name].get('userAgent') for name in ('Edge','Chrome')) else 'FAIL'
    if suite in ('all','runtime'):
        smtp=[e for e in evidence if e.get('kind')=='smtp_tls']
        checks['smtp_tls']='PASS' if any(e.get('accepted')==2 and e.get('refused')==1 and e.get('background') is True and e.get('certificate_verified') is True for e in smtp) else 'FAIL'
        workers={e.get('threads'):e for e in evidence if e.get('kind')=='tls_workers'}
        checks['tls_workers']='PASS' if all(workers.get(n,{}).get('requests')==16 and workers[n].get('allowed')==8 and workers[n].get('denied')==8 and workers[n].get('certificate_verified') is True for n in (1,4,16)) else 'FAIL'
    return checks

def assess(suite, selected, executed, counts, checks, sources_ok):
    complete=len(selected)==len(executed) and set(selected)==set(executed) and len(executed)==len(set(executed))
    clean=counts['tests']==len(selected) and counts['tests']>0 and all(counts[k]==0 for k in ('failures','errors','skipped','expected_failures','unexpected_successes'))
    required={'all':('routes','get_matrix','browser','smtp_tls','tls_workers'),
        'http':('routes','get_matrix'),'browser':('routes','browser'),
        'runtime':('routes','smtp_tls','tls_workers'),'compatibility':('routes',)}.get(suite,())
    passed=complete and clean and sources_ok and 'FAIL' not in checks.values() and all(checks.get(k)=='PASS' for k in required)
    full=passed and suite=='all' and set(inventory()['baseline_test_names']).issubset(executed) and all(v=='PASS' for v in checks.values())
    return dict(status='PASS' if passed else 'FAIL',full_gate=full,all_selected_executed=complete)

def save_result(output, data):
    with (output/'results.json').open('x',encoding='utf-8') as stream:
        json.dump(data,stream,indent=2); stream.write('\n')

def main(argv=None):
    parser=argparse.ArgumentParser(description='OpenITSM named suites; subsets never certify the full gate')
    parser.add_argument('--suite',choices=SUITES,required=True)
    parser.add_argument('--list',action='store_true')
    parser.add_argument('--output-dir')
    args=parser.parse_args(argv)
    if not args.list and not args.output_dir:
        parser.error('--output-dir is required for execution')
    output=None; selected=[]; all_names=[]; data={}
    started=datetime.now(timezone.utc).isoformat()
    try:
        if not args.list: output=prepare_output(args.output_dir)
        cases=discover(); all_names=[case.id() for case in cases]
        chosen=[case for case in cases if args.suite=='all' or classify(case.id())==args.suite]
        selected=[case.id() for case in chosen]
        groups={name:sum(classify(test)==name for test in all_names) for name in SUITES if name!='all'}
        if args.list:
            print(json.dumps(dict(suite=args.suite,execution='NOT_RUN',full_gate=False,test_names=selected,tests=len(selected),discovered_partition=groups)))
            return 0
        data=dict(schema_version=1,suite=args.suite,started_at_utc=started,python=sys.version.split()[0],
            selected_test_names=selected,discovered_test_names=all_names,discovered_partition=groups,
            executed_test_names=[],tests=0,failures=0,errors=0,skipped=0,expected_failures=0,unexpected_successes=0,
            full_gate=False,baseline_test_sources_preserved=baseline_sources())
        missing=browser_prerequisites() if args.suite in ('all','browser') else []
        if missing:
            data.update(status='NOT_EXECUTED',reason='Required browser prerequisites missing',missing_prerequisites=missing,not_executed=selected,completed_at_utc=datetime.now(timezone.utc).isoformat())
            (output/'test-results.txt').write_text('NOT_EXECUTED: required browser prerequisites missing\n'+'\n'.join(missing)+'\n',encoding='utf-8')
            save_result(output,data); print(json.dumps(dict(status=data['status'],full_gate=False,tests=0,missing_prerequisites=missing)))
            return 2
        if not data['baseline_test_sources_preserved']:
            data.update(status='NOT_EXECUTED',reason='Accepted baseline test sources changed',not_executed=selected)
            (output/'test-results.txt').write_text(data['reason']+'\n',encoding='utf-8')
            save_result(output,data); return 2
        clock=time.monotonic()
        with (output/'test-results.txt').open('x',encoding='utf-8') as log:
            result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=RecordingResult).run(unittest.TestSuite(chosen))
        data.update(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
            skipped=len(result.skipped),expected_failures=len(result.expectedFailures),unexpected_successes=len(result.unexpectedSuccesses),
            executed_test_names=result.executed,not_executed=sorted(set(selected)-set(result.executed)),
            seconds=round(time.monotonic()-clock,3),completed_at_utc=datetime.now(timezone.utc).isoformat())
        metadata=collect_metadata(selected,args.suite); checks=compatibility_checks(args.suite,metadata)
        counts={k:data[k] for k in ('tests','failures','errors','skipped','expected_failures','unexpected_successes')}
        sources_ok=baseline_sources()
        data.update(metadata=metadata,compatibility=checks,baseline_test_sources_preserved=sources_ok)
        data.update(assess(args.suite,selected,result.executed,counts,checks,sources_ok))
        data['packages']={n:version(n) for n in ('flask','werkzeug','cheroot','cryptography')}
        save_result(output,data)
        print(json.dumps({k:data[k] for k in ('suite','status','full_gate','tests','failures','errors','skipped')}))
        return 0 if data['status']=='PASS' else 1
    except Exception as error:
        if output is not None and not (output/'results.json').exists():
            data.setdefault('tests',0); data.setdefault('executed_test_names',[])
            data.update(schema_version=1,suite=args.suite,status='ERROR',full_gate=False,
                selected_test_names=selected,not_executed=sorted(set(selected)-set(data['executed_test_names'])),
                reason=str(error),started_at_utc=started)
            if not (output/'test-results.txt').exists(): (output/'test-results.txt').write_text('ERROR: '+str(error)+'\n',encoding='utf-8')
            save_result(output,data)
        print('ERROR: '+str(error),file=sys.stderr)
        return 2
