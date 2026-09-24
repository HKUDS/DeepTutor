#!/usr/bin/env bash
# Build the MarginNote 4 add-on package from the sources in this directory.
# Output: deeptutor-mn4-sync-1.1.2.mnaddon (not committed — attach to releases).
set -euo pipefail
cd "$(dirname "$0")"

VERSION="1.1.2"
OUT="deeptutor-mn4-sync-${VERSION}.mnaddon"

rm -f "$OUT"
zip -X "$OUT" main.js mnaddon.json logo_44x44.png
echo "built: $OUT"
