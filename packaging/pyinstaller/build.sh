#!/usr/bin/env bash
# Thin Unix wrapper around packaging/pyinstaller/build.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-${1:-python3}}"
shift || true
exec "$PYTHON" packaging/pyinstaller/build.py --python "$PYTHON" "$@"
