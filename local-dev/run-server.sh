#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

if [ ! -x ".venv/bin/python" ]; then
  echo "Missing virtualenv. Run ./local-dev/bootstrap.sh first." >&2
  exit 1
fi

MCP_HOST="${MCP_HOST:-127.0.0.1}" \
MCP_PORT="${MCP_PORT:-8000}" \
  .venv/bin/python -m Medical_Wizard_MCP
