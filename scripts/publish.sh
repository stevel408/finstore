#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  exit 1
fi

# Load .env to pick up PYPI_TOKEN (and any other vars) without polluting the shell.
set -a && source "$ENV_FILE" && set +a

if [[ -z "${PYPI_TOKEN:-}" ]]; then
  echo "ERROR: PYPI_TOKEN is not set in .env" >&2
  exit 1
fi

cd "$ROOT"
uv build
uv publish --token "$PYPI_TOKEN"
