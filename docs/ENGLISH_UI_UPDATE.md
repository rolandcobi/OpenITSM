# English interface update

All application modules now use English for interface text and generated messages: navigation, forms, dropdowns, help text, dialogs, errors, notifications, chat, email, calendar, task/workflow history, reports and exports. Organizational visibility guidance matches the enforced scoped permissions. The service label Major Outage retains its existing wire value for compatibility.

Validation on Windows / Python 3.14.7 / Flask 3.1.3: 223/223 complete named-suite tests passed with no failures, errors or skips, including all original 216 identities and seven new English UI tests. The full gate passed route, role/mode, real Edge/Chrome, controlled SMTP TLS and TLS worker checks. Organization and workspace matrices covered 630 and 2,466 cases respectively. All JavaScript files passed syntax checks.

The test changes retain exact authorization, filtering, count and denial assertions. English export labels replace the previous language expectations. Handler fingerprints were updated only after verifying identical AST structure apart from string constants. The named runner includes the seven new HTTP tests; the inventory records the explicit text-only baseline amendments.

Tests use disposable synthetic databases. User-entered content, stored historical records, frozen migrations, schema identifiers and compatibility values remain unchanged. This update does not replace human visual acceptance or establish production deployment readiness.

Run the complete suite with:

    .venv\Scripts\python.exe tests\run_suites.py --suite all --output-dir test-results\english-ui

CI proposals, local credentials, databases, manual-test runtime files and historical internal reports are excluded.
