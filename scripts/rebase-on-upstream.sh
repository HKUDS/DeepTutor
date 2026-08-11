#!/usr/bin/env bash

# Rebase this fork's topic commits onto the latest upstream DeepTutor main.
#
# Upstream tracking: PR #719 introduced the original immersive-reading work.
# If upstream/main starts changing the immersive-reading paths, compare its
# implementation before resolving a rebase conflict or retaining local code.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! git remote get-url origin >/dev/null 2>&1; then
    echo "Missing required upstream remote: origin" >&2
    exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Refusing to rebase with tracked worktree changes." >&2
    echo "Commit or stash them first, then run this script again." >&2
    exit 1
fi

git fetch origin --prune

immersive_paths=(
    deeptutor/immersive_reading
    deeptutor/api/routers/immersive_reading.py
    web/app/'(workspace)'/immersive-reading
    web/lib/immersive-reading-api.ts
)

if git log --format=%h origin/main -- "${immersive_paths[@]}" | grep -q .; then
    echo ""
    echo "Upstream now changes immersive-reading paths (watch PR #719)."
    echo "Compare upstream's implementation before retaining local EPUB code."
fi

if ! git rebase origin/main; then
    echo ""
    echo "Rebase stopped on a conflict. Resolve it, then run:"
    echo "  git add <resolved files>"
    echo "  git rebase --continue"
    echo "Afterward, run:"
    echo "  python -m pytest -q tests/book/test_character_graph.py tests/immersive_reading"
    exit 1
fi

python -m pytest -q tests/book/test_character_graph.py tests/immersive_reading
