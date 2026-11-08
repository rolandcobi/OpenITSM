# GitHub preparation and approval checklist

All project-facing documentation in this prepared tree is English. The source begins from the clean source candidate and adds community/architecture documentation without changing application/test/dependency/license bytes.

The original OpenITSM-rc-001 ZIP stays separate and unchanged:
SHA-256 fe0d0943043f5fe28181133c8100aaf103098e01b94240e9fce17c273ec7679d
272202 bytes; 96 entries.

This tree has fresh Git history, not a rewritten copy of the private development repository. The archive manifest records provenance only; SOURCE_MANIFEST.json describes the prepared files. Runtime/tests/fixtures retain their validated bytes. The three retained historical test witnesses are synthetic and required by tests; internal failure logs and developer-profile paths are excluded.

Before first private upload:
1. Verify the exact prepared commit, source manifest, clean Git status and one-root-commit history.
2. Review the recorded secret/content checks and full synthetic test gate.
3. Recheck the verified destination rolandcobi/OpenITSM is still private and empty.
4. Ask for explicit approval of that exact commit and destination before uploading.
5. Push only main after approval; never use --all, --mirror or --force.

No upload or hosting mutation is performed by this checklist. A repository gaining commits requires reconciliation before any push. The GitHub connector authentication and local Git transport are different; a working read-only connector does not prove local Git push credentials are configured.

Before any later public transition or release, complete independent review, review the chosen source/disclosure set, configure/test the private reporting route when the hosting visibility permits it, review release notes and obtain separate explicit approval. Do not publish the existing private evidence/history or substitute an automatic GitHub archive for the original validated asset.

See [readiness](../RELEASE_READINESS.md), [security policy](../SECURITY.md), [validation](../VALIDATION.md) and [repository plan](GITHUB_REPOSITORY_PLAN.md).
