"""Atomic KB index rebuild after web-source sync.

All functions here operate on the KB's ``raw/`` directory and produce
a new index version via ``RAGService.initialize``, keeping the previous
version intact for rollback.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def needs_initial_index(kb_dir: Path) -> bool:
    """Return True if the KB has no usable index version yet."""
    try:
        from deeptutor.services.rag.index_versioning import list_kb_versions

        versions = list_kb_versions(kb_dir)
        return not any(v.get("ready") for v in versions)
    except Exception:
        return False


async def rebuild_index_async(
    kb_name: str,
    base_dir: str,
    raw_dir: Path,
    *,
    validation_queries: list[str] | None = None,
) -> int:
    """Rebuild the KB index from all files in ``raw/`` atomically.

    Uses ``RAGService.initialize`` which writes to a new version dir,
    keeping the old version intact for rollback.

    Returns the number of files indexed.
    """
    from deeptutor.services.rag.file_routing import FileTypeRouter
    from deeptutor.services.rag.service import RAGService

    supported = FileTypeRouter.collect_supported_files(raw_dir, recursive=True)
    if not supported:
        logger.warning("No supported files found in %s, skipping index rebuild", raw_dir)
        return 0
    provider = resolve_rag_provider(base_dir, kb_name)
    if provider != "llamaindex":
        raise RuntimeError(
            f"Validated web-source index publishing is only supported for LlamaIndex; "
            f"KB '{kb_name}' uses '{provider}'"
        )

    file_paths = [str(f) for f in supported]
    from deeptutor.services.rag.index_versioning import list_kb_versions

    kb_dir = Path(base_dir) / kb_name
    before = list_kb_versions(kb_dir)
    previous_ready = next((entry for entry in before if entry.get("ready")), None)
    rag_service = RAGService(kb_base_dir=base_dir)
    try:
        success = await rag_service.initialize(
            kb_name=kb_name,
            file_paths=file_paths,
            published=False,
        )
    except Exception:
        for entry in _new_versions(before, list_kb_versions(kb_dir)):
            _quarantine_candidate(Path(str(entry["version_path"])))
        raise

    if not success:
        raise RuntimeError(f"Index rebuild returned failure for KB '{kb_name}'")

    candidates = _new_versions(before, list_kb_versions(kb_dir))
    if len(candidates) != 1:
        for entry in candidates:
            _quarantine_candidate(Path(str(entry["version_path"])))
        raise RuntimeError(
            f"Expected one candidate index version for KB '{kb_name}', found {len(candidates)}"
        )
    candidate = candidates[0]
    candidate_path = Path(str(candidate["version_path"]))

    queries = _validation_queries(raw_dir, file_paths, configured=validation_queries)
    try:
        await validate_candidate_index(kb_name, base_dir, candidate_path, queries)
    except Exception as exc:
        _record_failed_validation(kb_name, base_dir, candidate_path, str(exc))
        raise RuntimeError(
            f"Candidate index validation failed for KB '{kb_name}' "
            f"({candidate_path.name}): {exc}"
        ) from exc

    _publish_candidate(
        candidate_path,
        queries=queries,
        previous_version=str(previous_ready.get("version") or "") if previous_ready else "",
    )

    update_file_hashes(kb_name, base_dir, raw_dir, file_paths)
    logger.info("Rebuilt index for KB '%s' with %d files", kb_name, len(file_paths))
    return len(file_paths)


def _new_versions(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict]:
    before_paths = {str(entry.get("version_path") or entry.get("storage_path")) for entry in before}
    return [
        entry
        for entry in after
        if str(entry.get("version_path") or entry.get("storage_path")) not in before_paths
    ]


def _validation_queries(
    raw_dir: Path,
    file_paths: list[str],
    *,
    configured: list[str] | None = None,
) -> list[str]:
    if configured:
        return [query.strip() for query in configured if query.strip()]
    queries: list[str] = []
    for fpath_str in file_paths[:5]:
        fpath = Path(fpath_str)
        title = ""
        try:
            for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    title = stripped.lstrip("#").strip()
                    break
        except OSError:
            pass
        queries.append(title or fpath.stem.replace("-", " "))
    return queries[:3] or ["documentation"]


async def validate_candidate_index(
    kb_name: str,
    base_dir: str,
    candidate_path: Path,
    queries: list[str],
) -> None:
    """Run representative retrievals directly against an unpublished index."""
    provider = resolve_rag_provider(base_dir, kb_name)
    if provider != "llamaindex":
        raise RuntimeError(f"candidate validation is not implemented for provider '{provider}'")

    from deeptutor.services.rag.pipelines.llamaindex import storage

    if not queries:
        raise RuntimeError("no representative validation queries were provided")
    for query in queries:
        nodes = await asyncio.to_thread(
            storage.retrieve_nodes,
            candidate_path,
            query,
            top_k=3,
        )
        if not nodes or not any(str(getattr(node.node, "text", "") or "").strip() for node in nodes):
            raise RuntimeError(f"representative query returned no indexed content: {query!r}")


def _read_meta(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_meta(path: Path, payload: dict[str, Any]) -> None:
    from deeptutor.services.file_io import atomic_write_json

    atomic_write_json(path / "meta.json", payload)


def _quarantine_candidate(path: Path) -> None:
    if not path.exists():
        return
    failed = path.with_name(f"failed-{path.name}")
    suffix = 1
    while failed.exists():
        failed = path.with_name(f"failed-{path.name}-{suffix}")
        suffix += 1
    path.rename(failed)


def _record_failed_validation(
    kb_name: str,
    base_dir: str,
    candidate_path: Path,
    error: str,
) -> None:
    _write_meta(
        candidate_path,
        {
            **_read_meta(candidate_path),
            "published": False,
            "validation_failed": True,
            "validation_error": error,
            "validated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    _quarantine_candidate(candidate_path)

    metadata_file = Path(base_dir) / kb_name / "metadata.json"
    metadata = {}
    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    from deeptutor.services.file_io import atomic_write_json

    atomic_write_json(
        metadata_file,
        {
            **metadata,
            "needs_reindex": True,
            "last_indexed_action": "web_sync_candidate_validation_failed",
            "last_index_error": error,
        },
    )


def _publish_candidate(
    candidate_path: Path,
    *,
    queries: list[str],
    previous_version: str,
) -> None:
    _write_meta(
        candidate_path,
        {
            **_read_meta(candidate_path),
            "published": True,
            "validation_failed": False,
            "validation_error": "",
            "validation_queries": queries,
            "previous_version": previous_version,
            "validated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def update_file_hashes(kb_name: str, base_dir: str, raw_dir: Path, file_paths: list[str]) -> None:
    """Record content hashes for all indexed files in metadata.json."""
    import json

    from deeptutor.knowledge.add_documents import _raw_hash_key
    from deeptutor.services.file_io import atomic_write_json

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
