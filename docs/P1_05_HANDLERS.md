# P1-05 handler families and registration contract

P1-05 separates handlers without adding business features, URLs or permissions. The 184 accepted identities remain required; 14 tests verify the new registration/module contracts. [P1-05 report](../VALIDATION.md) records the five sequential full gates.

## Ownership map

| Family | Owner / responsibility |
|---|---|
| Read views | handlers/read.py: dashboard, list/search/calendar/notifications/poll, reports/audit exports and their scoped helpers. |
| Ticket/task business | handlers/tickets.py: intake/detail mutations, task detail/actions, workflow/delegation helpers. Existing ticket/task list views are in read. |
| Assets/services | handlers/infrastructure.py: scoped CRUD, catalog/subsection actions. |
| Identity/administration | handlers/identity.py: login/logout/account/users/admin/directory/profile, notification acknowledgement and eligibility decorators. |
| Organization | handlers/organization.py explicitly initializes the already-separated org.py policy/handler module using this instance's dependencies. |
| Chat/workspace | handlers/collaboration.py explicitly registers the existing chat.py and space.py modules in their original order. Their policy/handler bodies are unchanged. |

51 functions/helpers and the per-instance EXPORTERS mapping move out of the transitional runtime into four core family modules. All 27 core route implementations are owned by those modules. The 11 organization/chat/workspace routes already had dedicated modules; explicit adapters integrate their registration without a redundant rewrite.

_application_runtime.py retains configuration/DB/service compatibility helpers, hooks and server entry, not inline core route handlers. Full business-service decomposition is not claimed.

## Explicit instance binding and URL compatibility

Family modules import without DB/worker creation. register(runtime) creates functions with explicit references to the owning instance namespace; no process-global current-runtime singleton is set. Each instance gets distinct functions, exporter maps and family state. Existing runtime.helper attributes remain aliases so established fault-injection/policy patching still reaches moved handlers.

This is a transitional service/dependency namespace, not a public plugin system. Private function module/qualname/globals locations change through extraction; the compatibility contract is URL/method/endpoint names, helper aliases, HTML/JSON behavior and authorization/transaction semantics.

handler_registry.py declares immutable core rules and registers them in the original order after all core functions are bound, before organization/chat/workspace registration. add_url_rule uses the original unprefixed endpoint names; url_for paths/converters and HEAD/OPTIONS behavior remain unchanged. No Blueprint name prefix is introduced.

Duplicate families, wrong family order, duplicate core installation and missing core handlers are refused. Core registration prechecks every required binding before adding rules. Failed application construction does not start workers or expose a partially built app.

Read, ticket/task, infrastructure and identity bind first. Core rules install next; organization then chat/workspace preserve the accepted final route ordering. Shared auth/CSRF/error/transaction hooks stay in their original order.

## Security boundaries preserved

There are still 38 application routes / 22 POST routes. All authorization derives from the shared existing policies; no copied broad role exception or structure-text scope is introduced. Requester intake, cross-unit/object checks, safe reads, CSRF, session revocation, audit atomicity, post-commit dispatch, export literal protection and immutable audit remain baseline contracts.

database.py, app_config.py, migration runner/steps/schema metadata, authorization.py, org.py, space.py, chat.py, templates/static and dependency declarations are unchanged from P1-04. Handler registration does not migrate data, alter the schema marker or change worker timing.

## Sequential implementation and evidence

The implementation followed five gates: read -> ticket/task -> assets/services -> users/organization -> workspace/chat. Each gate ran targeted module/behavior tests and the complete suite before the next extraction. Every gate passed 198/198, zero failures/errors/skips/expected failures/unexpected successes. This means 198 unique identities executed repeatedly, not 990 distinct coverage claims.

New tests verify pure imports, exact route order/names/methods, url_for converters, real function ownership, normalized AST parity, duplicate/missing registration refusal, paired instance/secret/cookie isolation, late-bound policy/audit seams, scoped HTML/CSV payloads, CSRF/IDOR/allowed comments, rollback and static/template roots. Existing role/mode/hierarchy/action/export/browser/TLS/SMTP/concurrency/migration cases run at every gate.

tests/fixtures/p1_05_handler_contracts.json freezes AST fingerprints, family names and route declarations from accepted commit de6a8d6. Runtime-prefix normalization allows comparison of the extracted source against the old function bodies; semantic HTTP and state assertions remain mandatory alongside it.

Implementation drivers under evidence/p1-05 are archived, pinned development tooling, not imported at application startup or test discovery. They rewrite implementation snapshots when run deliberately; do not run them in an active/user-modified worktree as a maintenance command. Production registration uses ordinary Python modules and explicit calls, not AST generation/eval.

## Limits

No P1-06 test-suite restructuring/CI activation, P1-07 deployment certification, schema/dependency upgrade, new public API, production migration, merge, push or publication is included. The bounded [Phase 0 scope](../PHASE_0_SCOPE.md) remains applicable; passing regression counts do not certify arbitrary infrastructures or every possible input combination.
