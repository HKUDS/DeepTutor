#!/usr/bin/env bash
# Thin Unix wrapper around packaging/node-runtime/prepare.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" packaging/node-runtime/prepare.py "$@"
