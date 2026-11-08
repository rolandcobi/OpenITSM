"""P1-06 runner safety/coverage contracts; no production application import."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import patch
import suite_support as support

ROOT=Path(__file__).resolve().parents[1]

class RunnerContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='openitsm-p106-')
        self.addCleanup(self.tmp.cleanup); self.folder=Path(self.tmp.name)

    def counts(self,tests=1,**extra):
        values=dict(tests=tests,failures=0,errors=0,skipped=0,expected_failures=0,unexpected_successes=0)
        values.update(extra); return values

    def metadata(self):
        base=support.inventory()
        return dict(routes=copy.deepcopy(base['routes']),get_matrix=copy.deepcopy(base['get_matrix']),
                    runtime_evidence=copy.deepcopy(base['reference_runtime_evidence']))

    def test_accepted_198_ids_form_exact_disjoint_named_partition(self):
        names=support.inventory()['baseline_test_names']; self.assertEqual(len(names),198)
        counts={name:sum(support.classify(test)==name for test in names) for name in support.SUITES if name!='all'}
        self.assertEqual(counts,dict(policy=34,http=101,migration=23,browser=1,runtime=2,compatibility=37,tooling=0))
        self.assertEqual(sum(counts.values()),198); self.assertEqual(len(set(names)),198)

    def test_unknown_identity_is_not_silently_omitted(self):
        with self.assertRaises(ValueError): support.classify('unknown.SecurityCase.test_hidden')

    def test_discovery_rejects_duplicate_ids(self):
        def case():
            class Sample(unittest.TestCase):
                def runTest(self): pass
            obj=Sample(); obj.id=lambda:support.inventory()['baseline_test_names'][0]; return obj
        with patch.object(unittest.defaultTestLoader,'discover',return_value=unittest.TestSuite([case(),case()])):
            with self.assertRaisesRegex(ValueError,'Duplicate'): support.discover()

    def test_discovery_rejects_missing_accepted_ids(self):
        with patch.object(unittest.defaultTestLoader,'discover',return_value=unittest.TestSuite()):
            with self.assertRaisesRegex(ValueError,'Missing accepted'): support.discover()

    def test_test_source_hashes_only_allow_line_ending_normalization(self):
        path=self.folder/'test_original.py'; original=b'assert True\n'
        path.write_bytes(original)
        contract=dict(baseline_test_source_sha256={'test_original.py':hashlib.sha256(original).hexdigest()})
        with patch.object(support,'ROOT',self.folder),patch.object(support,'inventory',return_value=contract):
            self.assertTrue(support.baseline_sources())
            path.write_bytes(b'assert True\r\n'); self.assertTrue(support.baseline_sources())
            path.write_bytes(b'assert False\n'); self.assertFalse(support.baseline_sources())

    def test_subset_pass_never_certifies_complete_gate(self):
        names=[support.inventory()['baseline_test_names'][0]]
        result=support.assess('policy',names,names,self.counts(),{'routes':'NOT_EXECUTED'},True)
        self.assertEqual(result['status'],'PASS'); self.assertFalse(result['full_gate'])

    def test_skips_expected_failures_errors_and_empty_execution_are_not_passes(self):
        names=[support.inventory()['baseline_test_names'][0]]
        for field in ('failures','errors','skipped','expected_failures','unexpected_successes'):
            with self.subTest(field=field):
                result=support.assess('all',names,names,self.counts(**{field:1}),{'routes':'PASS'},True)
                self.assertEqual(result['status'],'FAIL'); self.assertFalse(result['full_gate'])
        self.assertEqual(support.assess('policy',[],[],self.counts(tests=0),{},True)['status'],'FAIL')

        for suite in ('all','http','browser','runtime','compatibility'):
            with self.subTest(missing_required_evidence=suite):
                self.assertEqual(support.assess(suite,names,names,self.counts(),{},True)['status'],'FAIL')

    def test_missing_or_duplicate_executions_cannot_satisfy_coverage(self):
        names=support.inventory()['baseline_test_names'][:2]
        for executed in (names[:1],[names[0],names[0]]):
            self.assertEqual(support.assess('all',names,executed,self.counts(tests=2),{'routes':'PASS'},True)['status'],'FAIL')

    def test_url_and_get_matrix_mismatch_fail_compatibility(self):
        metadata=self.metadata()
        self.assertTrue(all(v=='PASS' for v in support.compatibility_checks('all',metadata).values()))
        metadata['routes'][0]['methods']=['GET']
        self.assertEqual(support.compatibility_checks('all',metadata)['routes'],'FAIL')
        metadata=self.metadata(); metadata['get_matrix'].pop()
        self.assertEqual(support.compatibility_checks('all',metadata)['get_matrix'],'FAIL')
        metadata=self.metadata(); metadata['get_matrix']=[tuple(r) for r in metadata['get_matrix']]
        self.assertEqual(support.compatibility_checks('all',metadata)['get_matrix'],'PASS')

    def test_required_runtime_evidence_cannot_be_inferred_from_test_counts(self):
        for kind in ('browser','smtp_tls','tls_workers'):
            metadata=self.metadata()
            metadata['runtime_evidence']=[e for e in metadata['runtime_evidence'] if e['kind']!=kind]
            key='browser' if kind=='browser' else kind
            self.assertEqual(support.compatibility_checks('all',metadata)[key],'FAIL')

    def test_output_guards_preserve_source_historical_and_existing_artifacts(self):
        for path in (ROOT,ROOT/'tests'/'new-output',ROOT/'.venv'/'new-output',ROOT/'.git'/'new-output'):
            with self.subTest(path=str(path)):
                with self.assertRaises(ValueError): support.prepare_output(path)
        existing=self.folder/'existing'; existing.mkdir(); sentinel=existing/'results.json'; sentinel.write_text('preserved')
        with self.assertRaises(ValueError): support.prepare_output(existing)
        self.assertEqual(sentinel.read_text(),'preserved')
        fresh=self.folder/'fresh'; self.assertEqual(support.prepare_output(fresh),fresh)
        self.assertTrue(fresh.is_dir())

    def test_list_command_imports_no_application_or_database(self):
        env=dict(os.environ,ITSM_DB=str(self.folder/'forbidden.sqlite'),ITSM_BACKUP='1')
        result=subprocess.run([sys.executable,str(ROOT/'tests/run_suites.py'),'--suite','all','--list'],
            cwd=ROOT,env=env,capture_output=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertEqual(data['execution'],'NOT_RUN'); self.assertFalse(data['full_gate'])
        self.assertTrue(set(support.inventory()['baseline_test_names']).issubset(data['test_names']))
        self.assertEqual(sum(data['discovered_partition'].values()),data['tests'])
        self.assertFalse((self.folder/'forbidden.sqlite').exists())

    def test_policy_cli_executes_real_subset_and_preserves_legacy_results(self):
        saved={n:(ROOT/n).read_bytes() for n in ('phase0-http-results.json','phase0-test-results.txt')}
        output=self.folder/'policy'
        result=subprocess.run([sys.executable,str(ROOT/'tests/run_suites.py'),'--suite','policy','--output-dir',str(output)],
            cwd=ROOT,capture_output=True,encoding='utf-8',timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        data=json.loads((output/'results.json').read_text())
        self.assertEqual(data['tests'],34); self.assertEqual(data['status'],'PASS')
        self.assertFalse(data['full_gate']); self.assertEqual(data['selected_test_names'],data['executed_test_names'])
        self.assertEqual(data['compatibility']['routes'],'NOT_EXECUTED')
        self.assertTrue(all((ROOT/n).read_bytes()==v for n,v in saved.items()))

    def test_missing_browser_is_not_executed_not_skipped_or_passed(self):
        output=self.folder/'missing-browser'
        fake={'Edge':self.folder/'missing-edge.exe','Chrome':self.folder/'missing-chrome.exe'}
        with patch.object(support,'BROWSER_PATHS',fake),redirect_stdout(io.StringIO()):
            code=support.main(['--suite','browser','--output-dir',str(output)])
        data=json.loads((output/'results.json').read_text())
        self.assertEqual(code,2); self.assertEqual(data['status'],'NOT_EXECUTED')
        self.assertEqual(data['tests'],0); self.assertEqual(data['skipped'],0)
        self.assertFalse(data['full_gate']); self.assertEqual(len(data['not_executed']),1)
        self.assertEqual(len(data['missing_prerequisites']),2)

    def test_discovery_failure_has_nonzero_structured_artifact(self):
        output=self.folder/'discovery-failure'
        with patch.object(support,'discover',side_effect=ValueError('Synthetic missing test')),redirect_stderr(io.StringIO()):
            code=support.main(['--suite','all','--output-dir',str(output)])
        data=json.loads((output/'results.json').read_text())
        self.assertEqual(code,2); self.assertEqual(data['status'],'ERROR')
        self.assertFalse(data['full_gate']); self.assertEqual(data['executed_test_names'],[])

        output=self.folder/'metadata-failure'
        class Sample(unittest.TestCase):
            def runTest(self): pass
        case=Sample(); case.id=lambda:'test_ticket_policy.Synthetic.test_report_failure'
        with patch.object(support,'discover',return_value=[case]),patch.object(support,'collect_metadata',side_effect=ValueError('Synthetic metadata failure')),redirect_stderr(io.StringIO()):
            code=support.main(['--suite','policy','--output-dir',str(output)])
        data=json.loads((output/'results.json').read_text())
        self.assertEqual(code,2); self.assertEqual(data['status'],'ERROR')
        self.assertEqual(data['tests'],1); self.assertEqual(data['executed_test_names'],[case.id()])
        self.assertEqual(data['not_executed'],[]); self.assertFalse(data['full_gate'])

    def test_compatibility_inventory_probe_is_explicit_and_synthetic(self):
        before={p.name:p.read_bytes() for p in ROOT.glob('*.db')}
        imported='app' in sys.modules
        with redirect_stdout(io.StringIO()): metadata=support.collect_metadata([],'compatibility')
        self.assertEqual(metadata['inventory_source'],'post_suite_synthetic_inventory_probe')
        self.assertEqual(metadata['routes'],support.inventory()['routes'])
        checks=support.compatibility_checks('compatibility',metadata)
        self.assertEqual(checks['routes'],'PASS'); self.assertEqual(checks['get_matrix'],'NOT_EXECUTED')
        self.assertEqual(before,{p.name:p.read_bytes() for p in ROOT.glob('*.db')})
        self.assertEqual('app' in sys.modules,imported)

    def test_fixture_setup_failure_is_not_reported_as_executed_tests(self):
        class Broken(unittest.TestCase):
            @classmethod
            def setUpClass(cls): raise RuntimeError('Synthetic setup failure')
            def test_never(self): self.fail('Never executes')
        selected=[Broken('test_never').id()]
        result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=support.RecordingResult).run(unittest.TestSuite([Broken('test_never')]))
        self.assertEqual(result.testsRun,0); self.assertEqual(result.executed,[])
        counts=self.counts(tests=result.testsRun,errors=len(result.errors))
        self.assertEqual(support.assess('all',selected,result.executed,counts,{},True)['status'],'FAIL')

    def test_runner_module_import_is_pure(self):
        code="""import sqlite3,threading,os
from pathlib import Path
def forbidden(*a,**k): raise AssertionError('Import side effect')
sqlite3.connect=forbidden; threading.Thread.start=forbidden
before=dict(os.environ)
import run_suites,suite_support
assert before==dict(os.environ)
assert not list(Path.cwd().iterdir())
"""
        result=subprocess.run([sys.executable,'-c',code],cwd=self.folder,
            env=dict(os.environ,PYTHONPATH=os.pathsep.join((str(ROOT/'tests'),str(ROOT)))),
            capture_output=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
