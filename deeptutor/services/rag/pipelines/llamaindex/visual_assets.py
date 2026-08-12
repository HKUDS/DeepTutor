"""Parser-block-aware visual asset mapping for LlamaIndex ingestion."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

import pymupdf

_VISUAL_TYPES = {"image", "table"}
_EXCLUDED_CONTEXT_TYPES = {"header", "footer", "page_number"}
_LAYOUT_AREA_LIMIT = 0.002
_FINGERPRINT_SIZE = 16
_FIGURE_ID_RE = re.compile(
    r"(?:(?:图|表)\s*|(?:figure|fig\.?|table)\s*)([A-Za-z]?\d+(?:[.\-]\d+)*(?:\s*\([A-Za-z0-9]+\))?)",
    re.IGNORECASE,
)
_EXPLICIT_VISUAL_REFERENCE_RE = re.compile(
    r"(?:如图|见图|下图|上图|图中|示意图|figure|fig\.?|table)", re.IGNORECASE
)
_EXERCISE_REFERENCE_RE = re.compile(r"(?:第\s*\d+\s*题|exercise\s+\d+)", re.IGNORECASE)
_BOILERPLATE_RE = re.compile(r"^(?:人民教育出版社|publisher)$", re.IGNORECASE)
_CHAPTER_HEADING_RE = re.compile(r"^(?:第\s*[^\s]+\s*章\b|chapter\b)", re.IGNORECASE)


@dataclass(frozen=True)
class VisualComponent:
    path: Path
    block_index: int
    page_idx: int
    bbox: tuple[float, float, float, float]
    sha256: str


@dataclass(frozen=True)
class VisualAsset:
    asset_id: str
    resource_type: str
    index_role: str
    grouping_state: str
    origin: Path
    source_hash: str
    parser_signature: str
    components: tuple[VisualComponent, ...]
    figure_id: str
    caption: str
    footnote: str
    chapter: str
    section: str
    nearby_text_before: str
    nearby_text_after: str
    pdf_page_index: int
    pdf_page_number: int
    printed_page_number: str
    logical_bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class _Candidate:
    component: VisualComponent
    resource_type: str
    caption: str
    footnote: str
    figure_id: str
    chapter: str
    section: str
    nearby_text_before: str
    nearby_text_after: str
    printed_page_number: str
    fingerprint: str | None
    placement_signature: tuple[int, int, int, int]
    area_ratio: float
    has_semantic_anchor: bool


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return "\n".join(part for item in value if (part := _text(item)))
    return ""


def _caption(block: dict[str, Any], resource_type: str) -> str:
    return _text(
        block.get("table_caption") if resource_type == "table" else block.get("image_caption")
    )


def _footnote(block: dict[str, Any], resource_type: str) -> str:
    return _text(
        block.get("table_footnote") if resource_type == "table" else block.get("image_footnote")
    )


def _figure_id(*values: str) -> str:
    for value in values:
        match = _FIGURE_ID_RE.search(value)
        if not match:
            continue
        prefix_match = re.match(r"(图|表|figure|fig\.?|table)\s*", match.group(0), re.IGNORECASE)
        prefix = prefix_match.group(1) if prefix_match else ""
        if prefix.lower().startswith("fig"):
            prefix = "Figure"
        if prefix.lower() == "table":
            prefix = "Table"
        separator = "" if prefix in {"图", "表"} else " "
        return f"{prefix}{separator}{match.group(1)}"
    return ""


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        return None
    try:
        result = tuple(float(part) for part in value)
    except (TypeError, ValueError):
        return None
    if result[2] <= result[0] or result[3] <= result[1]:
        return None
    return result[0], result[1], result[2], result[3]


def _resolve_component_path(img_path: Any, asset_dir: Path) -> Path | None:
    if not isinstance(img_path, str) or not img_path.strip():
        return None
    raw = Path(img_path)
    if ".." in raw.parts:
        return None
    if raw.is_absolute():
        candidates = [raw]
    elif raw.parts and raw.parts[0] == asset_dir.name:
        candidates = [asset_dir.parent / raw]
    else:
        candidates = [asset_dir / raw]
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and resolved.is_relative_to(asset_dir):
            return resolved
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_grayscale_fingerprint(path: Path) -> str | None:
    """Return a contrast-normalized average hash derived through PyMuPDF."""
    try:
        pixmap = pymupdf.Pixmap(str(path))
        if pixmap.alpha:
            pixmap = pymupdf.Pixmap(pixmap, 0)
        if pixmap.n != 1:
            pixmap = pymupdf.Pixmap(pymupdf.csGRAY, pixmap)
        values: list[int] = []
        for row in range(_FINGERPRINT_SIZE):
            y = min(
                pixmap.height - 1,
                int((row + 0.5) * pixmap.height / _FINGERPRINT_SIZE),
            )
            for column in range(_FINGERPRINT_SIZE):
                x = min(
                    pixmap.width - 1,
                    int((column + 0.5) * pixmap.width / _FINGERPRINT_SIZE),
                )
                values.append(pixmap.samples[y * pixmap.stride + x * pixmap.n])
        threshold = sum(values) / len(values)
        packed = bytearray()
        for offset in range(0, len(values), 8):
            byte = 0
            for bit, value in enumerate(values[offset : offset + 8]):
                if value < threshold:
                    byte |= 1 << bit
            packed.append(byte)
        return packed.hex()
    except Exception:
        return None


def _context_text(block: dict[str, Any]) -> str:
    if block.get("type") in _EXCLUDED_CONTEXT_TYPES:
        return ""
    if block.get("type") not in {"text", "equation"}:
        return ""
    text = _text(block.get("text") or block.get("content"))
    if not text or _BOILERPLATE_RE.fullmatch(text):
        return ""
    return text


def _nearby_context(blocks: list[dict[str, Any]], index: int, page_idx: int) -> tuple[str, str]:
    before = ""
    after = ""
    for candidate in reversed(blocks[:index]):
        if candidate.get("page_idx") != page_idx:
            continue
        if candidate.get("text_level"):
            continue
        before = _context_text(candidate)
        if before:
            break
    for candidate in blocks[index + 1 :]:
        if candidate.get("page_idx") != page_idx:
            continue
        if candidate.get("text_level"):
            continue
        after = _context_text(candidate)
        if after:
            break
    return before, after


def _hierarchy_at(blocks: list[dict[str, Any]], index: int) -> tuple[str, str]:
    chapter = ""
    section = ""
    for block in blocks[:index]:
        text = _text(block.get("text") or block.get("content"))
        try:
            level = int(block.get("text_level") or 0)
        except (TypeError, ValueError):
            level = 0
        if not text or not level:
            continue
        if level == 1 or _CHAPTER_HEADING_RE.search(text) or not chapter:
            chapter = text
            section = ""
        else:
            section = text
    return chapter, section


def _printed_page_number(blocks: list[dict[str, Any]], page_idx: int) -> str:
    for block in blocks:
        if block.get("page_idx") == page_idx and block.get("type") == "page_number":
            return _text(block.get("text") or block.get("content"))
    return ""


def _placement_signature(bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    # MinerU content-list coordinates are normalized to a 1000 x 1000 page.
    edge_role = 0 if x1 <= 200 else 2 if x2 >= 800 else 1
    return (
        edge_role,
        round(x1 / 50),
        round((x2 - x1) / 20),
        round((y2 - y1) / 20),
    )


def _has_semantic_anchor(
    resource_type: str,
    caption: str,
    footnote: str,
    figure_id: str,
    before: str,
    after: str,
) -> bool:
    if resource_type == "table" or caption or footnote or figure_id:
        return True
    context = f"{before}\n{after}"
    return bool(
        _EXPLICIT_VISUAL_REFERENCE_RE.search(context) or _EXERCISE_REFERENCE_RE.search(context)
    )


def _candidate_from_block(
    parsed: Any,
    origin: Path,
    asset_dir: Path,
    blocks: list[dict[str, Any]],
    index: int,
    block: dict[str, Any],
) -> _Candidate | None:
    resource_type = str(block.get("type") or "")
    if resource_type not in _VISUAL_TYPES:
        return None
    try:
        raw_page_idx = block.get("page_idx")
        if raw_page_idx is None:
            return None
        page_idx = int(raw_page_idx)
    except (TypeError, ValueError):
        return None
    bbox = _bbox(block.get("bbox"))
    path = _resolve_component_path(block.get("img_path"), asset_dir)
    if bbox is None or path is None or page_idx < 0:
        return None
    caption = _caption(block, resource_type)
    footnote = _footnote(block, resource_type)
    before, after = _nearby_context(blocks, index, page_idx)
    figure_id = _figure_id(caption, footnote, before, after)
    chapter, section = _hierarchy_at(blocks, index)
    component = VisualComponent(
        path=path,
        block_index=index,
        page_idx=page_idx,
        bbox=bbox,
        sha256=_sha256(path),
    )
    x1, y1, x2, y2 = bbox
    area_ratio = ((x2 - x1) * (y2 - y1)) / 1_000_000
    return _Candidate(
        component=component,
        resource_type=resource_type,
        caption=caption,
        footnote=footnote,
        figure_id=figure_id,
        chapter=chapter,
        section=section,
        nearby_text_before=before,
        nearby_text_after=after,
        printed_page_number=_printed_page_number(blocks, page_idx),
        fingerprint=_normalized_grayscale_fingerprint(path),
        placement_signature=_placement_signature(bbox),
        area_ratio=area_ratio,
        has_semantic_anchor=_has_semantic_anchor(
            resource_type, caption, footnote, figure_id, before, after
        ),
    )


def _aligned_compact(candidates: Sequence[_Candidate]) -> bool:
    boxes = [candidate.component.bbox for candidate in candidates]
    widths = [box[2] - box[0] for box in boxes]
    heights = [box[3] - box[1] for box in boxes]
    horizontal = max((box[1] + box[3]) / 2 for box in boxes) - min(
        (box[1] + box[3]) / 2 for box in boxes
    ) <= max(heights)
    vertical = max((box[0] + box[2]) / 2 for box in boxes) - min(
        (box[0] + box[2]) / 2 for box in boxes
    ) <= max(widths)
    if horizontal:
        ordered = sorted(boxes, key=lambda box: box[0])
        return all(
            right[0] - left[2] <= max(max(widths), max(heights))
            for left, right in zip(ordered, ordered[1:])
        )
    if vertical:
        ordered = sorted(boxes, key=lambda box: box[1])
        return all(
            lower[1] - upper[3] <= max(max(widths), max(heights))
            for upper, lower in zip(ordered, ordered[1:])
        )
    return False


def _figure_id_root(figure_id: str) -> str:
    return re.sub(r"\s*\([A-Za-z0-9]+\)$", "", figure_id).strip()


def _group_candidates(candidates: list[_Candidate]) -> list[list[_Candidate]]:
    grouped: list[list[_Candidate]] = []
    index = 0
    while index < len(candidates):
        run = [candidates[index]]
        next_index = index + 1
        while next_index < len(candidates):
            previous = run[-1]
            current = candidates[next_index]
            if current.component.page_idx != previous.component.page_idx:
                break
            if current.component.block_index != previous.component.block_index + 1:
                break
            run.append(current)
            next_index += 1
        figure_ids = [candidate.figure_id for candidate in run if candidate.figure_id]
        figure_roots = {_figure_id_root(figure_id) for figure_id in figure_ids}
        explicit_group_id = len(figure_ids) == 1 or (
            len(figure_ids) == len(run) and len(figure_roots) == 1
        )
        if len(run) > 1 and explicit_group_id and _aligned_compact(run):
            grouped.append(run)
        else:
            grouped.extend([[candidate] for candidate in run])
        index = next_index
    return grouped


def _layout_roles(candidates: Iterable[_Candidate]) -> set[int]:
    candidates = list(candidates)
    marker_indices: set[int] = set()
    for index, candidate in enumerate(candidates):
        if (
            candidate.has_semantic_anchor
            or candidate.area_ratio > _LAYOUT_AREA_LIMIT
            or candidate.fingerprint is None
        ):
            continue
        for other_index, other in enumerate(candidates):
            if index == other_index or candidate.component.page_idx == other.component.page_idx:
                continue
            if other.fingerprint is None:
                continue
            fingerprint_distance = (
                int(candidate.fingerprint, 16) ^ int(other.fingerprint, 16)
            ).bit_count()
            if fingerprint_distance > 16:
                continue
            if candidate.placement_signature != other.placement_signature:
                continue
            marker_indices.add(index)
            break
    return marker_indices


def _logical_bbox(components: Sequence[VisualComponent]) -> tuple[float, float, float, float]:
    return (
        min(component.bbox[0] for component in components),
        min(component.bbox[1] for component in components),
        max(component.bbox[2] for component in components),
        max(component.bbox[3] for component in components),
    )


def _asset_id(parsed: Any, candidates: Sequence[_Candidate]) -> str:
    payload = {
        "source_hash": str(getattr(parsed, "source_hash", "") or ""),
        "parser_signature": str(getattr(parsed, "parser_signature", "") or ""),
        "page_idx": candidates[0].component.page_idx,
        "components": [
            {
                "block_index": candidate.component.block_index,
                "sha256": candidate.component.sha256,
                "bbox": candidate.component.bbox,
            }
            for candidate in candidates
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_visual_assets(parsed: Any, *, origin: Path) -> list[VisualAsset]:
    """Map formally referenced parser blocks to conservative logical visual assets."""
    if getattr(parsed, "blocks", None) is None or getattr(parsed, "asset_dir", None) is None:
        return []
    try:
        asset_dir = Path(parsed.asset_dir).resolve(strict=True)
    except OSError:
        return []
    if not asset_dir.is_dir():
        return []
    blocks = [block for block in parsed.blocks if isinstance(block, dict)]
    candidates = [
        candidate
        for index, block in enumerate(blocks)
        if (
            candidate := _candidate_from_block(
                parsed, Path(origin), asset_dir, blocks, index, block
            )
        )
        is not None
    ]
    layout_marker_indices = _layout_roles(candidates)
    candidate_positions = {id(candidate): index for index, candidate in enumerate(candidates)}
    assets: list[VisualAsset] = []
    for group in _group_candidates(candidates):
        first = group[0]
        components = tuple(candidate.component for candidate in group)
        figure_ids = [candidate.figure_id for candidate in group if candidate.figure_id]
        captions = [candidate.caption for candidate in group if candidate.caption]
        footnotes = [candidate.footnote for candidate in group if candidate.footnote]
        is_layout_marker = all(
            candidate_positions[id(candidate)] in layout_marker_indices for candidate in group
        )
        assets.append(
            VisualAsset(
                asset_id=_asset_id(parsed, group),
                resource_type=(
                    first.resource_type
                    if all(item.resource_type == first.resource_type for item in group)
                    else "mixed"
                ),
                index_role=(
                    "layout_marker"
                    if is_layout_marker
                    else "semantic"
                    if any(candidate.has_semantic_anchor for candidate in group)
                    else "uncertain"
                ),
                grouping_state="logical_group" if len(group) > 1 else "separate_assets",
                origin=Path(origin),
                source_hash=str(getattr(parsed, "source_hash", "") or ""),
                parser_signature=str(getattr(parsed, "parser_signature", "") or ""),
                components=components,
                figure_id=_figure_id_root(figure_ids[0]) if figure_ids else "",
                caption="\n".join(dict.fromkeys(captions)),
                footnote="\n".join(dict.fromkeys(footnotes)),
                chapter=first.chapter,
                section=first.section,
                nearby_text_before=first.nearby_text_before,
                nearby_text_after=group[-1].nearby_text_after,
                pdf_page_index=first.component.page_idx,
                pdf_page_number=first.component.page_idx + 1,
                printed_page_number=first.printed_page_number,
                logical_bbox=_logical_bbox(components),
            )
        )
    return assets


__all__ = ["VisualAsset", "VisualComponent", "build_visual_assets"]
