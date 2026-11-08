# P1-06 - named test commands and evidence contract

P1-06 changes test tooling only. Application code, URL registration, permissions, migrations, dependencies and the accepted 198 tests/fixtures remain unchanged. The legacy full runner remains available.

## Commands

Use the existing Windows interpreter from the checkout, with synthetic temporary databases only:

```powershell
.venv\Scripts\python.exe tests\run_suites.py --suite all --list
.venv\Scripts\python.exe tests\run_suites.py --suite policy --output-dir evidence\local-run-001\policy
.venv\Scripts\python.exe tests\run_suites.py --suite all --output-dir evidence\local-run-001\all
```

Replace policy with any level below. Use a fresh or empty output directory for every attempt; the CLI never overwrites prior evidence. Repository output is restricted to evidence/ or test-results/; source, Git, cache and virtual-environment paths are rejected. A separate explicit temporary/output directory outside the checkout is also supported. No credentials or database path are required: existing fixtures control isolation, temporary stores, loopback listeners and cleanup. Do not point tests at site databases.

| Level | Unique tests | Purpose |
|---|---:|---|
| policy | 34 | Pure policy/SQL authorization contracts |
| http | 101 | Phase 0 Flask security, mutations, scoped content and error integrity |
| migration | 23 | Seven historical migration and sixteen explicit runner/recovery contracts |
| browser | 1 | Actual Edge and Chrome HTTPS/CSRF/cookie/read flows |
| runtime | 2 | Verified loopback TLS SMTP/background and Cheroot 1/4/16 threads |
| compatibility | 37 | Factory, transaction/lifecycle and handler/URL compatibility |
| tooling | 18 | Discovery, isolation, partition, failure reporting and evidence contracts |
| all | 216 | One complete gate, not a sum inferred from separate runs |

Each identity belongs to exactly one level. The 198 accepted identities and test-source hashes are frozen from parent f22c475 in tests/fixtures/p1_06_test_inventory.json. Existing assertions/fixtures are not rewritten or fixture work shared across processes. Unknown, duplicate or missing baseline identities stop discovery. A future test module must receive an explicit classification; this deliberate maintenance step prevents silent exclusion.

## Results and failure semantics

Each execution creates results.json and test-results.txt. JSON contains selected and actually started identities, counts, not-executed identities, interpreter/packages, baseline-source preservation, observed URL/GET/runtime evidence and compatibility decisions. Class setup failures are errors with unexecuted selected tests; they cannot count as executed coverage. Reporting failures return ERROR and retain already observed execution counts.

Exit codes: 0 = selected level passed; 1 = executed tests/contracts failed; 2 = prerequisites, discovery, output or reporting prevented acceptance. A passing subset always has full_gate=false. Only all with all selected tests actually executed, all accepted identities retained, unchanged baseline tests, zero failures/errors/skips/expected failures/unexpected successes and every required compatibility witness passing can have full_gate=true. Automation must require both exit 0 and full_gate=true for the final job.

--list discovers identities without executing fixtures or importing/initializing the application; its execution=NOT_RUN and full_gate=false are never acceptance evidence. A missing Edge or Chrome executable makes browser/all NOT_EXECUTED, exit 2, tests=0 and skipped=0, with prerequisites and unexecuted identities recorded. A present but broken browser fails the real test; file existence alone cannot certify browser coverage.

Observed routes retain exact order, methods and endpoint names (38 rules / 22 POST rules). HTTP/all compare the exact 522 GET observations. Browser evidence must show both engines succeeded; runtime evidence must show verified certificates, SMTP accepted/refused/background behavior and each 1/4/16-thread worker scenario. Other levels mark these witnesses NOT_EXECUTED rather than reusing old evidence. Compatibility inventory is an explicit synthetic factory probe, not a default app import.

These witnesses supplement the existing semantic security/state assertions; neither 216 passes nor matching URL/status counts proves exhaustive security coverage.

## Legacy compatibility

```powershell
.venv\Scripts\python.exe tests\run_phase0.py
```

This existing runner is byte-for-byte unchanged and still discovers the entire suite. It overwrites the two root Phase 0 artifacts. Save their bytes before running, copy new results into a separate evidence directory even on failure, and restore the saved bytes in finally. The P1-06 verification driver demonstrates that procedure. The new named CLI writes only its explicit output directory and avoids this historical overwrite.

Historical Phase 0 reports/results are preserved. P1-06 results are separate and cannot retroactively broaden Phase 0 acceptance.

## Automation / CI plan only

No workflow, external service or scheduled job is activated by P1-06.

1. Prepare a reviewed Windows worker with the existing pinned runtime profile, both installed browsers, loopback TLS listener access and isolated writable temporary storage. Provisioning/install commands and dependency changes require separate work; no real SMTP, site credentials or site database are supplied.
2. Record source revision, dirty inventory, dependency versions and source/test/fixture hashes. Use a fresh working directory and fresh artifact path per attempt. Do not cache databases, cookies, certificates or secrets.
3. Run policy, http, migration, browser, runtime, compatibility and tooling in separate processes using the named CLI. Keep logs and JSON on failure. Browser/runtime jobs require capable Windows workers; unavailable prerequisites block acceptance rather than passing by skip. Existing fixture startup remains per process; no unsafe shared DB optimization is planned.
4. Run all in one capable environment as the final required gate. Verify exit status, status=PASS, full_gate=true, selected/executed identity parity and zero abnormal counts. Shard success alone never releases this gate.
5. Check source preservation, compile, whitespace and documentation links. Archive JSON/logs plus a manifest tied to the exact source, including unsuccessful attempts and prerequisite failures. Retain legacy full-run compatibility proof for tooling changes.
6. Report package GO/NO-GO for the declared profile. Publishing, deployment, merging and enabling CI are separate actions and are not authorized by this plan.

The current gate is Windows / one process / local SQLite / direct HTTPS. Real site grants, arbitrary historical databases, proxy/multi-process/network SQLite, SMTP AUTH at an organization relay, every-screen browser/accessibility coverage, durable jobs, other platforms and independent security certification remain outside this evidence. See ../PHASE_0_SCOPE.md and the P1-06 report.
