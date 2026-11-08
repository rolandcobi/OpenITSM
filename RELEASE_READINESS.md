# Release readiness

Technical validation of the Windows OpenITSM-rc-001 source candidate passed. Public release and real production deployment remain separate decisions.

The owner is Roland Cobi; the project uses Apache-2.0. The connected GitHub account rolandcobi and existing private repository rolandcobi/OpenITSM were verified read-only during preparation. No repository setting or content was changed remotely.

This source tree is prepared for a first private upload with one fresh root commit on main. That upload requires explicit approval of the exact commit and destination before any bytes are sent.

Before a public release, complete independent source/security review, review native/dependency/third-party licensing for the actual distribution, establish and test a private vulnerability route when supported by the actual hosting visibility, and approve the exact public artifact. No public transition, tag/release, CI, Pages, deployment or external automation is activated.

The evaluated profile is Windows x64 / CPython 3.14.7, one process/direct HTTPS/local SQLite-WAL. Proxy/multi-process/network SQLite, arbitrary historical databases, complete browser/accessibility coverage, native/OS/browser advisory certification, and real site permissions/certificates/SMTP AUTH/capacity/recovery remain unverified.

See [security policy](SECURITY.md), [validation summary](VALIDATION.md), [repository plan](docs/GITHUB_REPOSITORY_PLAN.md), and [operational runbook](docs/P1_07_RUNBOOK.md).
