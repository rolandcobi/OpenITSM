# Public source readiness

OpenITSM is publicly available at https://github.com/rolandcobi/OpenITSM as an engineering preview, following Roland Cobi's explicit authorization on 2026-11-08. This publication covers the source repository, English interface and six synthetic demonstration screenshots. No binary release, tag, hosted application or production deployment was created.

## Verified publication state

- Pull request #1 merged the tested English update. The only GitHub branch is main.
- The exact upload copy passed 223/223 complete named-suite tests, with zero failures, errors or skips and full_gate=true. All original 216 test identities were retained.
- The 23 migration checks passed with the configured local interpreter. Real Edge/Chrome, controlled SMTP TLS, TLS workers, organization and workspace authorization matrices passed.
- All 128 source files were scanned before upload with pinned Gitleaks 8.30.1. Three non-live test values/fingerprints were independently checked against the isolated test code and computed handler hashes; no unresolved secret finding remained.
- Screenshot PNGs and README links were checked and the images visually reviewed. Names, addresses, organizations and operational records in the images are synthetic. Demo databases, credentials, cookies, signing keys and browser profiles are excluded.
- Apache-2.0 is present and recognized by GitHub. Roland Cobi owns the project and the included screenshots. Runtime dependencies and native wheels are not bundled; dependency license identities are listed in THIRD_PARTY_NOTICES.md. A future binary/container distribution needs its own complete notices and license review.
- GitHub private vulnerability reporting is enabled and its API flag was verified. The responsible maintainer and reporting form are published in SECURITY.md.

## Remaining evaluation limits

Independent source/security review has not been completed. Automated tests and secret scanning are bounded internal evidence. Human visual/accessibility review, broader browser/platform coverage, native/OS/browser advisory certification and real deployment permissions, certificates, SMTP AUTH, capacity, shutdown and recovery remain unverified. No end-to-end private-report notification test is claimed.

The evaluated profile is Windows x64 / CPython 3.14.7 / Flask 3.1.3, one process, direct HTTPS and local SQLite/WAL. Proxy/multi-process/network SQLite and arbitrary historical database forks remain outside this profile. The CI and main-protection proposals remain separate local preparation work.

## Artifact identity

The frozen OpenITSM-rc-001 source ZIP and its validation record are unchanged. That ZIP predates the English interface and screenshot update; the public repository source and GitHub-generated archives are different artifacts. Do not describe them as the original validated ZIP.

See [security policy](SECURITY.md), [English update validation](docs/ENGLISH_UI_UPDATE.md), [screenshot provenance](docs/SCREENSHOTS.md), [candidate validation](VALIDATION.md) and [operational runbook](docs/P1_07_RUNBOOK.md).
