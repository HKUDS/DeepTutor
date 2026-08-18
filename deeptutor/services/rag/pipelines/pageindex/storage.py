"""On-disk manifest for a PageIndex-backed knowledge base.

PageIndex has no embeddings, so there is no model-specific index version. The
manifest lives at the KB root and PageIndex OSS keeps its Local Library in the
``pageindex/`` child directory. Older ``version-N`` manifests remain readable.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.services.file_io import atomic_write_json

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "pageindex_docs.json"
SDK_STORAGE_DIRNAME = "pageindex"
CLOUD_PROVIDER = "pageindex"
OSS_PROVIDER = "pageindex-oss"


def _empty_manifest(provider: str = CLOUD_PROVIDER) -> dict[str, Any]:
    return {"provider": provider, "docs": {}}


def manifest_path(storage_dir: Path) -> Path:
    return Path(storage_dir) / MANIFEST_FILENAME


def read_manifest(
    storage_dir: Path | None,
    *,
    provider: str = CLOUD_PROVIDER,
) -> dict[str, Any]:
    if storage_dir is None:
        return _empty_manifest(provider)
    path = manifest_path(storage_dir)
    if not path.exists():
        return _empty_manifest(provider)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read PageIndex manifest %s: %s", path, exc)
        return _empty_manifest(provider)
    if not isinstance(data, dict):
        return _empty_manifest(provider)
    data.setdefault("provider", provider)
    if not isinstance(data.get("docs"), dict):
        data["docs"] = {}
    return data


def write_manifest(storage_dir: Path, manifest: dict[str, Any]) -> None:
    atomic_write_json(manifest_path(storage_dir), manifest)


def find_storage_dir(kb_dir: Path, *, provider: str) -> Path | None:
    """Find the root manifest, falling back to the newest legacy version."""
    root = Path(kb_dir)

    def matches(candidate: Path) -> bool:
        if not manifest_path(candidate).is_file():
            return False
        manifest = read_manifest(candidate, provider=provider)
        return str(manifest.get("provider") or provider) == provider

    if matches(root):
        return root

    from deeptutor.services.rag.index_versioning import list_kb_versions

    for entry in list_kb_versions(root):
        candidate = Path(str(entry.get("storage_path") or ""))
        if matches(candidate):
            return candidate
    return None


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


def remove_doc(manifest: dict[str, Any], file_name: str) -> dict[str, Any] | None:
    entry = doc_entries(manifest).pop(file_name, None)
    return entry if isinstance(entry, dict) else None


def sdk_storage_path(storage_dir: Path) -> Path:
    return Path(storage_dir) / SDK_STORAGE_DIRNAME


__all__ = [
    "MANIFEST_FILENAME",
    "CLOUD_PROVIDER",
    "OSS_PROVIDER",
    "SDK_STORAGE_DIRNAME",
    "manifest_path",
    "find_storage_dir",
    "read_manifest",
    "write_manifest",
    "doc_entries",
    "doc_ids",
    "upsert_doc",
    "remove_doc",
    "sdk_storage_path",
]
