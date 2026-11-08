# Security policy

OpenITSM is an engineering preview maintained by Roland Cobi. Local regression results are bounded evidence, not independent security certification or production approval.

## Reporting a vulnerability

GitHub private vulnerability reporting is enabled for [rolandcobi/OpenITSM](https://github.com/rolandcobi/OpenITSM). The enabled setting was verified through GitHub's API on 2026-11-08.

Sign in to GitHub and use [Report a vulnerability](https://github.com/rolandcobi/OpenITSM/security/advisories/new). Reports are handled privately through repository security advisories. Roland Cobi ([@rolandcobi](https://github.com/rolandcobi)) is the responsible maintainer.

If the reporting form is unavailable, do not submit sensitive details through a public issue or pull request. Report only that the private reporting route is unavailable, without vulnerability details. No personal email address is designated as a security contact.

Do not publish credentials, site databases, personal information, detailed exploits, or unfixed vulnerability reports in public issues. No personal email or unrelated GitHub account is designated as a security contact here.

A private report should describe:

- The affected version/candidate and environment.
- A minimal synthetic reproduction and expected versus actual behavior.
- The affected role, object/unit boundary, prerequisites, and impact.
- Any temporary mitigation, without using real organization data.

Do not test against systems or users without authorization. Coordinate disclosure and remediation with the maintainer. No response-time SLA, bounty, or production support commitment is established.

## Supported evaluation scope

The currently validated source candidate is OpenITSM-rc-001 for Windows x64 / CPython 3.14.7, one process, local SQLite/WAL, and direct HTTPS/Cheroot. No maintained production release series or long-term security support window has been announced.

Real site permissions, certificates, SMTP AUTH, capacity, OS/service shutdown and recovery need site validation. Proxy/multi-process/network SQLite, arbitrary historical forks and broader browser/platform coverage are not certified.

See [the support boundary](PHASE_0_SCOPE.md) and [candidate verification](VALIDATION.md). Package/dependency scans do not replace a complete application, native dependency, OS or browser audit.

## Public preview and review status

The source repository is public as an engineering preview. Its complete 223-test regression gate passed, including the original 216 identities and seven English UI checks. Automated regression results do not establish independent security certification or production readiness.

Private reporting enablement was verified through the GitHub API. A real vulnerability report and end-to-end notification delivery were not simulated. Independent source/security review and real deployment validation remain follow-up work.

Official reference: [configure private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
