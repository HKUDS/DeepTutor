"""Freeze extracted document figures into a LlamaIndex version directory.

Parse engines write images under ``parse_cache/.../images/``. Retrieval and
the chat UI cannot serve those cache paths, so indexing copies them into
``version-N/assets/<origin>/<file>`` and records a small manifest used to
attach figures to text hits (even when multimodal ImageNode indexing is off).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.parse import quote

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.rag.file_routing import FileTypeRouter

ASSETS_DIRNAME = "assets"
MANIFEST_FILENAME = "manifest.json"
TEXT_IMAGE_CAP = 3

_PAGE_PATTERNS = (
    re.compile(r"(?:^|[-_])page[-_]?(\d+)", re.I),
    re.compile(r"(?:^|[-_])pg[-_]?(\d+)", re.I),
    re.compile(r"(?:^|[-_])p(\d+)(?:[-_.]|$)", re.I),
)
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ImageAssetSource:
    """An extracted (or standalone) image plus the document it belongs to."""

    path: Path
    origin: Path
    page: str = ""


def normalize_page(value: object) -> str:
    """Canonical page token for matching chunk metadata to asset records."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def page_from_filename(name: str) -> str:
    """Best-effort page number from common parser export names (e.g. page-3.png)."""
    for pattern in _PAGE_PATTERNS:
        match = pattern.search(name)
        if match:
            return match.group(1)
    return ""


def page_from_blocks(blocks: list[dict[str, Any]] | None, filename: str) -> str:
    """Look up a figure's page in parser IR blocks (MinerU ``content_list`` shape)."""
    if not blocks:
        return ""
    for block in blocks:
        if not isinstance(block, dict):
            continue
        img = str(block.get("img_path") or block.get("image_path") or block.get("path") or "")
        if Path(img).name != filename:
            continue
        if "page_idx" in block and block.get("page_idx") is not None:
            try:
                return str(int(block["page_idx"]) + 1)
            except (TypeError, ValueError):
                pass
        for key in ("page_label", "page"):
            page = normalize_page(block.get(key))
            if page:
                return page
    return ""


def assets_dir(storage_dir: Path) -> Path:
    return Path(storage_dir) / ASSETS_DIRNAME


def manifest_path(storage_dir: Path) -> Path:
    return assets_dir(storage_dir) / MANIFEST_FILENAME


def asset_rel_path(origin_name: str, image_name: str) -> str:
    origin = _UNSAFE_NAME.sub("_", Path(origin_name).name) or "document"
    image = Path(image_name).name
    if not image or image in {".", ".."}:
        raise ValueError(f"invalid image name: {image_name!r}")
    return f"{origin}/{image}"


def index_asset_url(kb_name: str, rel_path: str) -> str:
    """HTTP path the web client can pass to ``apiUrl`` / ``<img src>``."""
    encoded_kb = quote(str(kb_name), safe="")
    encoded_rel = "/".join(quote(part, safe="") for part in Path(rel_path).parts)
    return f"/api/knowledge-bases/{encoded_kb}/index-assets/{encoded_rel}"


def load_asset_manifest(storage_dir: Path | None) -> dict[str, Any]:
    if storage_dir is None:
        return {"assets": []}
    path = manifest_path(storage_dir)
    if not path.is_file():
        return {"assets": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"assets": []}
    if not isinstance(payload, dict):
        return {"assets": []}
    records = payload.get("assets")
    if not isinstance(records, list):
        payload["assets"] = []
    return payload


def image_ref(record: dict[str, Any], kb_name: str) -> dict[str, Any]:
    rel = str(record.get("rel_path") or "")
    mime = str(record.get("mime") or "")
    if not mime:
        mime = mimetypes.guess_type(Path(rel).name)[0] or "application/octet-stream"
    ref: dict[str, Any] = {
        "image_url": index_asset_url(kb_name, rel),
        "mime_type": mime,
    }
    description = str(record.get("description") or "").strip()
    if description:
        ref["image_description"] = description
    page = normalize_page(record.get("page"))
    if page:
        ref["page"] = page
    return ref


def match_images_for_source(
    manifest: dict[str, Any],
    *,
    origin_name: str,
    page: object = "",
    kb_name: str,
    cap: int = TEXT_IMAGE_CAP,
) -> list[dict[str, Any]]:
    """Pick figures to attach to a retrieved text chunk.

    Same-origin + same-page wins. If the chunk has no page, return the first
    ``cap`` figures from that origin so STEM PDFs still show nearby diagrams.
    """
    origin = Path(str(origin_name or "")).name
    if not origin:
        return []
    entries = [
        item
        for item in (manifest.get("assets") or [])
        if isinstance(item, dict) and Path(str(item.get("origin_name") or "")).name == origin
    ]
    page_key = normalize_page(page)
    if page_key:
        matched = [item for item in entries if normalize_page(item.get("page")) == page_key]
        entries = matched
    return [image_ref(item, kb_name) for item in entries[: max(0, cap)] if item.get("rel_path")]


def freeze_image_assets(
    storage_dir: Path,
    sources: list[ImageAssetSource],
    documents: list[Any] | None = None,
) -> dict[str, Any]:
    """Copy ``sources`` into ``storage_dir/assets`` and merge the manifest.

    Stamps ``asset_rel_path`` (and frozen ``image_path``) onto matching image
    documents so the persisted LlamaIndex docstore never points at parse cache.
    """
    storage = Path(storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    root = assets_dir(storage)
    root.mkdir(parents=True, exist_ok=True)

    existing = load_asset_manifest(storage)
    by_rel: dict[str, dict[str, Any]] = {}
    for item in existing.get("assets") or []:
        if isinstance(item, dict) and item.get("rel_path"):
            by_rel[str(item["rel_path"])] = item

    for source in sources:
        rel = asset_rel_path(source.origin.name, source.path.name)
        dest = root / Path(rel)
        _copy_under_assets(source.path, dest, allowed_root=root)
        mime = mimetypes.guess_type(source.path.name)[0] or "application/octet-stream"
        record = {
            "origin_name": source.origin.name,
            "page": normalize_page(source.page) or page_from_filename(source.path.name),
            "rel_path": rel,
            "mime": mime,
        }
        previous = by_rel.get(rel) or {}
        if previous.get("description") and not record.get("description"):
            record["description"] = previous["description"]
        by_rel[rel] = record
        _stamp_image_documents(documents or [], source, rel, dest, record)

    payload = {"assets": list(by_rel.values())}
    atomic_write_json(manifest_path(storage), payload)
    return payload


def _copy_under_assets(source: Path, dest: Path, *, allowed_root: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise OSError(f"Source is not an ordinary file: {source}")
    resolved_source = source.resolve(strict=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    shutil.copyfile(resolved_source, dest)
    resolved_dest = dest.resolve(strict=True)
    resolved_root = allowed_root.resolve(strict=True)
    try:
        resolved_dest.relative_to(resolved_root)
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise OSError(f"Frozen asset escaped assets dir: {dest}") from exc


def _stamp_image_documents(
    documents: list[Any],
    source: ImageAssetSource,
    rel: str,
    dest: Path,
    record: dict[str, Any],
) -> None:
    origin_name = source.origin.name
    image_name = source.path.name
    for doc in documents:
        meta = getattr(doc, "metadata", None)
        if not isinstance(meta, dict):
            continue
        if meta.get("content_type") != "image":
            continue
        if meta.get("file_name") not in {origin_name, image_name}:
            continue
        current_path = Path(str(getattr(doc, "image_path", "") or ""))
        if current_path.name and current_path.name != image_name:
            continue
        meta["asset_rel_path"] = rel
        if record.get("page") and not meta.get("page"):
            meta["page"] = record["page"]
        description = str(meta.get("image_description") or "").strip()
        if description:
            record["description"] = description
        if hasattr(doc, "image_path"):
            doc.image_path = str(dest)
        if hasattr(doc, "image_mimetype") and record.get("mime"):
            doc.image_mimetype = record["mime"]


def attach_figure_fields(
    item: dict[str, Any],
    *,
    meta: dict[str, Any],
    kb_name: str,
    manifest: dict[str, Any],
    image_mimetype: str = "",
) -> dict[str, Any]:
    """Add ``image_url`` / ``images`` to a retrieval source without filesystem paths."""
    content_type = str(item.get("content_type") or meta.get("content_type") or "text")
    item["content_type"] = content_type
    if not kb_name:
        return item
    if content_type == "image":
        rel = str(meta.get("asset_rel_path") or "")
        if rel:
            item["image_url"] = index_asset_url(kb_name, rel)
        description = str(meta.get("image_description") or "").strip()
        if description:
            item["image_description"] = description
        mime = str(meta.get("image_mimetype") or image_mimetype or "").strip()
        if not mime and rel:
            mime = mimetypes.guess_type(Path(rel).name)[0] or ""
        if mime:
            item["mime_type"] = mime
        return item
    origin = str(meta.get("asset_origin") or meta.get("file_name") or "")
    related = match_images_for_source(
        manifest, origin_name=origin, page=item.get("page"), kb_name=kb_name
    )
    if related:
        item["images"] = related
    return item


def is_image_asset_filename(name: str) -> bool:
    return Path(name).suffix.lower() in FileTypeRouter.IMAGE_EXTENSIONS


__all__ = [
    "ASSETS_DIRNAME",
    "ImageAssetSource",
    "TEXT_IMAGE_CAP",
    "asset_rel_path",
    "assets_dir",
    "attach_figure_fields",
    "freeze_image_assets",
    "image_ref",
    "index_asset_url",
    "is_image_asset_filename",
    "load_asset_manifest",
    "match_images_for_source",
    "normalize_page",
    "page_from_blocks",
    "page_from_filename",
]
