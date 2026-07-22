"""Provider-owned index readiness probes.

DeepTutor owns KB lifecycle/status, but each RAG provider owns the shape of its
persisted index. This module is the narrow read-only seam between those worlds:
callers ask "is this provider index really queryable?" and get a structured
answer without knowing provider-specific filenames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from deeptutor.services.rag.factory import (
    DEFAULT_PROVIDER,
    GRAPHRAG_PROVIDER,
    LIGHTRAG_PROVIDER,
    PAGEINDEX_PROVIDER,
    normalize_provider_name,
    version_matches_provider,
)


@dataclass(frozen=True)
class ProviderIndexProbe:
    """Read-only verdict for one provider storage directory."""

    provider: str
    storage_dir: str | None
    ready: bool
    failure_summary: str = ""
    doc_count: int | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


def inspect_provider_index(
    provider: str | None, storage_dir: str | Path | None
) -> ProviderIndexProbe:
    """Inspect one provider storage directory using real provider artifacts."""
    resolved = normalize_provider_name(provider)
    path = Path(storage_dir) if storage_dir is not None else None
    if path is None:
        return ProviderIndexProbe(resolved, None, False, "No storage path recorded.")
    if resolved == PAGEINDEX_PROVIDER:
        return _inspect_pageindex(path)
    if resolved == GRAPHRAG_PROVIDER:
        return _inspect_graphrag(path)
    if resolved == LIGHTRAG_PROVIDER:
        return _inspect_lightrag(path)
    return _inspect_llamaindex(path)


def inspect_provider_version(entry: dict[str, Any], provider: str | None) -> ProviderIndexProbe:
    """Inspect a version-list entry for ``provider``."""
    resolved = normalize_provider_name(provider)
    storage_path = entry.get("storage_path")
    if not storage_path:
        return ProviderIndexProbe(resolved, None, False, "No storage path recorded.")
    if not version_matches_provider(entry, resolved):
        return ProviderIndexProbe(
            resolved,
            str(storage_path),
            False,
            diagnostics={
                "version_provider": entry.get("provider"),
                "version_signature": entry.get("signature"),
                "provider_mismatch": True,
            },
        )
    return inspect_provider_index(resolved, Path(str(storage_path)))


def inspect_kb_versions(kb_dir: str | Path, provider: str | None) -> list[dict[str, Any]]:
    """Return version entries annotated with provider-probe readiness."""
    from deeptutor.services.rag.index_versioning import list_kb_versions

    versions: list[dict[str, Any]] = []
    for entry in list_kb_versions(Path(kb_dir)):
        adjusted = dict(entry)
        probe = inspect_provider_version(adjusted, provider)
        adjusted["ready"] = probe.ready
        if probe.failure_summary:
            adjusted["failure_summary"] = probe.failure_summary
        if probe.doc_count is not None:
            adjusted["doc_count"] = probe.doc_count
        if probe.diagnostics:
            adjusted["probe_diagnostics"] = probe.diagnostics
        versions.append(adjusted)
    return versions


def latest_ready_provider_version(
    kb_dir: str | Path, provider: str | None
) -> dict[str, Any] | None:
    """Return the newest provider-ready version, if any."""
    for entry in inspect_kb_versions(kb_dir, provider):
        if entry.get("ready"):
            return entry
    return None


def has_ready_provider_index(kb_dir: str | Path, provider: str | None) -> bool:
    """Return whether ``kb_dir`` has a genuinely ready index for ``provider``."""
    return latest_ready_provider_version(kb_dir, provider) is not None


def provider_failure_summary(
    kb_dir: str | Path,
    provider: str | None,
    *,
    limit: int = 3,
) -> str:
    """Return the first provider-specific failure summary under ``kb_dir``."""
    failures: list[str] = []
    for entry in inspect_kb_versions(kb_dir, provider):
        summary = str(entry.get("failure_summary") or "").strip()
        if summary:
            failures.append(summary)
        if len(failures) >= limit:
            break
    return "; ".join(failures[:limit])


def _inspect_llamaindex(storage_dir: Path) -> ProviderIndexProbe:
    diagnostics: dict[str, Any] = {}
    if not storage_dir.is_dir():
        return ProviderIndexProbe(
            DEFAULT_PROVIDER,
            str(storage_dir),
            False,
            "LlamaIndex storage directory does not exist.",
        )

    docstore = storage_dir / "docstore.json"
    index_store = storage_dir / "index_store.json"
    vector_stores = sorted(path.name for path in storage_dir.glob("*vector_store.json"))
    diagnostics["vector_stores"] = vector_stores

    if not docstore.exists():
        return ProviderIndexProbe(
            DEFAULT_PROVIDER,
            str(storage_dir),
            False,
            "Missing LlamaIndex docstore.json.",
            diagnostics=diagnostics,
        )
    if not index_store.exists():
        return ProviderIndexProbe(
            DEFAULT_PROVIDER,
            str(storage_dir),
            False,
            "Missing LlamaIndex index_store.json.",
            doc_count=_llamaindex_doc_count(docstore),
            diagnostics=diagnostics,
        )

    return ProviderIndexProbe(
        DEFAULT_PROVIDER,
        str(storage_dir),
        True,
        doc_count=_llamaindex_doc_count(docstore),
        diagnostics=diagnostics,
    )


def _inspect_pageindex(storage_dir: Path) -> ProviderIndexProbe:
    from deeptutor.services.rag.pipelines.pageindex import storage

    manifest = storage.read_manifest(storage_dir)
    ids = storage.doc_ids(manifest)
    if not ids:
        return ProviderIndexProbe(
            PAGEINDEX_PROVIDER,
            str(storage_dir),
            False,
            "PageIndex manifest has no document ids.",
            doc_count=0,
        )
    return ProviderIndexProbe(
        PAGEINDEX_PROVIDER,
        str(storage_dir),
        True,
        doc_count=len(ids),
        diagnostics={"manifest": str(storage.manifest_path(storage_dir))},
    )


def _inspect_graphrag(storage_dir: Path) -> ProviderIndexProbe:
    from deeptutor.services.rag.pipelines.graphrag import storage

    out = storage.output_dir(storage_dir)
    tables = [name for name in storage.OUTPUT_TABLES if (out / f"{name}.parquet").exists()]
    if not storage.has_output(storage_dir):
        return ProviderIndexProbe(
            GRAPHRAG_PROVIDER,
            str(storage_dir),
            False,
            "GraphRAG output has no core parquet tables.",
            diagnostics={"output_tables": tables},
        )
    return ProviderIndexProbe(
        GRAPHRAG_PROVIDER,
        str(storage_dir),
        True,
        diagnostics={"output_tables": tables},
    )


def _inspect_lightrag(storage_dir: Path) -> ProviderIndexProbe:
    from deeptutor.services.rag.pipelines.lightrag import storage

    failure = storage.failure_summary(storage_dir)
    ready = storage.has_output(storage_dir)
    return ProviderIndexProbe(
        LIGHTRAG_PROVIDER,
        str(storage_dir),
        ready,
        failure_summary="" if ready else failure,
        doc_count=_lightrag_doc_count(storage_dir),
    )


def _llamaindex_doc_count(docstore_path: Path) -> int | None:
    payload = _read_json(docstore_path)
    if not isinstance(payload, dict):
        return None
    data = payload.get("docstore/data")
    return len(data) if isinstance(data, dict) else None


def _lightrag_doc_count(storage_dir: Path) -> int | None:
    payload = _read_json(storage_dir / "kv_store_doc_status.json")
    if not isinstance(payload, dict):
        return None
    count = 0
    for item in payload.values():
        if not isinstance(item, dict):
            continue
        chunks = item.get("chunks_list")
        status = str(item.get("status") or "").lower()
        if (isinstance(chunks, list) and chunks) or status in {
            "processed",
            "completed",
            "done",
            "success",
            "indexed",
        }:
            count += 1
    return count


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


__all__ = [
    "ProviderIndexProbe",
    "inspect_provider_index",
    "inspect_provider_version",
    "inspect_kb_versions",
    "latest_ready_provider_version",
    "has_ready_provider_index",
    "provider_failure_summary",
]
