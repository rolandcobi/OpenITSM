# P1-07 operational runbook

This runbook covers the accepted Windows / one process / direct HTTPS / local SQLite-WAL profile. It is a handover procedure, not permission to deploy or publish. [Release scope](../RELEASE_SCOPE.md) distinguish engineering closure from publication readiness. Use a disposable synthetic evaluation copy until site approval exists.

## Before starting

Retain the approved code revision, dependency/version manifest, database schema/source identification, protected stable ITSM_SECRET_KEY and certificate/key files as one recovery set. SMTP credentials are encrypted using that secret; changing it can make them unreadable and invalidates cookies. Do not put real secrets or records in Git/logs/evidence. Set filesystem permissions and backup access/retention under the site's policy; those real ACLs and certificate trust were not validated here.

Use the existing .venv\Scripts\python.exe, with Flask 3.1.3 and the versions in the final evidence. Do not combine a dependency upgrade with recovery. .env is not automatically loaded. Unknown historical forks require a separate compatibility assessment; only the four frozen historical schemas and declared partial states are covered. No old binary over an upgraded database and no SQL downgrade is supported.

## Start and verify

Choose an absolute local ITSM_DB. Provision a stable secret of at least 32 characters and, only for an empty users table, an initial administrator password of at least 12 characters through the process environment/secret manager. A new bootstrap password does not reset an existing account. The following values describe a loopback HTTPS evaluation with configured certificate paths; replace the paths before use:

```powershell
$env:ITSM_ENV = 'production'
$env:ITSM_DB = 'C:\OpenITSM-evaluation\evaluation.sqlite'
$env:ITSM_TLS = '1'
$env:ITSM_HTTPS = '1'
$env:ITSM_DEBUG = '0'
$env:ITSM_HOST = '127.0.0.1'
$env:ITSM_ALLOWED_HOSTS = 'localhost,127.0.0.1'
$env:ITSM_CERT = 'C:\OpenITSM-evaluation\configured-cert.pem'
$env:ITSM_KEY = 'C:\OpenITSM-evaluation\configured-key.pem'
$env:ITSM_HTTPS_PORT = '5443'
$env:ITSM_HTTP_REDIRECT = '0'
$env:ITSM_BACKUP = '1'
.venv\Scripts\python.exe migrations.py --database $env:ITSM_DB --check
.venv\Scripts\python.exe app.py
```

For an existing v0 copy, stop all writers, take a verified backup, review --check, then separately run migrations.py --database $env:ITSM_DB --apply before serving. A fresh missing file needs bootstrap during explicit apply or compatible application startup. Never force user_version or repair audit triggers to bypass refusal.

Confirm the configured bind address/port, Cheroot availability (HTTPS uses 16 threads), expected certificate and hostname, secure cookie flags, login and expected scoped records. Production configuration rejects missing security settings; no missing-dependency fallback is accepted as the reference profile. The HTTP helpers deliberately force loopback plaintext and are unsuitable for this HTTPS procedure. Do not trust proxy headers or enable multiple processes/replicas.

The P1-07 drill starts a production-configured factory and actual Cheroot HTTPS listener with a temporary trusted synthetic certificate, verifies real login, own/foreign ticket access and CSRF. It uses controlled server.stop/join. It does not certify OS service installation, signal delivery or organization certificate trust.

## Stop

Stop accepting work and let authorized requests finish before maintenance. For the foreground app.py console use Ctrl+C; its Cheroot entry catches KeyboardInterrupt and calls stop. Confirm the process/listener has ended and no application, backup or maintenance writer remains before restore. OS Ctrl+C/service stop behavior was reviewed in code but not exercised by the synthetic drill; validate it for a real service manager. Forced termination, best-effort mail threads and power loss can lose in-flight work or notifications.

Do not kill unrelated processes or assume a closed browser means the server stopped. Do not replace a database under any live process. Keep shutdown evidence and inspect integrity before reopening after an abnormal stop.

## Backup and verification

The built-in backup uses SQLite's backup API into backups/ beside app.py by default. The factory API can supply a separate backup_dir; there is no backup-directory environment variable. Daily itsm-YYYY-MM-DD.db files are not overwritten on the same day. The best-effort worker checks hourly and removes .db files older than 30 days by modification time. This is not offsite/encrypted backup, a durable scheduler or a guaranteed RPO. Worker/disk/permission failure can extend loss beyond the last daily snapshot.

For a maintenance snapshot, first stop all writers and use a new destination name. Do not copy just a live main SQLite file: committed state can remain in WAL. The following Python body is the same backup/check mechanism exercised in the rehearsal; choose actual source and a new target deliberately:

```python
import sqlite3
from pathlib import Path

source = Path(r"C:\OpenITSM-evaluation\evaluation.sqlite")
target = Path(r"C:\OpenITSM-evaluation\snapshots\maintenance-001.sqlite")
assert source.is_file() and not target.exists()
assert source.resolve() != target.resolve()
target.parent.mkdir(parents=True, exist_ok=True)
src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
dst = sqlite3.connect(target)
try:
    src.backup(dst)
    assert dst.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert dst.execute("PRAGMA foreign_key_check").fetchall() == []
    assert dst.execute("PRAGMA user_version").fetchone()[0] == 1
finally:
    dst.close()
    src.close()
```

Version 1 above is a completed-v1 snapshot check, not a claim that v0 backups are invalid; retain and inspect the actual source version for a pre-upgrade snapshot. Record a checksum, expected record counts/access, immutable audit history and recovery-set revision. Verify by restoring into a new disposable file and opening it with the matching supported code. Protect database backups as sensitive records; SMTP encryption does not encrypt the entire database.

## Restore, restart and failed migrations

1. Keep all writers stopped. Preserve the failed/current database and logs separately for investigation; do not destroy them.
2. Choose the verified snapshot and its matching supported application/configuration/secret. Identify writes since the snapshot and obtain the site's recovery-window decision: those writes will be absent after restore.
3. Restore using the same SQLite backup API into a **new, nonexistent** database path. Never overwrite a live file or manually discard a WAL/SHM pair.
4. Check integrity, foreign keys, actual version, expected records and audit. Run migrations.py --database NEW_PATH --check; apply only a supported, reviewed upgrade. Completed valid v1 --apply is a read-only no-op.
5. Point ITSM_DB at the restored file while stopped, retain the stable secret/certificate configuration, and restart one process. Factory startup prepares WAL before requests; it does not reseed/backfill a completed valid v1.
6. Verify own/foreign access, authentication, CSRF and expected records, and test SMTP credential decryption without sending real mail during the drill. Keep the prior file/snapshot until recovery is accepted.

For corrupt, locked, incompatible or future-version refusal: stop, retain the error and investigate or restore; do not bypass checks. P1-04/current regression proves historical restore/re-upgrade and fault rollback. P1-07 additionally proves exact snapshot restore, absence of a later synthetic write, same-secret session and SMTP decryption, and future-version refusal before workers.

## Verification and escalation

Run the [named complete gate](P1_06_TESTING.md) in a capable environment, retaining fresh JSON/logs and source hashes. Missing browsers/runtime are missing evidence. The legacy runner remains available with the historical-artifact preservation procedure.

[Phase 0 scope](../PHASE_0_SCOPE.md) remains unchanged. Real site migration/backup restore, OS ACLs/key handling, SMTP AUTH/relay, trusted certificates, capacity, OS service shutdown, every-screen browser/accessibility, proxy/multi-process/network SQLite and power-loss/failover are not certified. Durable jobs, full service-layer decomposition and identity integrations are separate work. No automated deployment, external CI activation, Phase 2, merge, push or publication is part of this runbook.
