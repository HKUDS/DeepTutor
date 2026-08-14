"""Persistent storage for bilingual alignment sidecars.

Alignment results are stored as JSON files in a dedicated ``bilingual/``
directory inside the KB, keeping the ``raw/`` source files pristine.

Layout::

    data/knowledge_bases/<kb>/
        raw/                          # EN + ZH source files (untouched)
        bilingual/
            <pair_key>/
                <file_path>.json      # alignment result for one page
            _index.json               # pair-level summary
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _bilingual_dir(kb_dir: Path, pair_key: str) -> Path:
    return kb_dir / "bilingual" / pair_key


def _sidecar_path(kb_dir: Path, pair_key: str, file_path: str) -> Path:
    """Return the JSON sidecar path for one aligned page.

    ``file_path`` is relative to ``raw/`` (e.g. ``explore/book.md``).
    The sidecar mirrors the same structure but with a ``.json`` extension.
    """
    stem = file_path
    if stem.endswith(".md"):
        stem = stem[:-3]
    return _bilingual_dir(kb_dir, pair_key) / (stem + ".json")


def save_alignment(
    kb_dir: Path,
    pair_key: str,
    file_path: str,
    alignment: dict,
) -> Path:
    """Persist one page's alignment result as a JSON sidecar.

    Returns the path written.
    """
    target = _sidecar_path(kb_dir, pair_key, file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"file_path": file_path, **alignment}
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def load_alignment(
    kb_dir: Path,
    pair_key: str,
    file_path: str,
) -> dict | None:
    """Load a page's alignment sidecar, or ``None`` if it doesn't exist."""
    target = _sidecar_path(kb_dir, pair_key, file_path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read alignment sidecar %s: %s", target, exc)
        return None


def load_alignment_for_any_pair(
    kb_dir: Path,
    file_path: str,
) -> dict | None:
    """Search all pair keys for a sidecar matching *file_path*."""
    bilingual_root = kb_dir / "bilingual"
    if not bilingual_root.is_dir():
        return None
    for pair_dir in sorted(bilingual_root.iterdir()):
        if not pair_dir.is_dir():
            continue
        result = load_alignment(kb_dir, pair_dir.name, file_path)
        if result is not None:
            return result
    return None


def list_aligned_pages(kb_dir: Path, pair_key: str) -> list[str]:
    """Return all aligned file paths for a pair."""
    pair_dir = _bilingual_dir(kb_dir, pair_key)
    if not pair_dir.is_dir():
        return []
    result: list[str] = []
    for f in sorted(pair_dir.rglob("*.json")):
        if f.name == "_index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            fp = data.get("file_path")
            if fp:
                result.append(fp)
        except Exception:
            continue
    return result


def save_pair_index(
    kb_dir: Path,
    pair_key: str,
    index_data: dict,
) -> None:
    """Persist a pair-level summary index."""
    target = _bilingual_dir(kb_dir, pair_key) / "_index.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_pair_index(kb_dir: Path, pair_key: str) -> dict | None:
    """Load a pair-level summary index."""
    target = _bilingual_dir(kb_dir, pair_key) / "_index.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_pair_keys(kb_dir: Path) -> list[str]:
    """Return all pair keys that have alignment data."""
    bilingual_root = kb_dir / "bilingual"
    if not bilingual_root.is_dir():
        return []
    return sorted(
        d.name for d in bilingual_root.iterdir() if d.is_dir()
    )


def remove_pair(kb_dir: Path, pair_key: str) -> None:
    """Remove all alignment data for a pair."""
    import shutil
    pair_dir = _bilingual_dir(kb_dir, pair_key)
    if pair_dir.exists():
        shutil.rmtree(pair_dir, ignore_errors=True)
        logger.info("Removed alignment data for pair %s", pair_key)


def remove_alignment(kb_dir: Path, pair_key: str, file_path: str) -> bool:
    """Remove one page's alignment sidecar.

    Returns ``True`` if a file was deleted, ``False`` if it didn't exist.
    """
    target = _sidecar_path(kb_dir, pair_key, file_path)
    if target.exists():
        target.unlink()
        logger.debug("Removed stale sidecar for %s", file_path)
        return True
    return False


def cleanup_stale_sidecars(
    kb_dir: Path,
    pair_key: str,
    current_files: set[str],
) -> int:
    """Remove sidecars whose source files no longer exist in ``current_files``.

    ``current_files`` is the set of EN file paths (relative to ``raw/``)
    that are currently present.  Any sidecar not matching is deleted.

    Returns the number of sidecars removed.
    """
    pair_dir = _bilingual_dir(kb_dir, pair_key)
    if not pair_dir.is_dir():
        return 0

    removed = 0
    for f in sorted(pair_dir.rglob("*.json")):
        if f.name == "_index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            fp = data.get("file_path", "")
            if fp and fp not in current_files:
                f.unlink()
                removed += 1
        except Exception:
            continue
    return removed
