"""Content-addressed parse cache + canonical IR loader.

The cache is keyed by ``(source_hash, parser_signature)`` and shared across all
consumers (question extraction, RAG indexing). Re-parsing the same bytes with
the same engine config is a directory lookup; a different engine/version/knob
lands in a different signature dir and re-parses. Layout::

    parse_cache/<hash[:2]>/<source_hash>/<signature>/
        manifest.json              # written last → presence == "ready"
        <stem>.md
        <stem>_content_list.json   # optional (engines that emit structure)
        images/                    # optional

``load_ir`` turns such a dir back into ``(markdown, blocks, asset_dir)``,
mirroring the question extractor's loader but free of stdout side effects so
both it and the engines share one loader.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import shutil
from typing import Any, Optional

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"
_HASH_PREFIX = "sha256"
_READ_CHUNK = 1 << 20  # 1 MiB


def source_hash_from_path(path: Path) -> str:
    """Hash the *bytes* of ``path`` (not its name) so re-uploads of the same
    document under a random temp name still hit cache."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def signature_dir(cache_root: Path, source_hash: str, sig_hash: str) -> Path:
    return cache_root / source_hash[:2] / source_hash / sig_hash


def is_ready(workdir: Optional[Path]) -> bool:
    return bool(workdir) and (workdir / MANIFEST_FILENAME).is_file()


def lookup(cache_root: Path, source_hash: str, sig_hash: str) -> Optional[Path]:
    """Return a ready cache dir for the key, or ``None`` on miss."""
    target = signature_dir(cache_root, source_hash, sig_hash)
    return target if is_ready(target) else None


def reserve(cache_root: Path, source_hash: str, sig_hash: str) -> Path:
    """Create (or reuse) the signature dir the engine writes its artifacts into.

    Stale incomplete dirs (no manifest, e.g. a previous crash) are cleared so a
    retry starts clean.
    """
    target = signature_dir(cache_root, source_hash, sig_hash)
    if target.exists() and not is_ready(target):
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_manifest(workdir: Path, meta: dict[str, Any]) -> None:
    """Stamp the cache dir ready. Written last so a half-written dir never reads
    as a cache hit."""
    payload = {
        **meta,
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
    }
    with open(workdir / MANIFEST_FILENAME, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def cleanup_failed(workdir: Path) -> None:
    """Best-effort removal of an unfinished (manifest-less) cache dir."""
    try:
        if workdir.is_dir() and not is_ready(workdir):
            shutil.rmtree(workdir, ignore_errors=True)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("Could not clean up failed parse dir %s: %s", workdir, exc)


def find_content_dir(workdir: Path) -> Path:
    """Locate the dir holding parsed markdown artifacts.

    Engines (MinerU especially) may nest output under ``auto/``/``hybrid_auto/``
    or a per-document subdir. Mirrors the question extractor's resolver.
    """
    candidate_dirs: list[Path] = []

    for preferred_name in ("auto", "hybrid_auto"):
        preferred = workdir / preferred_name
        if preferred.is_dir():
            candidate_dirs.append(preferred)

    for child in sorted(workdir.iterdir()) if workdir.is_dir() else []:
        if child.is_dir() and child not in candidate_dirs:
            candidate_dirs.append(child)

    nested = {
        artifact.parent
        for pattern in ("*.md", "*_content_list.json")
        for artifact in (workdir.rglob(pattern) if workdir.is_dir() else [])
    }
    for artifact_dir in sorted(nested):
        if artifact_dir not in candidate_dirs:
            candidate_dirs.append(artifact_dir)

    for candidate in candidate_dirs:
        if list(candidate.glob("*.md")):
            return candidate

    return candidate_dirs[0] if candidate_dirs else workdir


def load_ir(workdir: Path) -> tuple[str, Optional[list[dict]], Optional[Path]]:
    """Load ``(markdown, blocks, asset_dir)`` from a parsed/cached dir.

    ``markdown`` is "" if no ``.md`` exists; ``blocks`` is the parsed
    ``*_content_list.json`` or ``None``; ``asset_dir`` is the ``images/`` dir if
    present.
    """
    content_dir = find_content_dir(workdir)

    markdown = ""
    md_files = list(content_dir.glob("*.md"))
    if md_files:
        markdown = md_files[0].read_text(encoding="utf-8")

    blocks: Optional[list[dict]] = None
    json_files = list(content_dir.glob("*_content_list.json"))
    if json_files:
        try:
            loaded = json.loads(json_files[0].read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                blocks = loaded
        except Exception as exc:
            logger.warning("Failed to read content_list %s: %s", json_files[0], exc)

    images_dir = content_dir / "images"
    asset_dir = images_dir if images_dir.is_dir() else None

    return markdown, blocks, asset_dir


__all__ = [
    "MANIFEST_FILENAME",
    "source_hash_from_path",
    "signature_dir",
    "is_ready",
    "lookup",
    "reserve",
    "write_manifest",
    "cleanup_failed",
    "find_content_dir",
    "load_ir",
]
