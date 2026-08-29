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
from typing import Any

from deeptutor.services.file_io import atomic_write_json

logger = logging.getLogger(__name__)

META_FILENAME = "meta.json"
PROVIDER = "lightrag"
ADAPTER_SCHEMA = 2
PUBLISHED_STATE = "published"

# Glob patterns LightRAG writes once it has actually built chunk/vector data.
# A graphml file alone is not enough: LightRAG creates an empty graph at startup
# before any document is successfully processed.
_OUTPUT_GLOBS = ("vdb_*.json", "kv_store_text_chunks.json")
_DOC_STATUS_FILENAME = "kv_store_doc_status.json"
_SUCCESS_STATUSES = {"processed", "completed", "done", "success", "indexed"}
_FAILED_STATUSES = {"failed", "error"}


def working_dir(root_dir: Path) -> Path:
    """LightRAG's working dir == the version-N root."""
    return Path(root_dir)


def _store_root(root_dir: Path) -> Path:
    """Resolve native workspace storage while retaining legacy flat reads."""
    root = Path(root_dir)
    if (root / _DOC_STATUS_FILENAME).exists() or any(root.glob("vdb_*.json")):
        return root
    meta = _read_meta(root)
    workspace = str((meta or {}).get("workspace") or "").strip()
    if not workspace:
        from .engine import workspace_for

        workspace = workspace_for(root)
    candidate = root / workspace
    return candidate if candidate.is_dir() else root


def has_output(root_dir: Path | None) -> bool:
    """True when LightRAG has at least one successfully indexed document."""
    if root_dir is None:
        return False
    root = _store_root(Path(root_dir))
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
    payload = _read_doc_status(_store_root(Path(root_dir)))
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
    payload = _read_doc_status(_store_root(Path(root_dir)))
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


def has_any_doc_status(root_dir: Path | None) -> bool:
    if root_dir is None:
        return False
    payload = _read_doc_status(_store_root(Path(root_dir)))
    return bool(payload)


def _read_meta(root_dir: Path) -> dict[str, Any] | None:
    path = Path(root_dir) / META_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def meta_is_native_published(root_dir: Path | None) -> bool:
    if root_dir is None:
        return False
    meta = _read_meta(Path(root_dir))
    return bool(
        meta
        and meta.get("provider") == PROVIDER
        and meta.get("signature") == PROVIDER
        and meta.get("lightrag_adapter_schema") == ADAPTER_SCHEMA
        and meta.get("parser_bridge_schema") == 1
        and meta.get("state") == PUBLISHED_STATE
        and has_output(Path(root_dir))
    )


def _parser_inputs(root_dir: Path) -> list[dict[str, str]]:
    from .ingress import bundles_root, load_verified_bundle

    records: set[tuple[str, str]] = set()
    for bundle in sorted(bundles_root(root_dir).glob("*.bundle")):
        canonical_name = bundle.name.removesuffix(".bundle")
        manifest, _ = load_verified_bundle(root_dir, canonical_name)
        parser = manifest.get("parser")
        if not isinstance(parser, dict):
            continue
        records.add(
            (
                str(parser.get("engine") or ""),
                str(parser.get("parser_signature") or ""),
            )
        )
    return [
        {"engine": engine, "parser_signature": signature} for engine, signature in sorted(records)
    ]


def write_meta(root_dir: Path) -> None:
    """Write a flat-layout ``meta.json`` so the version lists as ready.

    Mirrors ``index_versioning.write_version_meta`` but carries a synthetic
    ``lightrag`` signature instead of an embedding hash. The embedding identity
    is stamped alongside so an externally-linked index can be checked for
    embedding compatibility at connect time (LightRAG otherwise fails retrieval
    silently on a dimension mismatch).
    """
    from deeptutor.services.rag.embedding_signature import embedding_meta_fields

    from .engine import installed_version, workspace_for

    target = Path(root_dir)
    previous = _read_meta(target) or {}
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    payload = {
        "version": target.name,
        "signature": PROVIDER,
        "provider": PROVIDER,
        "state": PUBLISHED_STATE,
        "lightrag_adapter_schema": ADAPTER_SCHEMA,
        "lightrag_package_version": installed_version(),
        "parser_bridge_schema": 1,
        "parser_inputs": _parser_inputs(target),
        "workspace": workspace_for(target),
        "layout": "flat",
        "created_at": str(previous.get("created_at") or now),
        "updated_at": now,
        **embedding_meta_fields(),
    }
    atomic_write_json(target / META_FILENAME, payload)


__all__ = [
    "META_FILENAME",
    "PROVIDER",
    "document_error",
    "failure_summary",
    "has_any_doc_status",
    "working_dir",
    "has_output",
    "meta_is_native_published",
    "write_meta",
]
