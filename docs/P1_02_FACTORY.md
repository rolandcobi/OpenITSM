# P1-02 application factory and configuration

P1-02 implements configuration resolution and isolated application construction only. Handler/service extraction, transaction redesign and an independent migration runner remain P1-03/P1-04/P1-05 work. Phase 0 authorization/CSRF/session/workflow/export contracts remain unchanged.

## Entry points

- Import application or app_config: definitions only, no DB, secret/backup file creation or worker startup. org/space/chat/authorization imports also remain free of initialization until called.
- application.create_app(config=None, *, environ=None, start_workers=None, backup_dir=None, secret_path=None): explicit creation validates a configuration snapshot, resolves the secret, initializes this instance's configured DB/schema and returns Flask.
- Legacy import app: intentionally creates the default instance, exposing app.app/db/audit and other helpers for existing integrations/tests. It is not the side-effect-free factory entry.
- python app.py: creates the default instance and invokes its existing server entry once. URL paths, endpoint names, templates/static root and server/thread profiles are preserved.

## Configuration isolation and validation

Known ITSM_* variables and PORT are copied from the supplied environ mapping, or os.environ by default. Explicit config overrides take precedence. The result is a read-only snapshot; later process environment changes do not change DB, SMTP production guards or server settings of existing instances. TESTING is a boolean factory option, not an environment setting. Unknown override keys and non-string environment values reject.

ITSM_ENV must be development/test/production. Configured flags must be 0 or 1; ports are 1-65535 and HTTP threads 1-1024. Secret length/sentinel and production guards remain enforced, including with TESTING=True: HTTPS/TLS, debug off, nonempty allowed hosts, existing configured certificate/key files. TLS validates certificate/key contents when serving. Test mode never bypasses production guards. DEBUG is set explicitly from the snapshot; unrelated FLASK_DEBUG cannot enable it, including in production. A required regression reproduced this before the explicit override was added.

For two isolated instances supply distinct ITSM_DB and secrets and, where needed, backup_dir/secret_path. environ={} makes test configuration independent of shell variables. Default paths and the persistent legacy secret fallback retain their existing location beside the application; separate DB paths alone do not promise separate fallback secrets/backups. The explicit directory/path options are factory arguments, not new environment variables.

No dotenv loader or arbitrary Flask security-config override has been added. Store stable secrets outside version control. Rotation still requires both cookie revocation and recovery/re-encryption of SMTP settings.

## Transitional runtime boundary

Each factory call loads _application_runtime.py with a fresh private importlib module namespace and injects only that instance's settings/secret/backup path before initialization. This preserves the legacy helpers and their patch behavior without sharing FAILS, ORG, hook closures or Flask configuration between applications. No runtime module is cached as a shared singleton for factory calls.

The legacy app import aliases its default runtime module so existing app.app and helper patch semantics remain valid. This is a compatibility seam, not a completed business-layer refactor. Use application.create_app for new integrations; do not import the private runtime directly. It rejects direct initialization without factory configuration.

During construction only, raw connections opened by schema initializers are registered and closed in finally, including failed bootstrap. This addresses the failed-startup DB handle found by a new Windows regression. The established request connection proxy/commit/rollback behavior is unchanged; there is no new schema version or migration sequence.

## Controlled workers

Backup startup now occurs after organization/chat/workspace initialization and user_version=1, rather than midway through module import. This deliberately prevents the initial backup from capturing a partially initialized startup schema. Factory initialization failure cannot start a worker.

Automatic startup requires ITSM_BACKUP=1 and, by default, TESTING=False. start_workers=False explicitly suppresses initial backup/thread startup; start_workers=True explicitly opts in. application.start_background_services(app) is guarded by an instance lock and starts enabled backup work once. A successful initial backup precedes thread start.

This is still the existing best-effort daemon backup loop, not a durable worker service or a new shutdown/recovery framework. Cross-process/concurrent migrations, network SQLite and mixed-version operation remain unsupported. Shared default directories are not tenant isolation.

## Verification and compatibility

Nine new tests cover pure helper imports, paired concurrent instances/DB/secrets/cookies, immutable config/environment snapshots, production refusal (including testing), production SMTP/cookies despite shell mutation, idempotent post-schema backup, failed-start cleanup/no worker, and the legacy script entry. Existing route/RBAC/session/CSRF/IDOR/transaction/runtime regressions remain required.

The existing representative migration test follows the schema literal to _application_runtime.py; its assertions and the four frozen Git schema fixtures are unchanged. The baseline 145 test identities are retained; nine factory identities are added. Read [P1-02 results](../VALIDATION.md) and [Phase 0 scope](../PHASE_0_SCOPE.md) for actual outcomes and unverified deployment limits.

Construction boundary: call the factory during application setup, outside active request contexts. Private runtime helpers belong to their own instance and are not a cross-application API; invoke business operations through the matching Flask request/client context. This package does not introduce dynamic per-request application creation or multi-process lifecycle support.

P1-03 update: startup connection tracking/cleanup now belongs to database.py and is invoked by the factory finally path. Request DB ownership and callback queues follow the concrete Request, not application-context globals. See [current DB contracts](P1_03_DATABASE.md); the factory configuration/entry/worker contracts above remain applicable.

P1-04 update: validated factory configuration delegates to the explicit migration runner before runtime/module registration. Module initialization no longer writes schema, and valid v1 startup never repeats seed/backfill. See [migration contracts](P1_04_MIGRATIONS.md).

P1-05 update: the isolated runtime binds dedicated handler-family modules through an explicit owning runtime reference and registers original core URL rules in order. Helper aliases remain for compatibility; no module-global current-instance singleton is introduced. See [handler contracts](P1_05_HANDLERS.md).
