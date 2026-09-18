#!/usr/bin/env bash
# Recreate the repo .venv if it is missing or cannot `import requests`.
# Mix commands must use .venv/bin/python after this; system python is a silent
# degrade (no requests, failed skip-log ingest, failed publish).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_PY="${ROOT}/.venv/bin/python"
REQ="${ROOT}/requirements.txt"

venv_ok() {
  if [[ ! -x "$VENV_PY" ]]; then
    return 1
  fi
  "$VENV_PY" -c "import requests" 2>/dev/null
}

if venv_ok; then
  echo "ensure_venv: .venv ok ($VENV_PY)"
  exit 0
fi

if [[ ! -f "$REQ" ]]; then
  echo "ensure_venv: missing $REQ" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ensure_venv: python3 not on PATH; cannot create .venv" >&2
  exit 1
fi

echo "ensure_venv: .venv missing or broken; recreating"
if ! python3 -m venv --clear "${ROOT}/.venv"; then
  echo "ensure_venv: python3 -m venv failed. On Debian/Ubuntu: apt install python3-venv" >&2
  exit 1
fi
if [[ ! -x "$VENV_PY" ]]; then
  echo "ensure_venv: venv created but $VENV_PY is missing" >&2
  exit 1
fi
"$VENV_PY" -m pip install -r "$REQ"

if ! venv_ok; then
  echo "ensure_venv: .venv still cannot import requests after install" >&2
  exit 1
fi

echo "ensure_venv: recreated ($VENV_PY)"
