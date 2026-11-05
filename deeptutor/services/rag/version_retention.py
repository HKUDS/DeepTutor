"""Explicit offline retention for published, flat LlamaIndex snapshots.

Never run deletion alongside API workers, partners or indexers. Keeping two
published versions per embedding signature preserves the active index and a
rollback snapshot, even when the currently selected model has changed.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3

_VERSION = re.compile(r"version-([0-9]+)\Z")


def referenced_versions(databases: list[Path]) -> frozenset[str]:
    """Conservatively preserve version names in saved conversations/learning state.

    Fail closed on unreadable databases. A reference to version-5 in any KB
    protects version-5 in every KB; over-retention is preferable to a broken cite.
    """
    protected: set[str] = set()
    for path in dict.fromkeys(databases):
        if not path.exists():
            continue
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            for (table,) in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                for row in conn.execute(f"SELECT * FROM {quoted}"):
                    for value in row:
                        if isinstance(value, str):
                            protected.update(re.findall(r"\bversion-[0-9]+\b", value))
    return frozenset(protected)


def obsolete_versions(
    kb_dir: Path, *, keep: int = 2, protected: frozenset[str] = frozenset()
) -> list[Path]:
    """Plan deletion without loading docstores or modifying the KB.

    Unknown, incomplete, legacy and non-LlamaIndex versions are retained.
    Explicitly protected versions are additional to the normal retention count.
    """
    if keep < 2:
        raise ValueError("Keep at least two published versions per signature")
    groups: dict[str, list[Path]] = defaultdict(list)
    created: dict[Path, str] = {}
    for path in kb_dir.iterdir():
        if path.is_symlink() or not path.is_dir() or not _VERSION.fullmatch(path.name):
            continue
        meta_path = path / "meta.json"
        if meta_path.is_symlink():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        signature = meta.get("signature")
        if (
            meta.get("provider") != "llamaindex"
            or meta.get("state") != "published"
            or not isinstance(signature, str)
            or not signature
        ):
            continue
        artifacts = [path / name for name in ("docstore.json", "index_store.json")]
        if not all(p.is_file() and not p.is_symlink() and p.stat().st_size for p in artifacts):
            continue
        groups[signature].append(path)
        created[path] = str(meta.get("created_at") or "")
    obsolete = []
    for paths in groups.values():
        paths.sort(key=lambda p: (created[p], int(_VERSION.fullmatch(p.name)[1])), reverse=True)
        obsolete.extend(path for path in paths[keep:] if path.name not in protected)
    return sorted(obsolete, key=lambda p: int(_VERSION.fullmatch(p.name)[1]))


def prune_versions(
    kb_dir: Path,
    *,
    keep: int = 2,
    protected: frozenset[str] = frozenset(),
    offline: bool = False,
) -> list[str]:
    """Replan and delete old snapshots after the caller has stopped all writers."""
    if not offline:
        raise ValueError("Stop DeepTutor and all indexers before applying retention")
    removed = []
    for path in obsolete_versions(kb_dir, keep=keep, protected=protected):
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def cleanup_preview(kb_dir: Path, *, protected: frozenset[str] = frozenset()) -> dict:
    """A freshness-bound plan containing only public version names and sizes."""
    candidates = obsolete_versions(kb_dir, protected=protected)
    revisions = []
    size = 0
    for version in candidates:
        for path in sorted(version.rglob("*")):
            if path.is_symlink():
                raise ValueError("Cannot clean an index version containing symbolic links")
            stat = path.stat()
            revisions.append((str(path.relative_to(kb_dir)), stat.st_size, stat.st_mtime_ns))
            if path.is_file():
                size += stat.st_size
    # Include every version, so publication or a changed pin invalidates a preview.
    state = [(p.name, p.stat().st_mtime_ns) for p in kb_dir.iterdir() if _VERSION.fullmatch(p.name)]
    token = json.dumps([sorted(state), revisions, sorted(protected)], sort_keys=True).encode()
    return {
        "versions": [p.name for p in candidates],
        "bytes": size,
        "fingerprint": hashlib.sha256(token).hexdigest(),
    }


def apply_cleanup(
    kb_dir: Path, fingerprint: str, *, protected: frozenset[str] = frozenset()
) -> dict:
    """Caller must hold an exclusive version lease and refresh saved references."""
    plan = cleanup_preview(kb_dir, protected=protected)
    if fingerprint != plan["fingerprint"]:
        raise ValueError("Index versions changed. Preview cleanup again.")
    for name in plan["versions"]:
        shutil.rmtree(kb_dir / name)
    return plan
