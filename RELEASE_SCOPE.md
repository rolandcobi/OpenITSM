# Release candidate scope

Engineering validation and public publication approval are distinct decisions. This source candidate retains the accepted application and all 216 regression identities without changing assertions. Exact package validation results are supplied separately by the maintainer.

Supported evaluation profile: Windows x64, CPython 3.14.7, one process, direct HTTPS/Cheroot, local SQLite/WAL. Real site grants/data/restore, OS ACLs/key trust/service shutdown, organization SMTP AUTH, capacity and monitoring require site validation. Proxy/multi-process/network SQLite and arbitrary historical forks are not certified.

The included runbook describes configured startup, controlled stop, SQLite backup and offline restore. Best-effort SMTP/backup, daily snapshot non-overwrite, loss of writes after a restored snapshot, audit export's 20,000-row cap and focused browser coverage remain limitations. LDAP/AD/SSO/MFA and durable queues are not implemented.

Copyright 2026 Roland Cobi; Apache-2.0 project license. Dependency terms remain separate. Public vulnerability-reporting/hosting settings and independent review are not established by the candidate. Do not post secrets or unfixed vulnerability details in public issues; obtain a private channel from the owner before disclosure.

No publication or deployment is performed by preparing or testing this source archive.
