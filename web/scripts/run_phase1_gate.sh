#!/usr/bin/env bash
#
# Gate 1 of the Darsyar Phase 1 roadmap, ready to run on a machine that can
# install a browser.
#
# Why this script exists: the sandbox where Phase 1 was built has no browser
# and cannot get one. Playwright's download host is unreachable, and although
# a chromium binary can be pulled from npm, it needs libnss3/libnspr4, whose
# Debian repository is also unreachable. Eight of its eleven libraries are
# present; those three are the whole obstacle.
#
# So the E2E suite ships ready and unrun, rather than absent. This script is
# the part that turns "ready" into "run".
#
# Usage:
#   ./scripts/run_phase1_gate.sh                 # full run
#   ./scripts/run_phase1_gate.sh --install-only  # just fetch the browser
#   WEB_BASE_URL=http://localhost:3000 ./scripts/run_phase1_gate.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."

BASE_URL="${WEB_BASE_URL:-http://localhost:3000}"
INSTALL_ONLY=0
[[ "${1:-}" == "--install-only" ]] && INSTALL_ONLY=1

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$1"; }

# --- 1. Node ---------------------------------------------------------------
step "Checking Node"
command -v node >/dev/null || { fail "node is not installed"; exit 1; }
ok "node $(node --version)"

# --- 2. Dependencies -------------------------------------------------------
step "Installing dependencies"
if [[ ! -d node_modules ]]; then
  npm ci --replace-registry-host=always
else
  ok "node_modules already present"
fi

# --- 3. Browser ------------------------------------------------------------
step "Installing the Playwright browser"
# --with-deps also installs libnss3/libnspr4, which is the step this sandbox
# cannot perform. On a machine with a working apt repository it just works.
if npx playwright install --with-deps chromium; then
  ok "chromium installed"
else
  fail "chromium install failed"
  cat <<'EOF'

If the download host is unreachable, set a mirror first:

  PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
    npx playwright install --with-deps chromium

If the browser downloads but will not launch, the missing pieces are almost
always these three libraries:

  sudo apt-get install -y libnss3 libnspr4

Check with:  ldd ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome | grep 'not found'
EOF
  exit 1
fi

if [[ $INSTALL_ONLY -eq 1 ]]; then
  ok "install-only: stopping here"
  exit 0
fi

# --- 4. Reachability -------------------------------------------------------
step "Checking the web instance at $BASE_URL"
if ! curl -fsS -o /dev/null --max-time 10 "$BASE_URL/login"; then
  fail "no response from $BASE_URL/login"
  cat <<EOF

Start the app first, in another terminal:

  npm run build && npm run start        # production, matches the shipped bundle
  # or, for a quicker loop:
  npm run dev

Then re-run this script.
EOF
  exit 1
fi
ok "web instance reachable"

# --- 5. Accounts -----------------------------------------------------------
step "Checking seeded accounts"
# The authorisation tests need one admin and one student. They skip themselves
# when absent, so a run without them reports "skipped" rather than failing --
# but Gate 1 is only satisfied by a run where they do not skip.
if [[ "${DEEPTUTOR_PHASE1_SEED:-0}" == "1" ]]; then
  ok "seed flag set; authorisation tests will run"
else
  cat <<'EOF'
  Note: DEEPTUTOR_PHASE1_SEED is not set, so the authorisation and responsive
  tests will SKIP. To satisfy Gate 1 they must actually run.

  Create the two accounts first:

    phase1-admin    (role: admin)
    phase1-student  (role: student)

  then export DEEPTUTOR_PHASE1_SEED=1 with the passwords:

    export DEEPTUTOR_PHASE1_SEED=1
    export PHASE1_ADMIN_PASS=... PHASE1_STUDENT_PASS=...
EOF
fi

# --- 6. Run ----------------------------------------------------------------
step "Running Gate 1"
set +e
WEB_BASE_URL="$BASE_URL" npx playwright test --project=phase1-shell --reporter=list
STATUS=$?
set -e

echo
if [[ $STATUS -eq 0 ]]; then
  ok "Gate 1 PASSED"
  echo
  echo "Attach the output above, plus the HTML report if you want the traces:"
  echo "  npx playwright show-report"
else
  fail "Gate 1 FAILED (exit $STATUS)"
fi
exit $STATUS
