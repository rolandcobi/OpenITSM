# Phase 0 support and evidence boundary

This is the scope selected for the requested B05/B08 decision. It is an acceptance boundary, not a deployment or publication. Features outside it are not certified by a green local suite.

## Historical databases (B05)

Supported upgrade inputs are SQLite file databases with the schemas frozen from these four repository revisions in `tests/fixtures/historical_schemas.json`:

| Revision | Source |
|---|---|
| `67919cc` | Supplied OpenITSM snapshot |
| `5f94be3` | Organization/directory scope continuation |
| `bcea525` | Central ticket policy continuation |
| `bca9e33` | Directory edit continuation |

The fixtures are extracted from immutable Git objects and checked in as schema-only SQL. They are not regenerated from the application under test. Synthetic records are added by the tests; no historical user records are included.

Supported operations: upgrade from these schemas, restart/reapply the additive upgrade, resume an interrupted additive column migration, classify unambiguous legacy asset units, quarantine ambiguous or invalid units, and restore a SQLite backup before retrying the upgrade. Current schema marker is `PRAGMA user_version=1`; the supplied inputs use version 0. Missing core columns, future versions, and corrupt files are refused before migration writes. Preflight checks are a safety check, not certification of every schema that happens to contain the required columns.

Rollback means stopping the application and restoring a verified database snapshot with a matching supported application version. Running an old security-obsolete application against the upgraded database is unsupported. Never restore over a running database. A site must test its own synthetic/anonymized copy if it cannot establish that its schema matches a supported snapshot. Arbitrary forks, undocumented release schemas, external databases, network-mounted SQLite, concurrent migration processes, and multi-process application startup are outside this boundary.

## Production reference profile (B08)

- One OpenITSM process on a single host with local SQLite/WAL storage. The current `run_server` HTTPS entry point uses Cheroot with **16 worker threads**; the test harness also exercises Cheroot with 1 and 4 threads and simultaneous authorized/forbidden requests. These are thread counts, not separate application processes.
- Direct HTTPS using a configured certificate/key, TLS 1.2 or later, explicit allowed hostnames, a generated secret of at least 32 characters, no debug mode, secure/HttpOnly/SameSite=Lax cookies. Public deployment requires an organization-trusted certificate; test certificates are synthetic and local.
- Set `ITSM_ENV=production`, `ITSM_SECRET_KEY`, `ITSM_HTTPS=1`, `ITSM_TLS=1`, `ITSM_DEBUG=0`, `ITSM_ALLOWED_HOSTS`, `ITSM_CERT`, and `ITSM_KEY`. Missing/invalid security settings refuse startup. Certificate files must exist; actual certificate/key validity is enforced by the TLS stack. Private key/environment access is an operator-controlled OS permission prerequisite.
- A reverse proxy, load balancer, multi-process WSGI server, multiple replicas, external identity provider, network storage, and rolling mixed-version deployments are not covered. They require separate tests before use. No proxy headers are implicitly trusted.
- Login idle-cookie lifetime is 30 minutes; authenticated sessions also have an eight-hour absolute lifetime. Epochless/pre-change cookies are rejected, so users must sign in again after this upgrade. Logout, password changes/resets and deactivation revoke older sessions. Role changes increment the epoch. Key rotation requires reauthentication; old signing keys are not retained as fallbacks.
- Lockout counters are stored in SQLite and updated under a write transaction. Tests cover concurrent failed attempts and process restart. This does not certify distributed rate limiting; the reference profile is single-process.

## Browser coverage

Windows desktop **Edge and Chrome**, using the installed Chromium builds recorded in `phase0-http-results.json`, are exercised with fresh headless profiles. The flows use real secure cookies and HTTPS: HttpOnly visibility, GET/HEAD read-only behavior, invalid/valid CSRF, notification form submission, JSON chat acknowledgement, cross-origin request rejection, logout confirmation/POST, and login through the real form endpoint.

The browser harness trusts a synthetic loopback certificate using a test-only browser flag. Certificate validation is tested separately by the HTTPS and SMTP clients using an explicit synthetic CA. This does not validate an organization's certificate chain or revocation policy. Firefox, Safari, mobile, browser extensions, visual/accessibility review, arbitrary stale-tab/navigation combinations, and every business screen are not covered by these focused tests.

## SMTP and workers

The reference mail transport is **implicit TLS** with certificate verification enabled. Production mode rejects plaintext/unverified configurations. A loopback TLS SMTP fixture exercises accepted delivery, recipient refusal, email-log outcomes and the real background dispatch helper. All addresses and content are synthetic. No organizational relay or external mailbox is contacted.

Authenticated relay policies, STARTTLS, OAuth, relay-specific throttling, bounce processing, durable queues and guaranteed delivery after process termination are not certified by this fixture. The built-in asynchronous helper is a best-effort thread, not a durable job queue. Site-specific SMTP AUTH/relay behavior needs an additional controlled test before deployment there.

The worker tests establish request isolation and expected responses under a small concurrent workload at 1/4/16 threads. They do not establish production capacity, sustained throughput, failover, or recovery guarantees.

## Authorization default selected for blocker resolution

Only System Administrator is global. Central Administrators and managers use assigned units/subtrees in both visibility modes; no free-text structure bypass remains. Requesters see their own tickets. Technicians see assigned ticket/task/step work. Auditors have scoped audit read access and cannot change tickets/assets/services, even through an infrastructure capability flag. Personal profile/account/workspace operations and own notification/chat acknowledgements remain available as separately authorized user actions.

Service metadata with a NULL unit is explicitly a shared catalog; scoped services, their subsections and owner dropdowns follow unit scope. Shared catalog owner display names are public catalog attribution, not a grant to view their directory/contact record. Shared service changes are System-Administrator-only. User administration, directory, organization overview and audit metadata are scoped. Non-system workflow/task delegation requires both the ticket unit and the active staff target to be inside the actor's unit scope. Explicit cross-unit delegation is reserved for System Administrator. Team invitations also require unit scope; stale foreign memberships do not independently grant access.

These are conservative application defaults implemented under the request to resolve the blockers. A site requesting broader access must define and test that policy rather than treating a legacy broad grant as an exception.

## Closure contracts and integrity

The reference Phase 0 acceptance profile uses all nine application roles and both visibility modes. Workspace authorization follows ownership and explicit team membership: Lead manages, Member writes board content, Viewer reads; personal boards are owner-only even against direct System Administrator access. Team ownership/membership does not grant unrelated ticket, directory or organization permissions. Existing bilateral chat history is accessible to its parties; new partners are directory-scoped. Participant display names on authorized records are purpose-bound attribution, not permission to inspect a foreign directory profile.

Central account administration cannot reset/change credentials or roles to inherit broader infrastructure capabilities, head scope, foreign ticket/task/workflow grants or team membership. Only System Administrator grants infrastructure capability. A non-head administrator cannot grant head authority even on a leaf unit. Bulk unit/service assignments validate the submitted fields, preserve protected/foreign targets, and include Requester unit assignments. Management may submit self-service intake but has no operational ticket/task write authority through legacy assignments. Auditor remains operationally read-only even with a capability flag; separately authorized personal workspace operations remain available.

Resolved tickets are reversible: authorized staff may create/reopen tasks without implicitly changing the parent ticket status. Closed tickets deny these operations. Pending workflow signatures and open tasks block direct resolution/closure. Tests explicitly assert these lifecycle rules; no workflow redesign or Phase 1 feature is included.

Request business changes and audit records commit atomically. Audit/commit failures roll back the request's changes; denied security events may still be logged. Email dispatch waits for a successful commit and uses an independent context. External delivery cannot be rolled back and the asynchronous helper is not durable. Safe GET/HEAD/OPTIONS do not change business read state; security logging and session cookie refresh are permitted observability.

The closure action matrices are finite executable contracts: 2,466 workspace cases (roles, visibility modes, membership/ownership/head relations) and 630 organization cases (all seven actions, roles/modes and five scope/head realms). Export tests verify independently expected content, mixed filters, empty/date-boundary results and audit pagination across all roles/modes. They do not claim an exhaustive Cartesian proof of arbitrary input values. The audit export retains its existing 20,000-row cap; completeness above it is not certified. See the reports and actual JSON artifact for the final acceptance evidence.
