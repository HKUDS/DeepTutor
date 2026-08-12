"""Minimal structured visual-asset mapping for LlamaIndex ingestion."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.file_routing import FileTypeRouter

_VISUAL_BLOCK_TYPES = {"image", "table"}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StructuredVisualAsset:
    """One parser-referenced visual resource with basic provenance."""

    asset_id: str
    path: Path
    origin: Path
    resource_type: str
    block_index: int
    page_index: int | None
    bbox: tuple[float, float, float, float] | None
    caption: str
    text: str
    source_hash: str
    parser_signature: str


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return ""


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return tuple(float(item) for item in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _resolve_path(img_path: Any, asset_dir: Path) -> Path | None:
    if not isinstance(img_path, str) or not img_path.strip():
        return None
    raw = Path(img_path)
    if ".." in raw.parts:
        return None
    if raw.is_absolute():
        candidate = raw
    elif raw.parts and raw.parts[0] == asset_dir.name:
        candidate = asset_dir.parent / raw
    else:
        candidate = asset_dir / raw
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(asset_dir.resolve(strict=True))
    except (OSError, ValueError):
        return None
    if not resolved.is_file() or resolved.suffix.lower() not in FileTypeRouter.IMAGE_EXTENSIONS:
        return None
    return resolved


def _asset_id(
    parsed: ParsedDocument,
    *,
    origin: Path,
    block_index: int,
    resource_type: str,
    relative_path: str,
) -> str:
    payload = {
        "source": parsed.source_hash or str(origin.resolve()),
        "parser": parsed.parser_signature,
        "block_index": block_index,
        "resource_type": resource_type,
        "path": relative_path,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_structured_visual_assets(
    parsed: ParsedDocument, *, origin: Path
) -> list[StructuredVisualAsset]:
    """Return safe image/table resources explicitly referenced by parser blocks."""

    if not parsed.blocks or not parsed.asset_dir:
        return []
    asset_dir = Path(parsed.asset_dir)
    if not asset_dir.is_dir():
        return []

    assets: list[StructuredVisualAsset] = []
    for block_index, block in enumerate(parsed.blocks):
        if not isinstance(block, dict):
            continue
        resource_type = str(block.get("type") or "").strip().lower()
        if resource_type not in _VISUAL_BLOCK_TYPES:
            continue
        path = _resolve_path(block.get("img_path"), asset_dir)
        if path is None:
            logger.warning(
                "Skipped unsafe or missing structured visual reference at block %s in %s",
                block_index,
                origin.name,
            )
            continue
        relative_path = path.relative_to(asset_dir.resolve()).as_posix()
        page_idx = block.get("page_idx")
        page_index = page_idx if isinstance(page_idx, int) else None
        caption = _text(
            block.get("image_caption") or block.get("table_caption") or block.get("caption")
        )
        assets.append(
            StructuredVisualAsset(
                asset_id=_asset_id(
                    parsed,
                    origin=origin,
                    block_index=block_index,
                    resource_type=resource_type,
                    relative_path=relative_path,
                ),
                path=path,
                origin=origin,
                resource_type=resource_type,
                block_index=block_index,
                page_index=page_index,
                bbox=_bbox(block.get("bbox")),
                caption=caption,
                text=_text(block.get("table_body") or block.get("text") or block.get("content")),
                source_hash=parsed.source_hash,
                parser_signature=parsed.parser_signature,
            )
        )
    return assets


__all__ = ["StructuredVisualAsset", "build_structured_visual_assets"]
