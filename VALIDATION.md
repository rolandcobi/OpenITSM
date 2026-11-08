# Validation summary

The project code and all 216 accepted tests originate from the clean OpenITSM-rc-001 source candidate. That candidate passed installation into a fresh Windows x64 / CPython 3.14.7 environment and both complete named and legacy 216-test runners, with zero abnormal outcomes.

Frozen archive: OpenITSM-rc-001-source.zip
SHA-256: fe0d0943043f5fe28181133c8100aaf103098e01b94240e9fce17c273ec7679d
Size: 272202 bytes; 96 files.

The archive is preserved separately and is not committed as a binary to this repository. [Archive manifest](docs/validation/RC_ARCHIVE_MANIFEST.json) describes the original ZIP, not the later repository documentation overlay. GitHub-generated archives from this repository are different artifacts.

The repository is prepared from those clean files, with English community/architecture documentation and a fresh Git history. Original application, template/static, test/fixture, dependency-lock and license bytes are preserved. Private audit logs, personal filesystem paths, ignored databases/keys and old Git objects are excluded.

Named tests require installed Edge and Chrome and loopback TLS/SMTP. They use temporary synthetic databases. Counts supplement semantic RBAC/IDOR/cross-unit/CSRF/session/audit/transaction assertions; they do not prove exhaustive security. The private preparation record contains the actual command logs and further checks without exposing them in this source tree.

A separately recorded complete gate is run against this prepared tree before first-upload approval. Its result is added below before the one root commit is created. No upload, public release, independent audit or production deployment is implied.

## Prepared-tree verification

A fresh isolated Windows/Python environment installed the locked wheels and passed the complete named gate: 216/216 in 497.053 seconds, full_gate=true, with zero failures, errors, skips, expected failures or unexpected successes. Exact route/GET/runtime compatibility checks passed; application/test/fixture bytes were preserved. Local content scan retained only the three known non-live synthetic/fingerprint signals, and OSV returned no matches for the fifteen installed distributions at the recorded preparation time. This internal verification does not complete independent review. No upload occurred before the requested approval.
