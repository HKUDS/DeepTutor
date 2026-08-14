#!/usr/bin/env python3
"""Reject commonly regenerated files that have accidentally been tracked."""

from __future__ import annotations

from pathlib import PurePosixPath
import subprocess
import sys

FORBIDDEN_PARTS = {
    ".DS_Store",
    ".next",
    ".next-deeptutor",
    ".turbo",
    "__pycache__",
    "htmlcov",
    "node_modules",
    "playwright-report",
    "test-results",
}
FORBIDDEN_SUFFIXES = (".pyc", ".pyo")


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def violation(path: str) -> str | None:
    pure_path = PurePosixPath(path)
    if pure_path.parts[0:1] == ("web",) and pure_path.parts[1:2] in (
        ("out",),
        ("dist",),
    ):
        return "frontend build output"
    if any(part in FORBIDDEN_PARTS for part in pure_path.parts):
        return "generated output"
    if pure_path.suffix in FORBIDDEN_SUFFIXES:
        return "compiled bytecode"
    if path != path.strip() or any(
        ord(character) < 32 or ord(character) == 127 for character in path
    ):
        return "unusual filesystem whitespace"
    return None


def main() -> int:
    violations = [
        f"{path}: {reason}" for path in tracked_paths() if (reason := violation(path)) is not None
    ]
    if violations:
        print("Tracked generated or anomalous files found:", file=sys.stderr)
        print("\n".join(violations), file=sys.stderr)
        print(
            "Remove them from the index with `git rm --cached`; keep local files when "
            "they are useful build output.",
            file=sys.stderr,
        )
        return 1
    print("Repository hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
