"""Utility helpers for the visualize pipeline."""

from __future__ import annotations

import json
import re
from typing import Any

import defusedxml.ElementTree as ET

_MERMAID_KEYWORDS = (
    "graph",
    "flowchart",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "erDiagram",
    "gantt",
    "mindmap",
    "pie",
    "journey",
    "gitGraph",
    "timeline",
    "quadrantChart",
    "requirementDiagram",
    "sankey-beta",
    "xychart-beta",
    "block-beta",
    "C4Context",
)


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from raw model output."""
    raw = (text or "").strip()
    if not raw:
        return {}

    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    candidates = fenced + [raw]

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            parsed = _decode_first_json_object(candidate)
            if parsed is not None:
                return parsed

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = raw[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            parsed = _decode_first_json_object(snippet)
            if parsed is not None:
                return parsed

    raise json.JSONDecodeError("No JSON object found", raw, 0)


def _decode_first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    stripped = (text or "").lstrip()
    if not stripped:
        return None

    starts = [0]
    brace_index = stripped.find("{")
    if brace_index > 0:
        starts.append(brace_index)

    for start in starts:
        try:
            parsed, _end = decoder.raw_decode(stripped[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_code_block(text: str, language: str = "") -> str:
    """Extract a fenced code block from LLM output.

    If *language* is given the block must start with that tag;
    otherwise any triple-backtick fence is accepted.
    """
    if language:
        pattern = rf"```{re.escape(language)}\s*\n([\s\S]*?)\n```"
    else:
        pattern = r"```[A-Za-z]*\s*\n([\s\S]*?)\n```"
    match = re.search(pattern, text or "", re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return (text or "").strip()


def is_valid_html_document(html: str) -> bool:
    """Heuristic check that *html* looks like a renderable HTML fragment."""
    if not html:
        return False
    lowered = html.lower()
    return "<html" in lowered or "<!doctype" in lowered or "<body" in lowered or "<div" in lowered


def build_fallback_html(*, title: str, summary: str = "", note: str = "") -> str:
    """Build a minimal, self-contained fallback HTML page.

    Used when the model fails to produce a renderable HTML document, so the
    user still gets *something* shown in the iframe instead of a blank panel.
    """
    safe_title = (title or "Visualization").strip() or "Visualization"
    safe_summary = (summary or "").replace("\n", "<br>") or (
        "The model did not return a renderable HTML document."
    )
    safe_note = (note or "").replace("\n", "<br>")

    note_block = (
        f'<div class="note"><strong>Note:</strong><br>{safe_note}</div>' if safe_note else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       background:linear-gradient(135deg,#F8FAFC 0%,#EFF6FF 100%);
       min-height:100vh;padding:2rem;color:#1E293B;}}
  .card{{max-width:760px;margin:0 auto;background:#fff;border-radius:16px;
        padding:1.75rem 2rem;box-shadow:0 4px 6px -1px rgba(0,0,0,.08);}}
  h1{{color:#1E40AF;font-size:1.4rem;margin-bottom:1rem;}}
  .summary{{line-height:1.7;color:#475569;}}
  .note{{margin-top:1rem;padding:0.9rem 1rem;background:#FEF3C7;
        border-left:4px solid #F59E0B;border-radius:0 8px 8px 0;color:#92400E;}}
</style>
</head>
<body>
  <div class="card">
    <h1>{safe_title}</h1>
    <div class="summary">{safe_summary}</div>
    {note_block}
  </div>
</body>
</html>"""


def _strip_outer_fence(text: str) -> str:
    """Drop a single wrapping triple-backtick fence, if present."""
    stripped = (text or "").strip()
    match = re.match(r"^```[A-Za-z]*\s*\n?([\s\S]*?)\n?```$", stripped)
    return match.group(1).strip() if match else stripped


def validate_visualization(code: str, render_type: str) -> tuple[bool, str]:
    """Cheap, deterministic, local render-ability check.

    Returns ``(ok, error)``. When ``ok`` is False, ``error`` is a short,
    LLM-actionable message used to drive a single repair pass — none of these
    failures need an LLM call to *discover*. This replaces the generic LLM
    review for the text render types: only when local validation fails do we
    spend a model call (a targeted repair, not an open-ended review).
    """
    text = (code or "").strip()
    if not text:
        return False, "Generated code is empty."

    if render_type == "svg":
        if "<svg" not in text.lower():
            return False, "SVG must contain a root <svg> element."
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            return False, f"SVG is not well-formed XML: {exc}"
        tag = root.tag.split("}")[-1].lower()
        if tag != "svg":
            return False, f"Root element must be <svg>, found <{tag}>."
        # Case-sensitive: SVG only honors the camelCase ``viewBox``; a
        # lowercase ``viewbox`` is ignored by the browser and collapses the
        # figure, so it must NOT pass validation.
        if "viewBox" not in root.attrib:
            return False, (
                "SVG root is missing a viewBox attribute (must be camelCase "
                "`viewBox`, required for responsive scaling)."
            )
        return True, ""

    if render_type == "chartjs":
        candidate = _strip_outer_fence(text)
        try:
            config = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            return False, (
                "Chart.js config must be strict JSON: double-quoted keys, no "
                "function callbacks, no comments, no trailing commas."
            )
        if not isinstance(config, dict):
            return False, "Chart.js config must be a JSON object."
        missing = [field for field in ("type", "data") if field not in config]
        if missing:
            return False, f"Chart.js config is missing required field(s): {', '.join(missing)}."
        return True, ""

    if render_type == "mermaid":
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        # `---` front-matter and `%%{init}` directives are valid lead-ins.
        if (
            first_line.startswith(_MERMAID_KEYWORDS)
            or first_line.startswith("%%")
            or first_line.startswith("---")
        ):
            return True, ""
        return False, (
            "Mermaid code must start with a valid diagram keyword (graph, "
            "flowchart, sequenceDiagram, classDiagram, stateDiagram-v2, "
            "erDiagram, gantt, mindmap, ...)."
        )

    if render_type == "html":
        if is_valid_html_document(text):
            return True, ""
        return False, "Output does not look like a renderable HTML document."

    # Unknown render types are not gated.
    return True, ""


__all__ = [
    "build_fallback_html",
    "extract_code_block",
    "extract_json_object",
    "is_valid_html_document",
    "validate_visualization",
]
