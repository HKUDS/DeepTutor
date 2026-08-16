#!/usr/bin/env python3
"""Reject accidental direct commits on the release branch."""

from __future__ import annotations

import subprocess
import sys


def current_branch() -> str | None:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


def allows_main_commit() -> bool:
    result = subprocess.run(
        ["git", "config", "--bool", "deeptutor.allowMainCommit"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def main() -> int:
    if current_branch() == "main" and not allows_main_commit():
        print(
            "Direct commits to main are forbidden. Develop on dev or a topic branch, "
            "then integrate through review. For an explicit release exception, set "
            "deeptutor.allowMainCommit=true and unset it afterward.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
