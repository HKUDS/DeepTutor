"""Verified, parser-independent source images owned by a knowledge base.

The manifest is deliberately outside any vector index.  Retrieval engines may
index ``asset_id`` as metadata, but only this store resolves it to image bytes.
The caller must first resolve the KB through the normal access guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import warnings

from deeptutor.services.parsing.types import ParsedDocument

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_MODEL_IMAGES = 2
MAX_IMAGE_PIXELS = 30_000_000
logger = logging.getLogger(__name__)
_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        return None
    # Check that the bytes actually decode as an image, rather than trusting
    # an extension or a short magic prefix supplied by a parser.
    try:
        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    return None
                image.verify()
    except Exception:  # malformed or oversized images must not abort document indexing
        return None
    return mime


def _image_bytes(path: Path) -> tuple[bytes, str] | None:
    if path.is_symlink() or not path.is_file():
        return None
    size = path.stat().st_size
    if not 0 < size <= MAX_IMAGE_BYTES:
        return None
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        return None
    mime = _image_mime(data)
    return (data, mime) if mime is not None else None


def source_key_for(kb_dir: Path, source: Path) -> str:
    try:
        return source.resolve().relative_to((kb_dir / "raw").resolve()).as_posix()
    except ValueError:
        # Direct SDK callers can index paths outside raw/. Never persist the
        # host path in an asset manifest or expose it through citations.
        return source.name


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _managed_source(kb_dir: Path, source: Path) -> bool:
    return source.resolve().is_relative_to((kb_dir / "raw").resolve())


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(filter(None, (_text(item) for item in value))).strip()
    return ""


def _block_details(
    blocks: list[dict[str, Any]] | None, asset: Path
) -> tuple[str, str, int | None, int | None, list[float] | None, str]:
    if not blocks:
        return "", "", None, None, None, ""
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        raw = str(block.get("img_path") or block.get("path") or "")
        if not raw or Path(raw).resolve() != asset.resolve():
            continue
        caption = _text(
            block.get("caption")
            or block.get("image_caption")
            or block.get("chart_caption")
            or block.get("table_caption")
            or block.get("captions")
        )
        context = _text(block.get("text") or block.get("content"))
        if not context:
            neighbors = blocks[max(0, index - 1) : index] + blocks[index + 1 : index + 2]
            context = " ".join(
                _text(item.get("text") or item.get("content"))
                for item in neighbors
                if isinstance(item, dict)
            ).strip()
        has_page_index = block.get("page_idx") is not None
        page_raw = block.get("page_idx") if has_page_index else block.get("page")
        try:
            page_value = int(page_raw) if page_raw is not None else None
        except (ValueError, TypeError):
            page_value = None
        page_index = page_value if has_page_index else None
        page_number = (
            (page_value + 1 if has_page_index else page_value) if page_value is not None else None
        )
        raw_bbox = block.get("bbox")
        try:
            bbox = (
                [float(value) for value in raw_bbox[:4]]
                if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4
                else None
            )
        except (ValueError, TypeError):
            bbox = None
        return caption[:500], context[:500], page_index, page_number, bbox, f"blocks.json#/{index}"
    return "", "", None, None, None, ""


def _markdown_details(markdown: str, asset: Path) -> tuple[str, str, str]:
    for match in _MARKDOWN_IMAGE_RE.finditer(markdown):
        if Path(match.group(2).split("?", 1)[0]).name != asset.name:
            continue
        excerpt = markdown[max(0, match.start() - 250) : min(len(markdown), match.end() + 250)]
        excerpt = _MARKDOWN_IMAGE_RE.sub(" ", excerpt)
        return (
            match.group(1).strip()[:500],
            " ".join(excerpt.split())[:500],
            f"markdown:{match.start()}",
        )
    return "", "", ""


@dataclass(frozen=True)
class VisualAssetCandidate:
    path: Path
    record: dict[str, Any]


def collect_visual_assets(
    parsed: ParsedDocument, source: Path, kb_dir: Path
) -> list[VisualAssetCandidate]:
    """Normalize extracted PDF/EPUB images with provenance and byte identity."""
    asset_dir = parsed.asset_dir
    if asset_dir is None or asset_dir.is_symlink() or not asset_dir.is_dir():
        return []
    source_key = source_key_for(kb_dir, source)
    source_hash = _sha256_file(source)
    candidates: list[VisualAssetCandidate] = []
    for path in sorted(asset_dir.iterdir()):
        try:
            loaded = _image_bytes(path)
        except OSError:
            logger.warning(
                "Unable to read parser asset %s; coverage report will record it", path.name
            )
            continue
        if loaded is None:
            continue
        image, mime = loaded
        image_hash = sha256(image).hexdigest()
        caption, context, page_index, page_number, bbox, locator = _block_details(
            parsed.blocks, path
        )
        md_caption, md_context, md_locator = _markdown_details(parsed.markdown, path)
        caption = caption or md_caption
        context = context or md_context
        locator = locator or md_locator or f"asset:{path.name}"
        asset_id = sha256(
            f"{source_key}\0{source_hash}\0{parsed.parser_signature}\0{locator}\0{image_hash}".encode()
        ).hexdigest()
        record = {
            "asset_id": asset_id,
            "source_document_id": source_hash,
            "source_path": source_key,
            "managed_source": _managed_source(kb_dir, source),
            "parser_engine": parsed.engine,
            "parser_signature": parsed.parser_signature,
            "source_hash": parsed.source_hash,
            "source_locator": locator,
            "page_index": page_index,
            "page_number": page_number,
            "bbox": bbox,
            "caption": caption,
            "context": context,
            "image_sha256": image_hash,
            "mime_type": mime,
            "size": len(image),
        }
        from deeptutor.services.rag.source_visuals import figure_labels

        record["figure_labels"] = figure_labels(caption)
        matching = [
            block
            for block in (parsed.blocks or [])
            if isinstance(block, dict)
            and str(block.get("img_path") or block.get("path") or "")
            and Path(str(block.get("img_path") or block.get("path"))).resolve() == path.resolve()
        ]
        if matching:
            block = matching[0]
            record.update(
                {
                    "kind": str(block.get("type") or "image"),
                    "section": _text(block.get("section") or block.get("section_title")),
                    "group_id": str(block.get("group_id") or block.get("figure_id") or ""),
                    "table_html": _text(block.get("table_body") or block.get("table_html")),
                    "notes": _text(block.get("notes") or block.get("table_footnote")),
                }
            )
        candidates.append(VisualAssetCandidate(path=path, record=record))
    return candidates


class VisualAssetStore:
    """KB-scoped immutable image files plus an atomically replaced manifest."""

    def __init__(self, kb_dir: Path):
        self.kb_dir = Path(kb_dir)
        self.root = self.kb_dir / "visual_assets"
        self.manifest_path = self.root / "manifest.json"

    def records(self) -> dict[str, dict[str, Any]]:
        if self.root.is_symlink() or not self.root.resolve().is_relative_to(self.kb_dir.resolve()):
            return {}
        try:
            return self._read_manifest()
        except OSError as exc:
            logger.warning("Cannot read source figures for KB '%s': %s", self.kb_dir.name, exc)
            return {}

    def _read_manifest(self) -> dict[str, dict[str, Any]]:
        # #1802: the corpus grows independently of the per-image request budget.
        # Never interpret a large or corrupt manifest as an empty store on a write.
        try:
            if self.root.is_symlink() or not self.root.resolve().is_relative_to(
                self.kb_dir.resolve()
            ):
                raise OSError("Visual asset directory escapes knowledge base")
            if self.manifest_path.is_symlink():
                raise OSError("Visual asset manifest must not be a symbolic link")
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise OSError(f"Cannot read visual asset manifest {self.manifest_path}: {exc}") from exc
        records = payload.get("assets") if isinstance(payload, dict) else None
        if not isinstance(records, dict) or any(not isinstance(v, dict) for v in records.values()):
            raise OSError(f"Invalid visual asset manifest {self.manifest_path}")
        return records

    def publish(
        self,
        candidates: list[VisualAssetCandidate],
        *,
        replace: bool = False,
        source_paths: set[str] | None = None,
        prune_missing: bool = False,
    ) -> None:
        if self.root.is_symlink() or not self.root.resolve().is_relative_to(self.kb_dir.resolve()):
            raise OSError("Visual asset directory escapes knowledge base")
        self.root.mkdir(parents=True, exist_ok=True)
        prior = self._read_manifest()
        incoming = {item.record["asset_id"]: item.record for item in candidates}
        if replace:
            remaining: dict[str, dict[str, Any]] = {}
        else:
            # Keep older index versions' asset IDs reachable when the same
            # source is re-parsed with a new parser or embedding signature.
            # Explicit raw-file deletion removes all IDs for that source.
            replaced_sources = source_paths or set()
            remaining = {
                key: value
                for key, value in prior.items()
                if value.get("source_path") not in replaced_sources
            }
            if prune_missing:
                remaining = {
                    key: value
                    for key, value in remaining.items()
                    if not value.get("managed_source")
                    or self._source_exists(value.get("source_path"))
                }
        updated = {**remaining, **incoming}
        manifest = json.dumps(
            {"version": 1, "assets": updated}, ensure_ascii=False, sort_keys=True
        ).encode()
        for candidate in candidates:
            record = candidate.record
            loaded = _image_bytes(candidate.path)
            if (
                loaded is None
                or sha256(loaded[0]).hexdigest() != record["image_sha256"]
                or loaded[1] != record["mime_type"]
            ):
                raise OSError(f"Source image changed during indexing: {candidate.path.name}")
            target = self._path(record["asset_id"], record["mime_type"])
            existing = _image_bytes(target)
            if existing is None or sha256(existing[0]).hexdigest() != record["image_sha256"]:
                self._atomic_write(target, loaded[0])
        self._atomic_write(self.manifest_path, manifest)
        for old_id, old_record in prior.items():
            if old_id not in updated:
                self._path(old_id, str(old_record.get("mime_type"))).unlink(missing_ok=True)

    def read(self, asset_id: str) -> tuple[dict[str, Any], bytes] | None:
        if not _ID_RE.fullmatch(asset_id):
            return None
        record = self.records().get(asset_id)
        if not isinstance(record, dict) or record.get("asset_id") != asset_id:
            return None
        mime = record.get("mime_type")
        if mime not in _MIME_EXT:
            return None
        path = self._path(asset_id, mime)
        loaded = _image_bytes(path)
        if loaded is None or loaded[1] != mime:
            return None
        data = loaded[0]
        if len(data) != record.get("size") or sha256(data).hexdigest() != record.get(
            "image_sha256"
        ):
            return None
        return record, data

    def remove_source(self, source_relative_path: str) -> None:
        prior = self._read_manifest()
        updated = {
            key: value
            for key, value in prior.items()
            if value.get("source_path") != source_relative_path
        }
        if len(updated) == len(prior):
            return
        self._atomic_write(
            self.manifest_path,
            json.dumps(
                {"version": 1, "assets": updated}, ensure_ascii=False, sort_keys=True
            ).encode(),
        )
        for old_id, old_record in prior.items():
            if old_id not in updated:
                self._path(old_id, str(old_record.get("mime_type"))).unlink(missing_ok=True)

    def move_source(self, old_relative_path: str, new_relative_path: str) -> None:
        prior = self._read_manifest()
        updated = {}
        changed = False
        for key, value in prior.items():
            source = value.get("source_path")
            if source == old_relative_path or (
                isinstance(source, str) and source.startswith(old_relative_path + "/")
            ):
                value = {
                    **value,
                    "source_path": new_relative_path + source[len(old_relative_path) :],
                }
                changed = True
            updated[key] = value
        if changed:
            self._atomic_write(
                self.manifest_path,
                json.dumps(
                    {"version": 1, "assets": updated}, ensure_ascii=False, sort_keys=True
                ).encode(),
            )

    def _path(self, asset_id: str, mime: str) -> Path:
        if not _ID_RE.fullmatch(asset_id) or mime not in _MIME_EXT:
            raise ValueError("Invalid visual asset record")
        return self.root / (asset_id + _MIME_EXT[mime])

    def _source_exists(self, relative_path: Any) -> bool:
        if not isinstance(relative_path, str):
            return False
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            return False
        raw = (self.kb_dir / "raw").resolve()
        source = (raw / relative).resolve()
        return source.is_relative_to(raw) and source.is_file()

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".visual-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            Path(temp_name).unlink(missing_ok=True)
