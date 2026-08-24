#!/usr/bin/env python3
"""Keep the launchd-owned primary checkout on a clean integration branch."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

PRIMARY_BRANCHES = {"main", "dev"}
MAX_DIRTY_DETAILS = 30


def run_git(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def is_primary_worktree() -> bool:
    top_level = run_git(["rev-parse", "--show-toplevel"])
    common_git_dir = run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if top_level.returncode != 0 or common_git_dir.returncode != 0:
        raise SystemExit(
            top_level.stderr.strip()
            or common_git_dir.stderr.strip()
            or "Unable to inspect the Git worktree."
        )
    return (
        Path(top_level.stdout.strip()).resolve()
        == Path(common_git_dir.stdout.strip()).resolve().parent
    )


def current_branch() -> str | None:
    result = run_git(["branch", "--show-current"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "Unable to inspect the branch.")
    return result.stdout.strip() or None


def dirty_entries() -> list[str]:
    result = run_git(["status", "--porcelain=v1", "--untracked-files=normal"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "Unable to inspect Git status.")
    return [line for line in result.stdout.splitlines() if line.strip()]


def print_dirty_entries(entries: list[str]) -> None:
    print(
        f"Primary checkout is dirty ({len(entries)} entries). Move WIP to a task "
        "worktree before developing, merging, committing, or publishing:",
        file=sys.stderr,
    )
    print("\n".join(entries[:MAX_DIRTY_DETAILS]), file=sys.stderr)
    omitted = len(entries) - MAX_DIRTY_DETAILS
    if omitted > 0:
        print(f"... {omitted} additional entries omitted", file=sys.stderr)


def main() -> int:
    if not is_primary_worktree():
        return 0

    branch = current_branch()
    if branch not in PRIMARY_BRANCHES:
        print(
            f"Primary checkout is on task branch {branch!r}; switch it back to "
            "main or dev and develop in a linked worktree.",
            file=sys.stderr,
        )
        return 1

    entries = dirty_entries()
    if entries:
        print_dirty_entries(entries)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
