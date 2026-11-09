"""Map a Docling document onto the shared ``content_list`` block IR.

The canonical structured-parse IR is MinerU's legacy ``content_list.json``
shape (see ``deeptutor/services/parsing/types.py``): the LightRAG block
pipeline, the parse cache, and the question extractor all consume it. A
``DoclingDocument`` is a typed item tree in body reading order, so this
module walks the body layer and emits MinerU-shaped blocks:

* ``text`` / ``paragraph`` / other text labels
  → ``{"type": "text", "text": …}``
* ``title`` / ``section_header``
  → ``{"type": "text", "text": …, "text_level": n}`` (tree depth as level)
* ``formula`` → ``{"type": "equation", "text": <LaTeX>}`` — only when Docling
  actually produced the LaTeX (formula enrichment); LaTeX is never invented
* ``table`` → ``{"type": "table", "table_body": <html>, …}`` via
  ``TableItem.export_to_html(doc=document)`` so merged cells survive
  serialization (docling-core returns "" for the doc-less deprecated call)
* ``picture`` → ``{"type": "image", "img_path": "images/…", …}`` with the
  crop saved beside the content list (requires ``generate_picture_images``);
  pictures without a crop are skipped rather than emitted unresolvable
* ``list_item`` runs → ``{"type": "list", "list_items": […]}`` — one block
  per page (or per run of items with unknown provenance), with a bbox
  covering every grouped item
* ``code`` → ``{"type": "code", "code_body": …}``

Page chrome (``page_header`` / ``page_footer`` / ``page_number``) never
becomes a block: Docling's reading-order stage already moves those items
into the furniture layer — which the body walk skips — and the labels are
filtered defensively as well.

Provenance comes from Docling's ``prov`` records: a list of 1-based
``page_no`` + ``bbox`` entries per item. ``page_idx`` is the first record's
page converted to the IR's 0-based indexing, and each emitted ``bbox``
(``[l, t, r, b]`` floats, preserving the records' coordinate origin) covers
the records on that page. A single non-list record and missing/empty
``prov`` are tolerated.

Everything is duck-typed, so this module never imports Docling and the
mapping is unit-testable with fakes. Unknown labels degrade to plain
``text`` blocks when they carry text and are dropped otherwise, so the
emitted list is already sanitized for the LightRAG block policy.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import shutil
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

# Bumped when the block mapping itself changes shape, so parse caches built
# by an older mapping are invalidated via the parser signature.
# v2: read Docling's list-shaped provenance (``page_no`` + per-record
# bboxes) and split list groups per page with union bboxes — v1 caches carry
# wrong page_idx/bbox coordinates.
# v3: pass ``doc`` to the table exporters so tables carry real HTML with
# merged-cell spans (v2 caches hold flattened markdown), and split list
# groups on known/unknown page transitions (v2 caches hold merged groups
# with cross-page bboxes).
CONTENT_LIST_SCHEMA_VERSION = 3

CONTENT_LIST_SUFFIX = "_content_list.json"
IMAGES_DIRNAME = "images"

# (l, r, y_min, y_max, bottom_origin): y bounds normalized to min/max so
# unions are orientation-independent, with the input origin kept for output.
_Bounds = tuple[float, float, float, float, bool]

# Docling furniture labels that must never reach the block IR. Same strings
# MinerU's LightRAG block policy filters (see block_policy.py).
_CHROME_LABELS = frozenset({"page_header", "page_footer", "page_number"})
_HEADING_LABELS = frozenset({"title", "section_header"})
_SUPPORTED_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp"})
_SAFE_PREFIX = re.compile(r"[^A-Za-z0-9_-]+")
_PREFIX_MAX_LENGTH = 40


def _label_value(item: Any) -> str:
    label = getattr(item, "label", None)
    value = getattr(label, "value", label)
    return str(value or "").strip().lower()


def _item_text(item: Any) -> str:
    value = getattr(item, "text", None)
    return value.strip() if isinstance(value, str) else ""


def _record_page_no(record: Any) -> Optional[int]:
    """1-based page number of a provenance record (legacy ``page`` kept)."""
    for source in ("page_no", "page"):
        value = getattr(record, source, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _box_bounds(box: Any) -> Optional[_Bounds]:
    """``(l, r, y_min, y_max, bottom_origin)`` from a duck-typed BoundingBox.

    The y pair is min/max-normalized so unions are orientation-independent;
    ``bottom_origin`` remembers the input orientation (BOTTOMLEFT boxes carry
    ``t > b``) so the emitted ``[l, t, r, b]`` keeps it.
    """
    try:
        left, top, right, bottom = (float(getattr(box, name)) for name in ("l", "t", "r", "b"))
    except (AttributeError, TypeError, ValueError):
        return None
    origin = getattr(box, "coord_origin", None)
    value = getattr(origin, "value", origin)
    is_bottom = isinstance(value, str) and value.strip().upper() == "BOTTOMLEFT"
    return left, right, min(top, bottom), max(top, bottom), is_bottom


def _union_bounds(bounds: list[_Bounds]) -> _Bounds:
    """Smallest bounds covering every input (orientation from the first)."""
    return (
        min(b[0] for b in bounds),
        max(b[1] for b in bounds),
        min(b[2] for b in bounds),
        max(b[3] for b in bounds),
        bounds[0][4],
    )


def _bounds_bbox(bounds: _Bounds) -> list[float]:
    left, right, y_min, y_max, is_bottom = bounds
    return [left, y_max if is_bottom else y_min, right, y_min if is_bottom else y_max]


def _provenance(item: Any) -> tuple[Optional[int], Optional[_Bounds]]:
    """``(page_idx, bounds)`` from a Docling ``prov``, or ``(None, None)``.

    Real Docling items carry ``prov`` as a list of provenance records, each
    with a 1-based ``page_no`` and a ``bbox``. The page comes from the first
    record (converted to the IR's 0-based ``page_idx``), and the bbox covers
    every record on that page, so an item continued onto another page keeps
    only its first page's geometry. A single non-list record is tolerated,
    and a missing/empty ``prov`` yields ``(None, None)``.
    """
    prov = getattr(item, "prov", None)
    if not prov:
        return None, None
    records = prov if isinstance(prov, (list, tuple)) else [prov]
    page_no = _record_page_no(records[0])
    page_idx = page_no - 1 if page_no is not None else None
    on_page = [record for record in records if _record_page_no(record) == page_no]
    bounds = [
        parsed
        for parsed in (_box_bounds(getattr(record, "bbox", None)) for record in on_page)
        if parsed is not None
    ]
    return page_idx, _union_bounds(bounds) if bounds else None


def _base_fields(page_idx: Optional[int], bbox: Optional[list[float]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if page_idx is not None:
        fields["page_idx"] = page_idx
    if bbox is not None:
        fields["bbox"] = bbox
    return fields


def _caption_texts(item: Any, document: Any) -> list[str]:
    """Best-effort caption strings from a Docling item's caption refs."""
    captions: list[str] = []
    for ref in getattr(item, "captions", None) or []:
        text = getattr(ref, "text", None)
        if not isinstance(text, str) or not text.strip():
            resolve = getattr(ref, "resolve", None)
            if callable(resolve):
                try:
                    text = getattr(resolve(document), "text", None)
                except Exception:  # noqa: BLE001 - captions are optional
                    text = None
        if isinstance(text, str) and text.strip():
            captions.append(text.strip())
    return captions


def _export_with_doc(item: Any, attr: str, document: Any) -> str:
    """Call ``item.<attr>(doc=document)``, tolerating doc-less exporters.

    docling-core's table exporters need the owning document: without
    ``doc``, ``export_to_html()`` is deprecated and returns ``""`` (observed
    on 2.106), and ``export_to_markdown()`` falls back to a flattened
    tabulate export. An exporter without the parameter (older shapes,
    fakes) is retried doc-less; any failure yields ``""`` so callers can
    degrade instead of losing the parse.
    """
    export = getattr(item, attr, None)
    if not callable(export):
        return ""
    try:
        return str(export(doc=document) or "").strip()
    except TypeError:
        try:
            return str(export() or "").strip()
        except Exception:  # noqa: BLE001 - a broken export must not kill the parse
            return ""
    except Exception:  # noqa: BLE001 - a broken export must not kill the parse
        return ""


def _table_block(item: Any, document: Any, base: dict[str, Any]) -> Optional[dict[str, Any]]:
    """A table block carrying HTML so merged header cells survive.

    Both exporters are handed ``doc=document`` — without it docling-core's
    HTML export returns ``""`` and the markdown export flattens spans.
    Falls back to that flattened markdown as a plain text block — never
    drops the content — and returns ``None`` when nothing is extractable.
    """
    html = _export_with_doc(item, "export_to_html", document)
    if html:
        block: dict[str, Any] = {"type": "table", "table_body": html}
        data = getattr(item, "data", None)
        for source, target in (
            ("num_rows", "num_rows"),
            ("num_cols", "num_cols"),
        ):
            value = getattr(data, source, None)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                block[target] = value
        captions = _caption_texts(item, document)
        if captions:
            block["table_caption"] = captions
        block.update(base)
        return block
    markdown = _export_with_doc(item, "export_to_markdown", document)
    if markdown:
        return {"type": "text", "text": markdown, **base}
    return None


def _picture_extension(image: Any) -> str:
    fmt = str(getattr(image, "format", "") or "").strip().lower()
    if "/" in fmt:
        fmt = fmt.rsplit("/", 1)[-1]
    if fmt in _SUPPORTED_IMAGE_EXTENSIONS:
        return "jpg" if fmt == "jpeg" else fmt
    uri = getattr(image, "uri", None)
    if uri:
        suffix = Path(str(uri)).suffix.lower().lstrip(".")
        if suffix in _SUPPORTED_IMAGE_EXTENSIONS:
            return "jpg" if suffix == "jpeg" else suffix
    return "png"


def _save_picture_crop(image: Any, target: Path) -> bool:
    """Persist one picture crop: encode the PIL image or copy the artifact."""
    pil = getattr(image, "pil_image", None)
    if pil is not None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            pil.save(target)
            return True
        except Exception:  # noqa: BLE001 - one bad crop must not kill the parse
            logger.warning("Could not encode a Docling picture crop at %s", target)
            return False
    uri = getattr(image, "uri", None)
    if uri:
        source = Path(str(uri))
        try:
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                return True
        except OSError:
            logger.warning("Could not copy a Docling picture crop at %s", source)
    return False


def _safe_prefix(stem: str) -> str:
    prefix = _SAFE_PREFIX.sub("_", stem).strip("_")
    return prefix[:_PREFIX_MAX_LENGTH] or "img"


def _iterate_body(document: Any) -> Iterator[tuple[Any, int]]:
    """Yield ``(item, tree_level)`` in body reading order.

    ``DoclingDocument.iterate_items()`` walks the body tree only — headers,
    footers, and page numbers live in the separate furniture layer, so they
    never appear here.
    """
    for node, level in document.iterate_items():
        yield node, level


def build_content_list(
    document: Any,
    *,
    save_images_to: Optional[Path] = None,
    image_prefix: str = "img",
) -> list[dict[str, Any]]:
    """Map a Docling document to MinerU-shaped content_list blocks."""
    blocks: list[dict[str, Any]] = []
    prefix = _safe_prefix(image_prefix)
    pending_items: list[str] = []
    pending_page_idx: Optional[int] = None
    pending_bounds: list[_Bounds] = []
    picture_seq = 0

    def flush_list() -> None:
        nonlocal pending_items, pending_page_idx, pending_bounds
        if pending_items:
            block: dict[str, Any] = {"type": "list", "list_items": pending_items}
            if pending_page_idx is not None:
                block["page_idx"] = pending_page_idx
            if pending_bounds:
                # Cover every grouped item: min/max per axis, keeping the
                # orientation of the items' bboxes.
                block["bbox"] = _bounds_bbox(_union_bounds(pending_bounds))
            blocks.append(block)
        pending_items = []
        pending_page_idx = None
        pending_bounds = []

    for node, level in _iterate_body(document):
        label = _label_value(node)
        if not label or label in _CHROME_LABELS:
            continue
        page_idx, bounds = _provenance(node)
        base = _base_fields(page_idx, _bounds_bbox(bounds) if bounds is not None else None)

        if label == "list_item":
            text = _item_text(node)
            if not text:
                continue
            if pending_items and pending_page_idx != page_idx:
                # Consecutive list items never merge across a page break or
                # across a known/unknown provenance transition: one block
                # per page (or per unknown run), each with its own
                # coordinates. Comparing against ``pending_page_idx`` even
                # when it is ``None`` is what splits a group that started
                # with an unknown-provenance item.
                flush_list()
            if not pending_items:
                pending_page_idx = page_idx
            pending_items.append(text)
            if bounds is not None:
                pending_bounds.append(bounds)
            continue
        flush_list()

        if label in _HEADING_LABELS:
            text = _item_text(node)
            if text:
                heading_level = max(min(int(level), 6), 1) if label == "section_header" else 1
                blocks.append({"type": "text", "text": text, "text_level": heading_level, **base})
            continue

        if label == "formula":
            latex = _item_text(node)
            if latex:
                blocks.append({"type": "equation", "text": latex, **base})
            continue

        if label == "code":
            text = _item_text(node)
            if text:
                blocks.append({"type": "code", "code_body": text, **base})
            continue

        if label == "table":
            block = _table_block(node, document, base)
            if block is not None:
                blocks.append(block)
            continue

        if label == "picture":
            image = getattr(node, "image", None)
            if image is None or save_images_to is None:
                continue
            name = f"{prefix}_{picture_seq:03d}.{_picture_extension(image)}"
            if _save_picture_crop(image, save_images_to / name):
                picture_seq += 1
                block: dict[str, Any] = {"type": "image", "img_path": f"{IMAGES_DIRNAME}/{name}"}
                captions = _caption_texts(node, document)
                if captions:
                    block["image_caption"] = captions
                block.update(base)
                blocks.append(block)
            continue

        text = _item_text(node)
        if text:
            blocks.append({"type": "text", "text": text, **base})

    flush_list()
    return blocks


def write_content_list(
    document: Any, workdir: Path, *, stem: str
) -> Optional[list[dict[str, Any]]]:
    """Build blocks, save picture crops, and write ``<stem>_content_list.json``.

    Returns the blocks, or ``None`` when the document yielded no structure
    (the caller keeps its markdown-only fallback). The JSON and the
    ``images/`` dir mirror a MinerU bundle, so ``cache.load_ir`` and the
    LightRAG ingress consume them unchanged.
    """
    blocks = build_content_list(
        document, save_images_to=workdir / IMAGES_DIRNAME, image_prefix=stem
    )
    if not blocks:
        return None
    payload = json.dumps(blocks, ensure_ascii=False)
    (workdir / f"{stem}{CONTENT_LIST_SUFFIX}").write_text(payload, encoding="utf-8")
    return blocks


__all__ = [
    "CONTENT_LIST_SCHEMA_VERSION",
    "CONTENT_LIST_SUFFIX",
    "IMAGES_DIRNAME",
    "build_content_list",
    "write_content_list",
]
