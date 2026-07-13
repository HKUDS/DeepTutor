"""On-disk manifest for a PageIndex-backed knowledge base.

PageIndex has no embeddings, so there is nothing to vectorise locally. The only
local state is a lightweight manifest mapping each ingested file to its hosted
``doc_id``. It is written into the KB's flat ``version-N`` directory (reusing
``index_versioning`` with a ``None`` signature) so the Index-versions UI and the
"is this KB initialised?" checks see a ready version just like LlamaIndex KBs —
only the file contents differ (a doc-id map instead of a vector store).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "pageindex_docs.json"
META_FILENAME = "meta.json"
PROVIDER = "pageindex"


def _empty_manifest() -> dict[str, Any]:
    return {"provider": PROVIDER, "docs": {}}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def manifest_path(storage_dir: Path) -> Path:
    return Path(storage_dir) / MANIFEST_FILENAME


def read_manifest(storage_dir: Path | None) -> dict[str, Any]:
    if storage_dir is None:
        return _empty_manifest()
    path = manifest_path(storage_dir)
    if not path.exists():
        return _empty_manifest()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read PageIndex manifest %s: %s", path, exc)
        return _empty_manifest()
    if not isinstance(data, dict):
        return _empty_manifest()
    data.setdefault("provider", PROVIDER)
    if not isinstance(data.get("docs"), dict):
        data["docs"] = {}
    return data


def write_manifest(storage_dir: Path, manifest: dict[str, Any]) -> None:
    _atomic_write_json(manifest_path(storage_dir), manifest)


def write_meta(storage_dir: Path) -> None:
    """Write a flat-layout ``meta.json`` so the version is listed as ready.

    Mirrors ``index_versioning.write_version_meta`` but carries a synthetic
    ``pageindex`` signature instead of an embedding hash.
    """
    target = Path(storage_dir)
    payload = {
        "version": target.name,
        "signature": PROVIDER,
        "provider": PROVIDER,
        "layout": "flat",
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
    }
    _atomic_write_json(target / META_FILENAME, payload)


def doc_entries(manifest: dict[str, Any]) -> dict[str, Any]:
    docs = manifest.get("docs")
    return docs if isinstance(docs, dict) else {}


def doc_ids(manifest: dict[str, Any]) -> list[str]:
    return [
        str(entry["doc_id"])
        for entry in doc_entries(manifest).values()
        if isinstance(entry, dict) and entry.get("doc_id")
    ]


def upsert_doc(
    manifest: dict[str, Any],
    file_name: str,
    doc_id: str,
    *,
    size: int | None = None,
) -> None:
    docs = manifest.setdefault("docs", {})
    docs[file_name] = {
        "doc_id": doc_id,
        "size": size,
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


__all__ = [
    "MANIFEST_FILENAME",
    "PROVIDER",
    "manifest_path",
    "read_manifest",
    "write_manifest",
    "write_meta",
    "doc_entries",
    "doc_ids",
    "upsert_doc",
]
