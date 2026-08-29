"""Map frozen DeepTutor MinerU blocks to LightRAG's public Sidecar IR."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


class SidecarMappingError(ValueError):
    """Raised when a structured block cannot be represented without data loss."""


def _text(item: dict[str, Any]) -> str:
    for key in ("text", "content", "body", "code_body"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    value = str(value or "").strip()
    return [value] if value else []


def _position(item: dict[str, Any]):
    from lightrag.sidecar.ir import IRPosition

    page = item.get("page_idx", item.get("page"))
    if isinstance(page, bool):
        page = None
    elif isinstance(page, int):
        page = str(page + 1) if page >= 0 else str(page)
    elif page is not None:
        page = str(page).strip() or None
    bbox = item.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            return IRPosition(type="bbox", anchor=page, range=[float(value) for value in bbox[:4]])
        except (TypeError, ValueError):
            pass
    return IRPosition(type="bbox", anchor=page) if page is not None else None


def _heading(item: dict[str, Any], kind: str) -> tuple[str, int]:
    level = item.get("text_level", item.get("level", 0))
    try:
        level = int(level or 0)
    except (TypeError, ValueError):
        level = 0
    if kind in {"title", "section_header"}:
        return _text(item), max(level, 1)
    if kind == "text" and level > 0:
        return _text(item), level
    return "", 0


def _rows(value: Any) -> list[list[str]] | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                return None
        else:
            return None
    if not isinstance(value, list):
        return None
    rows: list[list[str]] = []
    for raw_row in value:
        if not isinstance(raw_row, list):
            continue
        rows.append(
            [
                str(cell.get("text", "")).strip() if isinstance(cell, dict) else str(cell).strip()
                for cell in raw_row
            ]
        )
    return rows or None


def _caption(item: dict[str, Any], *keys: str) -> str:
    direct = str(item.get("caption") or "").strip()
    if direct:
        return direct
    for key in keys:
        values = _strings(item.get(key))
        if values:
            return values[0]
    return ""


def _resolve_asset(bundle: Path, manifest: dict[str, Any], raw: str) -> Path | None:
    if not raw:
        return None
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise SidecarMappingError(f"Asset path escapes the frozen bundle: {raw}")
    candidates: list[Path] = []
    direct = bundle / "assets" / relative
    if direct.is_file():
        candidates.append(direct)
    basename = relative.name
    for record in manifest.get("assets", []):
        path = bundle / str(record.get("path") or "")
        if path.name == basename and path.is_file() and path not in candidates:
            candidates.append(path)
    if len(candidates) > 1:
        raise SidecarMappingError(f"Asset basename is ambiguous in the frozen bundle: {raw}")
    return candidates[0] if candidates else None


def build_ir(manifest: dict[str, Any], bundle: Path):
    """Return an ``IRDoc`` using only LightRAG's public Sidecar types."""
    from lightrag.sidecar.ir import (
        AssetSpec,
        IRBlock,
        IRDoc,
        IRDrawing,
        IREquation,
        IRTable,
    )

    blocks_record = manifest.get("blocks")
    if not isinstance(blocks_record, dict):
        raise SidecarMappingError("Sidecar mapping requires a blocks payload")
    raw_blocks = json.loads((bundle / blocks_record["path"]).read_text(encoding="utf-8"))
    if not isinstance(raw_blocks, list):
        raise SidecarMappingError("Frozen blocks payload is not an array")

    output: list[Any] = []
    assets: list[Any] = []
    asset_refs: dict[Path, str] = {}
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_tables: list[Any] = []
    current_drawings: list[Any] = []
    current_equations: list[Any] = []
    current_positions: list[Any] = []
    current_heading = "Preface/Uncategorized"
    current_level = 0
    current_parents: list[str] = []
    sequence = 0
    document_title = ""

    def next_key(prefix: str) -> str:
        nonlocal sequence
        sequence += 1
        return f"{prefix}{sequence}"

    def flush() -> None:
        nonlocal \
            current_lines, \
            current_tables, \
            current_drawings, \
            current_equations, \
            current_positions
        content = "\n".join(line for line in current_lines if line).strip()
        if not content and not (current_tables or current_drawings or current_equations):
            current_lines = []
            current_positions = []
            return
        output.append(
            IRBlock(
                content_template=content,
                heading=current_heading,
                level=current_level,
                parent_headings=list(current_parents),
                positions=list(current_positions),
                tables=list(current_tables),
                drawings=list(current_drawings),
                equations=list(current_equations),
            )
        )
        current_lines = []
        current_tables = []
        current_drawings = []
        current_equations = []
        current_positions = []

    for index, item in enumerate(raw_blocks):
        if not isinstance(item, dict):
            raise SidecarMappingError(f"Structured block {index} is not an object")
        kind = str(item.get("type") or item.get("label") or "").strip().lower()
        heading, level = _heading(item, kind)
        position = _position(item)
        if heading:
            flush()
            heading = re.sub(r"^#{1,6}\s+", "", heading).strip()
            heading_stack = heading_stack[: max(level - 1, 0)]
            current_parents = [value for value in heading_stack if value]
            heading_stack.append(heading)
            current_heading = heading
            current_level = level
            current_lines.append(f"{'#' * min(level, 6)} {heading}")
            if position is not None:
                current_positions.append(position)
            if not document_title and level == 1:
                document_title = heading
            continue

        if kind in {"text", "aside_text", "page_footnote"}:
            value = _text(item)
            if value:
                current_lines.append(value)
        elif kind == "list":
            values = item.get("list_items")
            value = "\n".join(_strings(values)) if isinstance(values, list) else _text(item)
            if value:
                current_lines.append(value)
        elif kind == "code":
            value = str(item.get("code_body") or _text(item)).strip()
            if value:
                current_lines.extend(_strings(item.get("code_caption")))
                current_lines.append(value)
                current_lines.extend(_strings(item.get("code_footnote")))
        elif kind == "table":
            body = item.get("rows", item.get("table_body"))
            table_rows = _rows(body)
            table_html = (
                body.strip() if isinstance(body, str) and "<table" in body.lower() else None
            )
            if not table_rows and not table_html:
                raise SidecarMappingError(f"Structured table {index} has no usable body")
            key = next_key("tb")
            current_tables.append(
                IRTable(
                    placeholder_key=key,
                    rows=table_rows,
                    html=table_html,
                    num_rows=int(item.get("num_rows") or (len(table_rows) if table_rows else 0)),
                    num_cols=int(
                        item.get("num_cols") or (max(map(len, table_rows)) if table_rows else 0)
                    ),
                    caption=_caption(item, "table_caption"),
                    footnotes=_strings(item.get("table_footnote") or item.get("footnotes")),
                    table_header=_rows(item.get("header")),
                    self_ref=f"blocks.json#/{index}",
                )
            )
            current_lines.append(f"{{{{TBL:{key}}}}}")
        elif kind in {"image", "picture", "drawing", "chart"}:
            raw_path = str(item.get("img_path") or item.get("path") or "")
            asset_path = _resolve_asset(bundle, manifest, raw_path)
            if asset_path is None:
                raise SidecarMappingError(f"Structured {kind} {index} has no verified bundle asset")
            ref = ""
            ref = asset_refs.get(asset_path, "")
            if not ref:
                ref = f"asset-{len(asset_refs) + 1}"
                asset_refs[asset_path] = ref
                assets.append(AssetSpec(ref=ref, suggested_name=asset_path.name, source=asset_path))
            key = next_key("im")
            current_drawings.append(
                IRDrawing(
                    placeholder_key=key,
                    asset_ref=ref,
                    fmt=Path(raw_path).suffix.lower().lstrip(".") or str(item.get("format") or ""),
                    caption=_caption(item, "image_caption", "chart_caption", "captions"),
                    footnotes=_strings(
                        item.get("image_footnote")
                        or item.get("chart_footnote")
                        or item.get("footnotes")
                    ),
                    src=str(item.get("src") or ""),
                    self_ref=f"blocks.json#/{index}",
                )
            )
            current_lines.append(f"{{{{IMG:{key}}}}}")
        elif kind in {"equation", "formula"}:
            latex = _text(item)
            if not latex:
                raise SidecarMappingError(f"Structured equation {index} has no LaTeX")
            key = next_key("eq")
            inline = str(item.get("text_format") or "").lower() in {"inline", "inline_equation"}
            current_equations.append(
                IREquation(
                    placeholder_key=key,
                    latex=latex,
                    is_block=not inline,
                    caption=_caption(item, "equation_caption"),
                    footnotes=_strings(item.get("equation_footnote") or item.get("footnotes")),
                    self_ref=f"blocks.json#/{index}" if not inline else "",
                )
            )
            current_lines.append(f"{{{{{'EQI' if inline else 'EQ'}:{key}}}}}")
        else:
            value = _text(item)
            if not value:
                raise SidecarMappingError(
                    f"Unknown structured block type {kind or '<missing>'!r} at {index} has no preservable text"
                )
            current_lines.append(value)
        if position is not None:
            current_positions.append(position)

    flush()
    if not output:
        raise SidecarMappingError("Structured document produced no Sidecar blocks")
    name = str(manifest.get("canonical_filename") or "document")
    return IRDoc(
        document_name=name,
        document_format=Path(name).suffix.lower().lstrip("."),
        doc_title=document_title or Path(name).stem,
        split_option={
            "parser": str((manifest.get("parser") or {}).get("engine") or ""),
            "parser_signature": str((manifest.get("parser") or {}).get("parser_signature") or ""),
        },
        blocks=output,
        assets=assets,
        bbox_attributes={"origin": "LEFTTOP", "max": 1000},
    )


__all__ = ["SidecarMappingError", "build_ir"]
