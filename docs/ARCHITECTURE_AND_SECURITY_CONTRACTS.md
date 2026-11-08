# Architecture and security contracts

Current Phase 1 handover snapshot. The role, scope, CSRF/session, transaction and export contracts below remain binding. See [factory](P1_02_FACTORY.md), [database](P1_03_DATABASE.md), [migrations](P1_04_MIGRATIONS.md), [handlers](P1_05_HANDLERS.md), [testing](P1_06_TESTING.md) and [operational runbook](P1_07_RUNBOOK.md). Historical package reports retain their original outcomes; [the final report](../VALIDATION.md) gives separate closure/publication decisions.

## Responsibility map

| Component | Current responsibility / boundary |
|---|---|
| app.py | Legacy default factory/import/server adapter; explicit import initializes configured storage/workers. |
| application.py / app_config.py | Pure helper imports, explicit isolated factory, immutable settings, secret/config validation and controlled backup startup. |
| _application_runtime.py | Per-instance transitional helpers, request/security hooks, SMTP/backup and server entry; not a fully decomposed service layer. |
| database.py | Connection ownership, deferred request commit/rollback, staged audit, post-commit callbacks and teardown. |
| migrations.py / migration_steps.py / schema_v1.json | Read-only inspection, atomic ordered upgrade, accepted schema-v1 validation and pre-request WAL readiness. |
| handlers/ / handler_registry.py | Core handler families and explicit org/chat/workspace adapters; original public URL order and endpoint names. |
| authorization.py | Shared parameterized scope/delegation/admin-target predicates. Historical broad names/comments do not grant global access. |
| org.py / chat.py / space.py | Existing hierarchy, bilateral chat and workspace helpers/routes; initialization registers handlers without DDL. |
| templates/, static/ | Existing rendered data, forms and chat client; server authorization and CSRF remain authoritative. |
| tests/ | Disjoint named suites, complete/legacy runners and frozen schema/identity/handler contracts using synthetic temporary data. |

## Actual startup and import order

1. Importing application/app_config/database/migration/handler helper modules alone does not initialize application storage or workers. Legacy app import explicitly constructs its default instance.
2. create_app validates an immutable configuration snapshot, resolves the stable secret and delegates to the migration runner before runtime/workers. Invalid production settings refuse early.
3. The runner checks existing state and applies supported v0/fresh upgrades in one writer transaction, validating audit/schema/foreign keys before the final version-1 marker. Completed valid v1 does not rerun seeds or backfill.
4. Factory prepares local WAL before requests, constructs a unique runtime namespace and binds the owning database, helpers, hooks and handler families in preserved URL order. Organization/chat/workspace registration performs no schema writes.
5. Startup connections close on completion/failure. Backup startup, when enabled, occurs only after validated schema and route initialization, once per instance. TESTING suppresses automatic workers unless explicitly enabled.
6. Direct python app.py calls the preserved runtime server entry. HTTP uses Waitress when available; accepted HTTPS uses Cheroot with 16 threads and configured certificates. Debug/missing-dependency fallbacks are not the accepted profile.

Explicit factory creation and legacy app import still have storage side effects; never use default app import for inventory or discovery against site data.

## Request and transaction contract

Current flow: CSRF validation -> typed mutation input -> authentication/session/forced-password gate -> object/action authorization -> domain writes/audit -> commit or rollback -> post-commit callbacks -> teardown.

Outside requests db() returns a raw SQLite connection with explicit commit/close. Inside a request it caches a proxy/raw pair in g; foreign-key enforcement and WAL are enabled with a 15-second connection timeout. This does not create foreign keys absent from historical schemas.

Proxy commit()/close() defer work; rollback() rolls back raw state and clears staged audit/callbacks. Apparent helper commits are not independent request transactions. Moving a helper to a raw connection can violate atomicity.

Below HTTP 400, after-request commits an active transaction and then invokes callbacks. At 400+ it rolls back business work and may persist only AccessDenied/LoginFailed/PasswordChangeFailed security events. SQLite commit failure rolls back, clears session and returns 503. Teardown rolls back unfinished work and closes raw connections. IntegrityError handling rolls back before a safe internal validation redirect.

Audit uses the same connection as domain changes; audit failure cannot leave a capability grant committed. Post-commit callback failure cannot undo committed business work. Email starts in an independent context/thread with fresh DB access: best effort, not durable/exactly-once. Startup/background raw connections are outside request atomicity.

## Role boundaries

Both visibility modes use explicit IDs/subtrees; free-text structure never grants scope. Only System Administrator is global for operational objects. Even that role cannot directly access another user's personal board.

| Role | Ticket visibility / actions |
|---|---|
| System Administrator | Global administration/delegation/capability grants; input and workflow guards still apply. |
| Central Administrator | Assigned unit/head subtree; scoped administration and staff actions, no global settings/capability grant or inheritance of broader target privileges. |
| Service Owner | Assigned unit/head subtree; staff/service actions still require ownership/capability and object scope. |
| Service Desk Manager | Assigned unit/head subtree; staff actions within scope, not global directory/tickets. |
| Operational Operator | Assigned ticket/task/workflow work; delegation additionally requires explicit ticket/target unit scope. |
| Local Administrator | Assigned unit/head subtree; eligible staff actions, no automatic global user administration or infrastructure capability. |
| Management | Assigned unit/head subtree; operationally read-only, self-service intake and scoped audit. |
| Requester | Own tickets/comments and trusted intake; no unit/assignee/chain injection. |
| Auditor | No ordinary ticket visibility; scoped audit, no operational write even with capability. Personal actions are separately authorized. |

Directory visibility is self plus explicit unit/subtree for non-system users. Edit/reset/role changes add protected-role, capability/head and foreign ticket/task/step/team grant guards. Non-head administrators cannot grant head authority even on a leaf unit. Infrastructure capability grants actions within scope, not wider scope. Unknown roles and missing object scope fail closed.

Assets use authoritative unit_id; ambiguous legacy references remain System-only. NULL-unit service metadata is shared, but private parent scope hides its child even when the child unit is NULL. Shared writes require System Administrator. Owner/participant attribution on authorized records is not directory access.

Team ownership/Lead manages, Member writes board content, Viewer reads. Personal boards are owner-only. Stale foreign memberships do not independently grant summaries/cards; team membership is not operational ticket authority. Bilateral chat history belongs to its parties, while new partners are directory-scoped.

## Sessions, reads, workflow and exports

- Every implemented POST requires session-bound CSRF through form or JSON header; identifiers, duplicates and malformed JSON validate before domain changes. Unregistered PUT/PATCH/DELETE reject.
- GET/HEAD/OPTIONS do not acknowledge chat/notifications or log out. Security logging/cookie refresh are permitted observability.
- Authentication reloads active user/role; absent/mismatched epoch rejects. Absolute expiry is eight hours, idle 30 minutes. Logout/password/reset/deactivation revoke old sessions; role change increments epoch; signing rotation has no old-cookie fallback.
- Password change uses epoch CAS. Login throttling is persistent SQLite with serialized updates/generic invalid responses. No distributed throttling or retroactive cancellation of authorized in-flight requests is claimed.
- Requester intake is server-configured; staff targets must be active/eligible and ticket/target in scope, except explicit System Administrator delegation.
- Pending signatures/open tasks block resolution/closure. Resolved permits authorized task creation/reopening without implicit parent status change; Closed denies those operations. Signature identity and parent/child binding stay server-checked.
- Audit triggers reject update/delete. List/count/filter/export scope must agree. CSV formula defense and XLSX literals persist. Audit export retains its 20,000-row cap.

## Configuration behavior

.env is not loaded automatically. Set explicit profile values in the process environment. Exact ITSM_ENV=production enables guards; development/test do not disable object authorization. TESTING is an explicit factory flag and never bypasses production guards.

| Setting | Behavior |
|---|---|
| ITSM_DB | Defaults beside app.py; explicit relative paths use working directory. |
| ITSM_SECRET_KEY | At least 32 characters, required in production; fallback secret.key outside production. Also derives SMTP encryption, so rotation needs a settings recovery/re-encryption design. |
| ITSM_INITIAL_ADMIN_PASSWORD | Minimum 12 characters, required only when bootstrapping an empty users table. |
| ITSM_TLS / ITSM_HTTPS | TLS defaults on unless 0. HTTPS=1 sets secure cookies before serving and is required in production. TLS entry also enables secure cookies. Set both explicitly. |
| ITSM_HOST | Default all interfaces for TLS, loopback for HTTP; bind explicitly. |
| PORT / ITSM_HTTPS_PORT | Defaults 5000 HTTP/redirect and 5443 HTTPS. |
| ITSM_ALLOWED_HOSTS | Comma-separated trusted request hosts, required in production; not bind/CORS/network authorization. |
| ITSM_CERT / ITSM_KEY | Configured existing files required in production; TLS stack enforces validity. |
| ITSM_CERT_HOSTS | Additional names for generated local test certificates only. |
| ITSM_DEBUG | Production refuses 1; keep 0. |
| ITSM_HTTP_REDIRECT | Defaults 1 for TLS entry; 0 disables separate HTTP listener. Redirect cannot protect credentials already sent by HTTP. |
| ITSM_THREADS | HTTP Waitress only, default 8. HTTPS Cheroot uses fixed 16. |
| ITSM_BACKUP | Defaults 1; can perform backup/start thread during import. Set 0 for isolated tests. |

SMTP settings come from admin UI/database, not SMTP_* environment variables. Production requires verified implicit TLS. Direct HTTPS with configured trusted certificate, local SQLite and one process is the reference boundary, not production approval.

Daily SQLite backups beside app.py are retained 30 days and checked hourly by a best-effort thread; same-day existing backups are not replaced. Backups start after the complete schema is validated; same-day existing snapshots remain unchanged. Restore must be verified with the matching supported schema/application, never over a live database. Arbitrary schemas, concurrent migration processes, network storage, multi-process/proxy, durable mail, power-loss and failover remain unverified/unsupported.

## Remaining seams and acceptance

P1-02 through P1-06 are implemented and P1-07 supplies handover/recovery evidence. Full business-service decomposition remains a future design choice; the transitional runtime is intentional. No external CI, deployment or Phase 2 is activated.

The [regression procedure](../TESTING.md) requires semantic allow/deny/no-write assertions, not route smoke alone. Keep source/test hashes and historical evidence; [Phase 0 scope](../PHASE_0_SCOPE.md) and engineering closure do not grant production/publication approval.
