# Security policy

OpenITSM is an engineering preview maintained by Roland Cobi. Local regression results are bounded evidence, not independent security certification or production approval.

## Reporting a vulnerability

The selected reporting mechanism is **GitHub private vulnerability reporting**. It is not enabled by these local files, and the existing repository rolandcobi/OpenITSM is private and verified, but no private reporting endpoint has been enabled or verified.

When enabled, use the repository's Security > Advisories > Report a vulnerability interface. If that interface is unavailable, the maintainer must establish and publish a verified private channel before accepting sensitive reports. Do not substitute a public issue or pull request for a missing private channel.

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

## Maintainer release requirement

Before public release, enable and test the chosen private reporting mechanism, assign a responsible recipient, and update this policy with a verified route. These remain hosting tasks; no GitHub setting was changed by preparing SECURITY.md.

Official reference: [configure private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
