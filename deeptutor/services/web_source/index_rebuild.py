"""Atomic KB index rebuild after web-source sync.

All functions here operate on the KB's ``raw/`` directory and produce
a new index version via ``RAGService.initialize``, keeping the previous
version intact for rollback.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def needs_initial_index(kb_dir: Path) -> bool:
    """Return True if the KB has no usable index version yet."""
    try:
        from deeptutor.services.rag.index_versioning import list_kb_versions
        versions = list_kb_versions(kb_dir)
        return not any(v.get("ready") for v in versions)
    except Exception:
        return False


async def rebuild_index_async(kb_name: str, base_dir: str, raw_dir: Path) -> int:
    """Rebuild the KB index from all files in ``raw/`` atomically.

    Uses ``RAGService.initialize`` which writes to a new version dir,
    keeping the old version intact for rollback.

    Returns the number of files indexed.
    """
    from deeptutor.services.rag.service import RAGService
    from deeptutor.services.rag.file_routing import FileTypeRouter

    supported = FileTypeRouter.collect_supported_files(raw_dir, recursive=True)
    if not supported:
        logger.warning("No supported files found in %s, skipping index rebuild", raw_dir)
        return 0

    file_paths = [str(f) for f in supported]
    rag_service = RAGService(kb_base_dir=base_dir)
    success = await rag_service.initialize(kb_name=kb_name, file_paths=file_paths)

    if not success:
        raise RuntimeError(f"Index rebuild returned failure for KB '{kb_name}'")

    update_file_hashes(kb_name, base_dir, raw_dir, file_paths)
    logger.info("Rebuilt index for KB '%s' with %d files", kb_name, len(file_paths))
    return len(file_paths)


def update_file_hashes(
    kb_name: str, base_dir: str, raw_dir: Path, file_paths: list[str]
) -> None:
    """Record content hashes for all indexed files in metadata.json."""
    import json
    from deeptutor.services.file_io import atomic_write_json
    from deeptutor.knowledge.add_documents import _raw_hash_key

    kb_dir = Path(base_dir) / kb_name
    metadata_file = kb_dir / "metadata.json"
    metadata = {}
    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}

    hashes = metadata.setdefault("file_hashes", {})
    for fpath_str in file_paths:
        fpath = Path(fpath_str)
        sha = hashlib.sha256()
        with open(fpath, "rb") as fh:
            for block in iter(lambda: fh.read(65536), b""):
                sha.update(block)
        hashes[_raw_hash_key(fpath, raw_dir)] = sha.hexdigest()

    metadata["rag_provider"] = resolve_rag_provider(base_dir, kb_name)
    metadata["needs_reindex"] = False
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata["last_updated"] = ts
    metadata["last_indexed_at"] = ts
    metadata["last_indexed_count"] = len(file_paths)
    metadata["last_indexed_action"] = "web_sync_rebuild"
    atomic_write_json(metadata_file, metadata)


def resolve_rag_provider(base_dir: str, kb_name: str) -> str:
    """Resolve the RAG provider name for a KB."""
    try:
        from deeptutor.services.rag.provider_binding import resolve_bound_provider
        return resolve_bound_provider(base_dir, kb_name)
    except Exception:
        from deeptutor.services.rag.factory import DEFAULT_PROVIDER
        return DEFAULT_PROVIDER
