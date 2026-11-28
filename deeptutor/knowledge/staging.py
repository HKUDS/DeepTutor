#!/usr/bin/env python
"""Shared staging rule for putting source documents into a KB's ``raw/`` tree.

Both ways of filling a knowledge base — creating one from a docs directory, and
adding documents to an existing one — flatten sources to their basename, so two
documents that share a name want the same path. Only one place should answer
what happens then, or the two entry points drift apart: the incremental path
kept both files while the create path copied straight onto the taken name and
indexed only the last one, silently losing the rest (#2041).
"""

from __future__ import annotations

import hashlib
import itertools
from pathlib import Path
import shutil


def content_hash(file_path: Path) -> str:
    """SHA-256 of a file, streamed in blocks so large documents stay off memory."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            sha256_hash.update(block)
    return sha256_hash.hexdigest()


def non_colliding(dest_path: Path) -> Path:
    """A free sibling name for a *different* document that wants a taken one.

    Two files can legitimately share a name and hold different content — a
    docs tree with a README.md per folder is the ordinary case, and a book
    series saved with one ``full.md`` per volume is the same shape. Dropping
    the later one loses a document the user asked to index, silently.
    """
    if not dest_path.exists():
        return dest_path
    for index in itertools.count(2):
        candidate = dest_path.with_name(f"{dest_path.stem} ({index}){dest_path.suffix}")
        if not candidate.exists():
            return candidate
    raise AssertionError("unreachable")  # pragma: no cover


def _copy_new(source_path: Path, dest_path: Path) -> None:
    """Copy into a name that must not exist yet; leave nothing behind on failure.

    ``"xb"`` makes taking the name atomic, so a file another writer created
    after the caller's check is never overwritten (``FileExistsError``).
    """
    with open(source_path, "rb") as source:
        sink = open(dest_path, "xb")
        try:
            with sink:
                shutil.copyfileobj(source, sink, 1 << 20)
        except BaseException:
            dest_path.unlink(missing_ok=True)
            raise
    shutil.copystat(source_path, dest_path)


def stage_source(
    source_path: Path,
    dest_path: Path,
    *,
    source_hash: str | None = None,
) -> tuple[Path, bool]:
    """Copy *source_path* to *dest_path* without replacing a different document.

    Returns the path the document actually landed on, and whether a copy was
    made. A name already holding the *same* content is reused rather than
    written twice; a name holding a different document is left alone and the
    newcomer takes a free sibling name, so both get indexed. A failed copy
    leaves no partial file behind.
    """
    current = source_hash
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        staged = (
            dest_path
            if index == 1
            else dest_path.with_name(f"{dest_path.stem} ({index}){dest_path.suffix}")
        )
        if staged.exists():
            current = current or content_hash(source_path)
            if current == content_hash(staged):
                return staged, False
            index += 1
            continue
        try:
            _copy_new(source_path, staged)
        except FileExistsError:
            # Taken since the check: compare against it on the next pass. A
            # name that still does not "exist" (a dangling symlink) is skipped.
            if not staged.exists():
                index += 1
            continue
        return staged, True


__all__ = ["content_hash", "non_colliding", "stage_source"]
