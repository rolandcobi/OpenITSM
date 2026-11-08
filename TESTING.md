# Testing

Use the exact Windows/Python hash locks and a fresh environment described in README.md. Use only temporary synthetic application databases.

Run tests/run_suites.py --suite all with a new --output-dir. Only a complete clean run with required actual runtime evidence can set full_gate=true. Subset results never certify the complete gate; missing browsers are NOT_EXECUTED, not pass.

The retained tests read three synthetic witnesses: phase0-http-results.json, phase0-test-results.txt and evidence/p1-04/regression_results.json. These contain test metadata, not a site database. Frozen schema/handler/identity fixtures remain unchanged.

The legacy tests/run_phase0.py discovers the complete suite but overwrites the two root Phase 0 result files. Save their bytes, copy new output to a separate evidence directory even on failure, and restore the saved bytes in finally. Never present old result files as a new execution.

See [named suite contracts](docs/P1_06_TESTING.md) and [validation summary](VALIDATION.md). Documentation-only changes require link/structure/content checks and artifact preservation rather than relabelling previous application results as fresh runs.
