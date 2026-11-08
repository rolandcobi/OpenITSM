# P1-04 explicit schema-v1 migration contract and recovery procedure

P1-04 extracts schema/bootstrap work from runtime and module initialization into migrations.py and migration_steps.py. There is no new schema version or ledger: target remains PRAGMA user_version=1. [P1-04 report](../VALIDATION.md) records actual tests and acceptance; [Phase 0 scope](../PHASE_0_SCOPE.md) remains the support boundary.

## Version inventory and entry points

Supported inputs remain the four frozen Git schema snapshots and declared additive partial states. schema_v1.json freezes table/column and explicit index/trigger metadata from accepted checkpoint 9f8fef0, using a temporary synthetic database before extraction. It contains no records or credentials. It validates the completed v1 contract; it is not a new historical-data fixture or proof of arbitrary-fork compatibility.

The ordered v1 steps are 0001_core, 0001_organization, 0001_chat and 0001_workspace. Core bootstrap/catalog defaults and conservative asset classification retain the previous rules. No ticket backfill or visibility policy is newly introduced.

- inspect_database(path, target=1): read-only plan/check; no file creation, seed or repair.
- run_migrations(path, bootstrap_password='', target=1): explicit apply. Existing valid v1 is read-only and does not rerun steps, seed missing groups or reclassify NULL-unit assets.
- create_app: validates application settings and delegates to the runner before loading runtime/registering modules or starting workers. This preserves legacy automatic bootstrap/upgrade compatibility; there is now one runner rather than scattered startup DDL.
- org/space/chat init: route/helper registration only, no schema writes. Legacy runtime preflight_db()/init_db() are delegates for compatibility.
- CLI maintenance, using the existing interpreter:

```powershell
.venv\Scripts\python.exe migrations.py --database C:\Evaluation\synthetic.sqlite --check
.venv\Scripts\python.exe migrations.py --database C:\Evaluation\synthetic.sqlite --apply
```

Paths above are examples, not actions executed on a site. Apply requires an explicitly provisioned ITSM_INITIAL_ADMIN_PASSWORD of at least 12 characters only for a database needing bootstrap. CLI does not create an application, serve HTTP, resolve session secrets or start workers. Modes --check/--apply are mutually exclusive and explicit. --target accepts only 1; there is no downgrade operation. Local file paths only: memory/URI/network deployment modes are not certified.

## Transaction and audit guarantees

Read-only preflight checks integrity, allowed version and existing core columns. Completed v1 additionally requires the accepted tables/columns and explicit indexes/immutable-audit trigger definitions, plus foreign-key consistency. A future/corrupt/incompatible/incomplete v1 is refused before writer opening; no silent repair or marker reset.

An upgrade obtains BEGIN IMMEDIATE on one connection, rechecks under the writer reservation and executes all DDL/data steps in that transaction. Scripts are split using SQLite complete_statement and executed without executescript's implicit commit. The SQL authorizer blocks transaction/savepoint/attach controls and premature protected PRAGMA writes from inside steps, including controls hidden behind comments. The runner alone advances the marker and commits once after all checks pass.

Existing audit rows must remain exactly unchanged. Audit UPDATE/DELETE triggers remain equivalent to the accepted definitions. A migration that edits or appends application audit history is refused and rolled back; migration execution evidence belongs in maintenance logs/manifests, not fabricated business audit events. Domain/role changes, staged audit inserts and the schema marker roll back together on tested step/commit failures. No privilege is granted just to enable migration.

The runner releases the connection/lock in finally. It does not change P1-03 request/audit/callback semantics or dispatch external notifications. Startup workers cannot run before a validated completed schema. For an actual v0 upgrade the runner prepares WAL after preflight and before BEGIN, because SQLite journal transitions cannot occur inside that transaction. Schema/data/audit/marker rollback is atomic; journal metadata can remain WAL after a failed upgrade. Valid-v1 CLI inspection/apply remain read-only. Factory separately calls prepare_application_storage to ensure WAL before first requests, including a v1 file restored in DELETE mode. This may change journal metadata without running schema/seed/backfill. Same-process factory/maintenance calls are serialized by canonical-path locks before journal transitions; SQLite still controls writer reservations and cross-process refusal.

A completed v1 restart performs checks but no schema/seed/backfill write. Missing required v1 objects cause a refusal, not an automatic trigger/index rebuild. SQLite lock timeout is bounded (two seconds); a writer lock can cause a safe refusal. The concurrent-runner test proves stale-plan recheck/serialization for two controlled maintenance calls, not supported multi-process application deployment.

## Offline backup, apply and recovery

1. Identify the source application/schema and retain a reviewable code/configuration checkpoint. Unknown forks are not certified merely because some columns match.
2. Stop the application and all writers before a real migration/restore. Create and verify a consistent SQLite backup with the SQLite backup API, including WAL state; do not copy only a live main database file.
3. Verify integrity, foreign-key checks, expected synthetic/anonymized records/access, immutable audit and secret availability on a supported copy. Preserve stable secrets for cookie/SMTP encryption behavior; never store real secrets in evidence.
4. Run --check, review the planned version/steps and provision bootstrap only when needed. Then run explicit --apply on the authorized copy/site during a separate maintenance action.
5. If apply fails, retain the error and verify the previous version/logical state before retry. Never force user_version, delete audit triggers or skip a failed step to obtain a green marker.
6. If recovery requires restore, keep writers stopped, restore the verified snapshot and matching approved application/configuration, then validate and reapply the supported upgrade. Do not run obsolete binaries over an upgraded file or restore over a running database. Writes after the snapshot may be lost; define that operational recovery window before a real deployment.

This task executed these procedures only against temporary synthetic files. No real site backup, migration, restore or deployment was performed.

## Evidence and limits

Sixteen new tests exercise read-only/no-create plans, fresh step/marker ordering, v1 byte-preserving no-op/no-backfill, failure after every step, commit failure/lock release, forbidden transaction/marker controls, audit tampering refusal, inconsistent v1 refusal, foreign-key refusal, all four snapshot restore/re-upgrades, locked recovery, controlled concurrent calls, CLI behavior, pre-worker factory refusal and pre-request WAL readiness for fresh/restored databases. The prior 168 identities remain required.

This is a finite fault contract, not universal disk/power-loss/failover certification. Multi-process application operation, arbitrary schemas/data, real site grants/certificates/SMTP, network SQLite, durable external jobs and production capacity remain outside verified scope. P1-05 handler extraction is not part of P1-04.
