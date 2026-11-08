# Contributing to OpenITSM

OpenITSM welcomes bug reports, documentation improvements, and focused code contributions. Read the [code of conduct](CODE_OF_CONDUCT.md), [security policy](SECURITY.md), and [support guide](SUPPORT.md).

## Before contributing

Use synthetic data. Never include a site database, credentials, private keys, organizational records, personal information, or uncoordinated vulnerability details in an issue, pull request, screenshot, or log.

Report suspected vulnerabilities through the private process in SECURITY.md, rather than a public issue. Feature requests should explain the organizational problem and expected behavior without promising a delivery date.

OpenITSM is an engineering preview. Its verified profile is Windows x64 / CPython 3.14.7 with local SQLite/WAL, one process, and direct HTTPS. Broader profiles require explicit design and tests.

## Development setup

Use a fresh checkout and environment. Follow the hash-locked installation in [README.md](README.md). The application does not load .env automatically; use temporary databases and synthetic secrets. Importing app initializes configured storage.

Keep dependency upgrades separate from refactoring or functional changes. The locks describe the validated Windows/Python environment. Other platform support is not established by removing hashes.

## Changes and regression evidence

Keep each change focused. Describe the trigger, resulting behavior, security implications, and verification. Preserve unrelated local edits.

For application changes, retain the accepted tests and add meaningful regression cases where behavior changes. Preserve role/unit/object boundaries, CSRF, session revocation, immutable audit, and atomic business/audit writes. New actions need allow/deny/no-write assertions, not only status checks.

Run the relevant named suite and the required complete gate; see [testing contracts](docs/P1_06_TESTING.md). The full gate requires actual browser/TLS/SMTP evidence and a capable environment. Missing prerequisites must be reported as unexecuted. A passing subset is not full acceptance.

For documentation-only changes, check links, spelling, examples, and artifact preservation; explain why application tests were not rerun. Never describe old test results as a new execution.

Do not import the default app for route discovery against site data. Preserve root historical result files if using the legacy runner.

## Pull requests

Use the pull request template, state what changed and why, list actual validation and remaining limits, and disclose schema/configuration/permission changes. Do not merge or publish on behalf of maintainers.

Changes to the frozen OpenITSM-rc-001 ZIP require a separate candidate/version and verification. Community documentation can evolve separately, but must not change that archive or present a newly generated source ZIP as the validated artifact.

By submitting a contribution for inclusion, you must have the right to submit it under the project's [Apache-2.0 license](LICENSE). Preserve third-party notices and identify externally sourced material. No separate CLA or DCO automation is configured by this guide.
