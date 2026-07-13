"""On-disk layout for a LightRAG-backed knowledge base.

Like the GraphRAG/PageIndex pipelines, a LightRAG KB keeps a self-contained
store inside the KB's flat ``version-N`` directory (reused from
``index_versioning`` with a ``None`` signature). That dir is LightRAG's
``working_dir``: LightRAG writes its KV stores, vector DBs and the knowledge
graph there::

    <kb_dir>/version-N/
        kv_store_*.json
        vdb_*.json
        graph_chunk_entity_relation.graphml
        meta.json            # synthetic "ready" marker (see write_meta)

The synthetic ``meta.json`` makes the existing "is this KB initialised?" and
index-versions UI checks treat a LightRAG KB as ready without teaching the
manager about LightRAG internals.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

META_FILENAME = "meta.json"
PROVIDER = "lightrag"

# Glob patterns LightRAG writes once it has actually built chunk/vector data.
# A graphml file alone is not enough: LightRAG creates an empty graph at startup
# before any document is successfully processed.
_OUTPUT_GLOBS = ("vdb_*.json", "kv_store_text_chunks.json")
_DOC_STATUS_FILENAME = "kv_store_doc_status.json"
_SUCCESS_STATUSES = {"processed", "completed", "done", "success", "indexed"}
_FAILED_STATUSES = {"failed", "error"}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def working_dir(root_dir: Path) -> Path:
    """LightRAG's working dir == the version-N root."""
    return Path(root_dir)


def has_output(root_dir: Path | None) -> bool:
    """True when LightRAG has at least one successfully indexed document."""
    if root_dir is None:
        return False
    root = Path(root_dir)
    if not root.is_dir():
        return False

    status_signal = _doc_status_has_success(root)
    if status_signal is not None:
        return status_signal

    for pattern in _OUTPUT_GLOBS:
        for path in root.glob(pattern):
            try:
                if path.is_file() and path.stat().st_size > 2:
                    return True
            except OSError:
                continue
    return False


def _doc_status_has_success(root_dir: Path) -> bool | None:
    payload = _read_doc_status(root_dir)
    if not payload:
        return None

    saw_failure = False
    for item in payload.values():
        if not isinstance(item, dict):
            continue
        chunks = item.get("chunks_list")
        if isinstance(chunks, list) and len(chunks) > 0:
            return True
        status = str(item.get("status") or "").lower()
        if status in _SUCCESS_STATUSES:
            return True
        if status in _FAILED_STATUSES:
            saw_failure = True

    return False if saw_failure else None


def failure_summary(root_dir: Path | None, *, limit: int = 3) -> str:
    """Return a short human-readable summary of failed LightRAG documents."""
    if root_dir is None:
        return ""
    payload = _read_doc_status(Path(root_dir))
    if not payload:
        return ""

    failures: list[str] = []
    for item in payload.values():
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").lower()
        error = str(item.get("error_msg") or "").strip()
        if status not in _FAILED_STATUSES and not error:
            continue
        name = str(item.get("file_path") or "document").strip()
        failures.append(f"{name}: {error or status}")
        if len(failures) >= limit:
            break
    return "; ".join(failures)


def document_error(root_dir: Path | None, doc_id: str) -> str:
    """Return the stored LightRAG error for one document, if present."""
    if root_dir is None or not doc_id:
        return ""
    payload = _read_doc_status(Path(root_dir))
    if not payload:
        return ""
    item = payload.get(doc_id)
    if not isinstance(item, dict):
        return ""
    status = str(item.get("status") or "").lower()
    error = str(item.get("error_msg") or "").strip()
    if status in _FAILED_STATUSES or error:
        return error or status
    return ""


def _read_doc_status(root_dir: Path) -> dict[str, Any] | None:
    path = root_dir / _DOC_STATUS_FILENAME
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        logger.warning("Failed to read LightRAG doc status %s: %s", path, exc)
        return None


def write_meta(root_dir: Path) -> None:
    """Write a flat-layout ``meta.json`` so the version lists as ready.

    Mirrors ``index_versioning.write_version_meta`` but carries a synthetic
    ``lightrag`` signature instead of an embedding hash. The embedding identity
    is stamped alongside so an externally-linked index can be checked for
    embedding compatibility at connect time (LightRAG otherwise fails retrieval
    silently on a dimension mismatch).
    """
    from deeptutor.services.rag.embedding_signature import embedding_meta_fields

    target = Path(root_dir)
    payload = {
        "version": target.name,
        "signature": PROVIDER,
        "provider": PROVIDER,
        "layout": "flat",
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        **embedding_meta_fields(),
    }
    _atomic_write_json(target / META_FILENAME, payload)


__all__ = [
    "META_FILENAME",
    "PROVIDER",
    "document_error",
    "failure_summary",
    "working_dir",
    "has_output",
    "write_meta",
]
