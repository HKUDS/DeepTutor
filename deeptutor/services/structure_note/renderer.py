from __future__ import annotations

from html import escape
import json
from pathlib import Path
import re

from .markdown_postprocessor import (
    normalize_structure_note_markdown,
    validate_renderer_compatible_markdown,
)
from .models import CitationEntry

_STYLE = """
@page {
  margin: 20mm 16mm;
}
body {
  font-family: "Helvetica", Arial, sans-serif;
  color: #202427;
  font-size: 11pt;
  line-height: 1.65;
}
h1, h2, h3, h4 {
  color: #111827;
  page-break-after: avoid;
  text-wrap: balance;
}
h1 {
  font-size: 22pt;
  margin-bottom: 8mm;
}
h2 {
  font-size: 16pt;
  margin-top: 8mm;
}
h3 {
  font-size: 13pt;
  margin-top: 6mm;
}
p, li {
  orphans: 3;
  widows: 3;
}
img {
  max-width: 100%;
  border-radius: 4px;
  margin: 6mm 0 2mm;
}
figure, table, pre {
  page-break-inside: avoid;
}
code {
  background: #f3f4f6;
  padding: 0.1rem 0.25rem;
  border-radius: 3px;
}
.math-inline {
  font-family: "Courier New", monospace;
  background: #f9fafb;
  border-radius: 3px;
  padding: 0.05rem 0.2rem;
}
blockquote {
  border-left: 3px solid #d1d5db;
  color: #4b5563;
  padding-left: 12px;
  margin-left: 0;
}
.math-block {
  display: block;
  margin: 4mm 0;
  padding: 3mm 4mm;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  overflow-wrap: anywhere;
}
.math-block pre {
  margin: 0;
  white-space: pre-wrap;
  font-family: "Courier New", monospace;
  font-size: 10pt;
  line-height: 1.45;
  background: transparent;
}
"""


class RenderError(RuntimeError):
    pass


_MATH_BLOCK_RE = re.compile(r"(?<!\$)\$\$\s*([\s\S]*?)\s*\$\$(?!\$)")
_MATH_INLINE_RE = re.compile(r"(?<!\\)(?<!\$)\$(?!\$|\s)([^$\n]+?)(?<!\s)(?<!\\)\$(?!\$)")
_FENCE_RE = re.compile(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)")


def _render_math_for_pdf(markdown_text: str) -> str:
    parts: list[str] = []
    last = 0
    for match in _FENCE_RE.finditer(markdown_text):
        if match.start() > last:
            parts.append(_render_math_in_non_fenced_text(markdown_text[last : match.start()]))
        parts.append(match.group(0))
        last = match.end()
    if last < len(markdown_text):
        parts.append(_render_math_in_non_fenced_text(markdown_text[last:]))
    return "".join(parts)


def _render_math_in_non_fenced_text(markdown_text: str) -> str:
    def replace_display(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if not expression:
            return ""
        return f'\n\n<div class="math-block"><pre>{escape(expression)}</pre></div>\n\n'

    def replace_inline(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if not expression:
            return ""
        return f'<span class="math-inline">{escape(expression)}</span>'

    rendered = _MATH_BLOCK_RE.sub(replace_display, markdown_text)
    return _MATH_INLINE_RE.sub(replace_inline, rendered)


def render_pdf(
    markdown_text: str,
    title: str,
    citation_entries: list[CitationEntry],
    job_dir: Path,
    final_dir: Path,
) -> tuple[Path, Path]:
    try:
        from markdown import markdown
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise RenderError(
            "The `markdown` package is required for Structure Note rendering."
        ) from exc

    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise RenderError(
            "WeasyPrint is required for Structure Note PDF export. Install `weasyprint` and retry."
        ) from exc

    markdown_text = normalize_structure_note_markdown(markdown_text)
    validation = validate_renderer_compatible_markdown(markdown_text)
    if not validation.ok:
        detail = "; ".join(validation.warnings)
        raise RenderError(f"Structure Note Markdown contains unsupported math syntax: {detail}")

    final_dir.mkdir(parents=True, exist_ok=True)
    html_ready_markdown = _render_math_for_pdf(markdown_text)
    html_body = markdown(html_ready_markdown, extensions=["extra", "fenced_code", "tables", "toc"])
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{_STYLE}</style>"
        "</head><body>"
        f"{html_body}</body></html>"
    )

    pdf_path = final_dir / "final.pdf"
    HTML(string=html, base_url=str(job_dir)).write_pdf(str(pdf_path))

    citation_path = final_dir / "citation_manifest.json"
    with open(citation_path, "w", encoding="utf-8") as handle:
        json.dump(
            [entry.model_dump(mode="json") for entry in citation_entries],
            handle,
            ensure_ascii=False,
            indent=2,
        )

    return pdf_path, citation_path
