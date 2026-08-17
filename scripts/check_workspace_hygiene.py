#!/usr/bin/env python3
"""Require a clean checkout in addition to clean tracked repository content."""

from __future__ import annotations

import subprocess
import sys


def run_git(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def dirty_entries() -> list[str]:
    result = run_git(["status", "--porcelain=v1", "--untracked-files=all"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "Unable to inspect Git status.")
    return [line for line in result.stdout.splitlines() if line.strip()]


def tracked_hygiene() -> int:
    result = subprocess.run(
        [sys.executable, "scripts/check_repo_hygiene.py"],
        check=False,
    )
    return result.returncode


def main() -> int:
    entries = dirty_entries()
    if entries:
        print(
            "Dirty checkout found; move work to a task worktree before proceeding:",
            file=sys.stderr,
        )
        print("\n".join(entries), file=sys.stderr)
        return 1
    return tracked_hygiene()


if __name__ == "__main__":
    raise SystemExit(main())
