# P1-03 database lifecycle and request transaction contract

P1-03 extracts the established lifecycle, proxy, audit staging and post-commit dispatch into database.py. It preserves the 154-test baseline and adds 14 targeted contracts. There is no schema/dependency migration, authorization change, handler extraction or new migration runner. See [P1-03 evidence](../VALIDATION.md).

## Components and ownership

Each factory instance exposes its own Database at app.extensions['openitsm']['database']. The transitional runtime keeps thin db(), teardown, finish and mail-dispatch adapters so existing handlers/helper patches continue to work. The commit_request_connection shim remains injectable for the existing fault tests.

Database owns:
- SQLite construction: timeout 15, Row results, foreign-key enforcement and WAL.
- Startup raw-connection tracking and finally cleanup, including failed initialization.
- RequestConnection proxy, per-request state, audit metadata and callback queues.
- Successful commit, denial rollback/security replay, error response and teardown.
- Clean-context background dispatch after successful commit.

RequestState is attached to the concrete Flask Request, keyed by its Database owner, rather than to shared application-context g. Nested same-application requests have independent connections/callbacks; inner teardown cannot close outer work. Cross-application request use fails closed. During factory schema initialization, connections are always raw for the new instance, so constructing an instance under another active request cannot borrow its connection. Construction remains an application-setup operation; dynamic per-request app creation is not an architectural recommendation.

## Raw versus request connections

Outside a request, connection()/the legacy db() returns a raw SQLite connection. Its caller explicitly commits or closes; close without commit rolls back. Startup raw connections are also closed by finish_initialization in the factory finally path.

Inside the matching request, the same RequestConnection is returned on repeated calls. commit()/close() defer to the response boundary. rollback() rolls back business work and clears that request's staged audit/callbacks, allowing fresh work before the response. PRAGMA/open failure closes the new handle.

This manages the application's db() lifecycle. Existing special read-only preflight and SQLite backup-copy connections retain their explicit local lifecycle; they are not silently converted into request transactions. Versioned migration/bootstrap redesign remains P1-04.

## Completion and failure behavior

For responses below 400, the transaction hook commits domain and audit SQL together, then invokes callbacks. For 400+, it rolls back domain writes and replays only staged AccessDenied, LoginFailed and PasswordChangeFailed events. An explicit rollback clears these staged records too.

Commit/security-replay failure returns generic 503, clears session, suppresses callbacks and attempts rollback. Teardown closes the connection even if explicit rollback raises; connection close remains the final SQLite rollback boundary. Handler exceptions that bypass response finalization still trigger teardown rollback/closure.

A request is finalized once. Callbacks without a DB connection run only on success and are not duplicated by repeated finalization. Callback failure is logged, does not undo committed work, and does not skip later callbacks. Callbacks must not add new writes/queues to a finalized request transaction; the component rejects that use.

Mail dispatch queues a thread launch until commit, then runs with a fresh contextvars.Context. Background work gets a raw connection rather than inherited Flask request state. Outside a request, dispatch remains immediate. This is best effort, not a durable outbox, exactly-once delivery, retry scheduler or worker shutdown system.

## Verification

Fourteen new synthetic tests cover raw commit/close, deferred proxy visibility/teardown, 2xx/3xx/4xx/5xx behavior, audit filtering, commit/security replay failures, explicit rollback, callback errors/no-DB/idempotency, actual clean-context worker visibility, concurrent requests, nested same-app state, cross-app construction/ownership, PRAGMA failure cleanup, exception/rollback-failure teardown, and pure module import.

The complete required suite is 168 identities: 154 unchanged baseline tests plus these 14. Actual counts, source hashes and route/content parity are recorded in the package report/manifest; old Phase 0 and P1-02 evidence remain historical.

Scope remains one process/direct HTTPS/local SQLite under [Phase 0 boundaries](../PHASE_0_SCOPE.md). Power-loss/disk durability permutations, multi-process/proxy/network storage, durable external mail and real site deployment remain unverified. No P1-04/P1-05 implementation or publication is included.

P1-04 update: read-only preflight and schema/bootstrap upgrade now belong to migrations.py, with one separate atomic maintenance transaction before runtime startup. The request transaction/ownership and post-commit contracts above are unchanged. See [migration/recovery contracts](P1_04_MIGRATIONS.md).
