#!/usr/bin/env python3
"""Reject CRLF in committed blobs so a Windows clone cannot dirty the tree.

`.gitattributes` declares `* text=auto eol=lf`, which keeps every text file
stored as LF no matter how a contributor's git is configured. That declaration
is only load-bearing while it is enforced: before it existed, a Windows clone
carried ~635 files that `git status` reported as modified with a diff of pure
CRLF and zero content change, and shell scripts and Dockerfiles committed with
CRLF fail inside a Linux container with `bad interpreter: /bin/sh^M`.

This checks the *index* form (what a commit records), not the working tree --
a checkout is free to hold CRLF on disk, and `*.bat` is deliberately checked
out that way.
"""

from __future__ import annotations

import subprocess
import sys

# `git ls-files --eol` reports the index form as `i/<eol>`:
#   lf / crlf / mixed -> a text blob, classified by what it contains
#   none             -> text blob with no line breaks at all
#   -text            -> binary, never converted
BAD_INDEX_EOL = {"crlf", "mixed"}


def tracked_eol() -> list[tuple[str, str, str]]:
    """Return (index_eol, attrs, path) for every tracked file."""
    result = subprocess.run(
        ["git", "ls-files", "--eol"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "Unable to inspect Git line endings.")

    entries: list[tuple[str, str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # "i/lf    w/crlf  attr/text eol=crlf   \tpath/with possible spaces"
        fields, _, path = line.partition("\t")
        if not path:
            continue
        # Three whitespace-separated columns: i/<eol>, w/<eol>, then the
        # attribute list, which itself contains spaces ("attr/text eol=lf").
        parts = fields.split(None, 2)
        if len(parts) < 2:
            continue
        index_eol = parts[0].removeprefix("i/")
        attrs = parts[2].strip() if len(parts) > 2 else ""
        entries.append((index_eol, attrs, path))
    return entries


def main() -> int:
    offenders = [
        (path, attrs) for index_eol, attrs, path in tracked_eol() if index_eol in BAD_INDEX_EOL
    ]
    if not offenders:
        return 0

    print(
        f"{len(offenders)} tracked file(s) are stored with CRLF line endings.",
        file=sys.stderr,
    )
    print(
        "Re-normalize them, then commit the result:\n"
        "    git add --renormalize .\n"
        "    git commit -m 'chore: normalize line endings'",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    for path, attrs in offenders:
        print(f"- {path}  [{attrs or 'no attributes'}]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
