#!/usr/bin/env bash
set -euo pipefail
export ITSM_TLS=0 ITSM_HOST=127.0.0.1 ITSM_BACKUP=0
export ITSM_SECRET_KEY="${ITSM_SECRET_KEY:-$(python -c 'import secrets; print(secrets.token_hex(32))')}"
if [[ ! -f itsm.db && -z "${ITSM_INITIAL_ADMIN_PASSWORD:-}" ]]; then
  read -r -s -p 'Set initial administrator password (minimum 12 characters): ' ITSM_INITIAL_ADMIN_PASSWORD
  echo
  export ITSM_INITIAL_ADMIN_PASSWORD
fi
python app.py
