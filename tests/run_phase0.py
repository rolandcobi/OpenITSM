"""Run isolated Phase 0 tests and record their actual results and route inventory."""
import json
from pathlib import Path
import sys
import unittest
from importlib.metadata import version

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
def test_ids(node):
    if isinstance(node,unittest.TestSuite):
        return [name for child in node for name in test_ids(child)]
    return [node.id()]
executed_names=test_ids(suite)
with (root / 'phase0-test-results.txt').open('w', encoding='utf-8') as log:
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
from test_phase0_http import Phase0HTTP
routes = [dict(route=str(r), methods=sorted(set(r.methods)-{'HEAD', 'OPTIONS'}), handler=r.endpoint)
          for r in Phase0HTTP.m.app.url_map.iter_rules() if r.endpoint != 'static']
data = dict(test_names=executed_names,tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
            skipped=len(result.skipped), expected_failures=len(result.expectedFailures),
            unexpected_successes=len(result.unexpectedSuccesses), python=sys.version.split()[0],
            flask=version('flask'),packages={name:version(name) for name in ('cheroot','cryptography','werkzeug')}, routes=routes, get_matrix=Phase0HTTP.http_matrix, runtime_evidence=Phase0HTTP.runtime_evidence)
(root / 'phase0-http-results.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
print(json.dumps({k:v for k,v in data.items() if k not in ('routes','get_matrix','runtime_evidence','test_names')}))
print('Routes:', len(routes), 'GET role/mode observations:', len(data['get_matrix']))
sys.exit(not result.wasSuccessful())
