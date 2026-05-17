"""Utility helpers for the visualize pipeline."""

from __future__ import annotations

import json
import re
from typing import Any


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


def is_widget_spec(data: Any) -> bool:
    """Return True if *data* looks like a DeepTutor widget spec dict."""
    if not isinstance(data, dict):
        return False
    return "metrics" in data or "controls" in data or "canvas_html" in data or "update_js" in data


def build_widget_from_spec(spec: dict[str, Any]) -> str:
    """Convert a structured widget spec into a complete, fixed-layout HTML page.

    The spec schema:
    {
      "metrics": [{"id": str, "label": str, "value": str|num, "unit": str}],
      "canvas_type": "svg" | "canvas2d",   # default "svg"
      "canvas_html": str,                  # inner SVG markup OR empty for canvas2d
      "draw_js":  str,                     # canvas2d only: body of draw(ctx,w,h,values)
      "controls": [
          {"type": "slider",  "id": str, "label": str,
           "min": num, "max": num, "step": num, "value": num},
          {"type": "toggle",  "id": str, "label": str, "value": bool},
          {"type": "button",  "id": str, "label": str}
      ],
      "update_js": str   # JS body run after every control change; has access to
                         #   values {id: currentValue}, updateMetric(id, text),
                         #   and for svg: the SVG element as dtSvg
                         #   and for canvas2d: redraw()
    }
    """
    metrics = spec.get("metrics") or []
    canvas_type = str(spec.get("canvas_type") or "svg").lower()
    canvas_html = str(spec.get("canvas_html") or "").strip()
    draw_js = str(spec.get("draw_js") or "").strip()
    controls = spec.get("controls") or []
    update_js = str(spec.get("update_js") or "").strip()

    # ── Build metric strip HTML ──────────────────────────────────────────────
    metric_items: list[str] = []
    for m in metrics:
        mid = str(m.get("id") or "").strip()
        label = str(m.get("label") or "").strip()
        value = str(m.get("value") if m.get("value") is not None else "").strip()
        unit = str(m.get("unit") or "").strip()
        display = f"{value}\u202f{unit}".strip() if unit else value
        id_attr = f' id="{mid}"' if mid else ""
        metric_items.append(
            f'<div class="dt-metric">'
            f'<span class="dt-metric-label">{label}</span>'
            f'<span class="dt-metric-value"{id_attr}>{display}</span>'
            f"</div>"
        )
    metrics_html = "\n      ".join(metric_items)

    # ── Build canvas zone HTML ───────────────────────────────────────────────
    if canvas_type == "canvas2d":
        canvas_zone = '<canvas id="dt-cv"></canvas>'
    else:
        # SVG — wrap provided markup in a responsive container
        inner = (
            canvas_html
            if canvas_html
            else '<svg id="dt-svg" viewBox="0 0 800 300" xmlns="http://www.w3.org/2000/svg"></svg>'
        )
        if "<svg" not in inner.lower():
            inner = f'<svg id="dt-svg" viewBox="0 0 800 300" xmlns="http://www.w3.org/2000/svg">{inner}</svg>'
        elif 'id="dt-svg"' not in inner and "id='dt-svg'" not in inner:
            inner = inner.replace("<svg", '<svg id="dt-svg"', 1)
        # Strip full-coverage background rects with white/light fills that LLMs
        # commonly inject — they hide our dark .dt-canvas background.
        inner = re.sub(
            r'<rect\b(?=[^>]*\bfill\s*=\s*["\'](?:#fff(?:fff)?|white|#f[0-9a-f]{5}'
            r'|rgb\(\s*25[0-9]\s*,\s*25[0-9]\s*,\s*25[0-9]\s*\))["\'])[^>]*/?>',
            "",
            inner,
            flags=re.IGNORECASE,
        )
        # Also strip rects that have style="...fill:white..." or style="background:white"
        inner = re.sub(
            r'<rect\b(?=[^>]*style\s*=\s*["\'][^"\'>]*?fill\s*:\s*(?:white|#fff)[^"\'>]*?["\'])[^>]*/?>',
            "",
            inner,
            flags=re.IGNORECASE,
        )
        canvas_zone = inner

    # ── Build controls HTML ──────────────────────────────────────────────────
    control_items: list[str] = []
    init_values: list[str] = []
    for c in controls:
        ctype = str(c.get("type") or "slider").lower()
        cid = str(c.get("id") or "").strip()
        clabel = str(c.get("label") or "").strip()
        cval = c.get("value")

        if ctype == "slider":
            cmin = c.get("min", 0)
            cmax = c.get("max", 100)
            cstep = c.get("step", 1)
            init_val = float(cval) if cval is not None else float(cmin)
            init_values.append(f'values["{cid}"] = {init_val};')
            # Format display: remove trailing .0 for whole numbers
            disp = str(int(init_val)) if init_val == int(init_val) else str(init_val)
            control_items.append(f"""
      <div class="dt-control-group">
        <span class="dt-control-label">{clabel}</span>
        <div class="dt-slider-row">
          <input type="range" id="ctrl-{cid}" min="{cmin}" max="{cmax}" step="{cstep}" value="{init_val}">
          <span class="dt-slider-value" id="val-{cid}">{disp}</span>
        </div>
      </div>""")

        elif ctype == "toggle":
            checked = "checked" if cval else ""
            init_bool = "true" if cval else "false"
            init_values.append(f'values["{cid}"] = {init_bool};')
            control_items.append(f"""
      <div class="dt-toggle-row">
        <label class="dt-toggle">
          <input type="checkbox" id="ctrl-{cid}" {checked}>
          <span class="dt-toggle-track"></span>
          <span class="dt-toggle-thumb"></span>
        </label>
        <span class="dt-control-label">{clabel}</span>
      </div>""")

        elif ctype == "button":
            control_items.append(f"""
      <button class="dt-btn" id="ctrl-{cid}">{clabel}</button>""")

    controls_html = "".join(control_items)
    init_values_js = "\n    ".join(init_values)

    # ── Canvas 2D setup ──────────────────────────────────────────────────────
    if canvas_type == "canvas2d":
        canvas_setup_js = f"""
    var dtCv = document.getElementById('dt-cv');
    dtCv.width  = dtCv.offsetWidth  || dtCv.parentElement.offsetWidth;
    dtCv.height = dtCv.offsetHeight || dtCv.parentElement.offsetHeight;
    var dtCtx = dtCv.getContext('2d');
    function dtDraw(values) {{
      var w = dtCv.width, h = dtCv.height;
      dtCtx.clearRect(0, 0, w, h);
      {draw_js}
    }}
    window.addEventListener('resize', function() {{
      dtCv.width  = dtCv.parentElement.offsetWidth;
      dtCv.height = dtCv.parentElement.offsetHeight;
      dtDraw(values);
    }});"""
        update_canvas_call = "dtDraw(values);"
    else:
        canvas_setup_js = "    var dtSvg = document.getElementById('dt-svg');"
        update_canvas_call = ""

    # ── Wire up controls JS ──────────────────────────────────────────────────
    wire_js_parts: list[str] = []
    for c in controls:
        ctype = str(c.get("type") or "slider").lower()
        cid = str(c.get("id") or "").strip()
        if ctype == "slider":
            wire_js_parts.append(f"""
    (function() {{
      var el = document.getElementById('ctrl-{cid}');
      var vl = document.getElementById('val-{cid}');
      if (!el) return;
      el.addEventListener('input', function() {{
        var n = parseFloat(el.value);
        values["{cid}"] = n;
        if (vl) vl.textContent = Number.isInteger(n) ? n : n.toFixed(1);
        runUpdate();
      }});
    }})();""")
        elif ctype == "toggle":
            wire_js_parts.append(f"""
    (function() {{
      var el = document.getElementById('ctrl-{cid}');
      if (!el) return;
      el.addEventListener('change', function() {{
        values["{cid}"] = el.checked;
        runUpdate();
      }});
    }})();""")

    wire_js = "".join(wire_js_parts)

    # ── Assemble full document ───────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  /* ── DeepTutor Widget Shell v1 — adapts to light & dark mode ── */
  :root {{
    color-scheme: light dark;
    /* Light mode defaults */
    --dt-text:         #111827;
    --dt-muted:        #6b7280;
    --dt-zone-bg:      rgba(0,0,0,0.04);
    --dt-zone-border:  rgba(0,0,0,0.1);
    --dt-divider:      rgba(0,0,0,0.1);
    --dt-track:        #d1d5db;
    --dt-thumb:        #3b82f6;
    --dt-val-bg:       rgba(0,0,0,0.07);
    --dt-val-border:   rgba(0,0,0,0.15);
    --dt-btn-bg:       rgba(0,0,0,0.07);
    --dt-btn-border:   rgba(0,0,0,0.15);
    --dt-toggle-off:   #d1d5db;
    --dt-svg-text:     #111827;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --dt-text:         #e4e4e7;
      --dt-muted:        #a1a1aa;
      --dt-zone-bg:      rgba(255,255,255,0.05);
      --dt-zone-border:  rgba(255,255,255,0.1);
      --dt-divider:      rgba(255,255,255,0.1);
      --dt-track:        #3f3f46;
      --dt-thumb:        #3b82f6;
      --dt-val-bg:       rgba(255,255,255,0.1);
      --dt-val-border:   rgba(255,255,255,0.15);
      --dt-btn-bg:       rgba(255,255,255,0.08);
      --dt-btn-border:   rgba(255,255,255,0.15);
      --dt-toggle-off:   #52525b;
      --dt-svg-text:     #e4e4e7;
    }}
    /* Dark-only: nuke LLM-injected white backgrounds */
    [style*="background: white"],[style*="background-color: white"],
    [style*="background:#fff"],[style*="background: #fff"],
    [style*="background:#ffffff"],[style*="background: #ffffff"],
    [style*="background-color:#fff"],[style*="background-color: #fff"],
    [style*="background-color:#ffffff"],[style*="background-color: #ffffff"] {{
      background: transparent !important;
      background-color: transparent !important;
    }}
    /* Dark-only: nuke LLM-injected black text */
    [style*="color: black"],[style*="color:black"],
    [style*="color: #000"],[style*="color:#000"],
    [style*="color: #000000"],[style*="color:#000000"] {{
      color: var(--dt-text) !important;
    }}
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    width: 100%; height: 100vh; overflow: hidden;
    background: transparent !important;
    color: var(--dt-text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
  }}
  /* Layout */
  .dt-widget {{
    display: flex; flex-direction: column;
    height: 100vh; padding: 10px; gap: 8px;
  }}
  /* Zone 1 — Metric Strip */
  .dt-metrics {{
    display: flex; flex-shrink: 0;
    background: var(--dt-zone-bg); border: 1px solid var(--dt-zone-border);
    border-radius: 10px; overflow: hidden;
  }}
  .dt-metric {{
    flex: 1; display: flex; flex-direction: column;
    align-items: center; padding: 7px 10px; gap: 1px;
  }}
  .dt-metric + .dt-metric {{ border-left: 1px solid var(--dt-divider); }}
  .dt-metric-label {{
    font-size: 10px; text-transform: uppercase;
    letter-spacing: 0.06em; color: var(--dt-muted);
  }}
  .dt-metric-value {{
    font-size: 17px; font-weight: 600; color: var(--dt-text);
    white-space: nowrap;
  }}
  /* Zone 2 — Diagram Canvas */
  .dt-canvas {{
    flex: 1; min-height: 0;
    background: var(--dt-zone-bg); border: 1px solid var(--dt-zone-border);
    border-radius: 10px; overflow: hidden; position: relative;
    display: flex; align-items: center; justify-content: center;
  }}
  .dt-canvas svg {{
    width: 100%; height: 100%; display: block;
    background: transparent !important;
  }}
  /* SVG text inherits the theme text color by default */
  .dt-canvas svg text {{ fill: var(--dt-svg-text); }}
  .dt-canvas svg text[fill="#000"],
  .dt-canvas svg text[fill="#000000"],
  .dt-canvas svg text[fill="black"] {{ fill: var(--dt-svg-text) !important; }}
  .dt-canvas canvas {{ width: 100%; height: 100%; display: block; }}
  /* Zone 3 — Controls */
  .dt-controls {{
    flex-shrink: 0;
    background: var(--dt-zone-bg); border: 1px solid var(--dt-zone-border);
    border-radius: 10px; padding: 8px 12px;
    display: flex; flex-direction: column; gap: 6px;
  }}
  .dt-control-group {{ display: flex; align-items: center; gap: 10px; }}
  .dt-control-label {{
    font-size: 12px; color: var(--dt-text); white-space: nowrap; min-width: 120px;
  }}
  .dt-slider-row {{ flex: 1; display: flex; align-items: center; gap: 8px; }}
  input[type="range"] {{
    flex: 1; -webkit-appearance: none; appearance: none;
    height: 4px; border-radius: 2px; background: var(--dt-track);
    accent-color: var(--dt-thumb); cursor: pointer; outline: none;
  }}
  input[type="range"]::-webkit-slider-thumb {{
    -webkit-appearance: none; width: 16px; height: 16px;
    border-radius: 50%; background: var(--dt-thumb); cursor: pointer;
    box-shadow: 0 1px 4px rgba(0,0,0,.3);
  }}
  .dt-slider-value {{
    font-size: 12px; font-weight: 500; color: var(--dt-text);
    background: var(--dt-val-bg); border: 1px solid var(--dt-val-border);
    border-radius: 5px; padding: 1px 7px; min-width: 38px; text-align: center;
  }}
  /* Toggle */
  .dt-toggle-row {{ display: flex; align-items: center; gap: 8px; }}
  .dt-toggle {{ position: relative; width: 38px; height: 20px; flex-shrink: 0; }}
  .dt-toggle input {{ display: none; }}
  .dt-toggle-track {{
    position: absolute; inset: 0;
    background: var(--dt-toggle-off); border-radius: 10px; cursor: pointer;
    transition: background .2s;
  }}
  .dt-toggle input:checked + .dt-toggle-track {{ background: var(--dt-thumb); }}
  .dt-toggle-thumb {{
    position: absolute; top: 2px; left: 2px;
    width: 16px; height: 16px; border-radius: 50%;
    background: #fff; pointer-events: none; transition: left .2s;
  }}
  .dt-toggle input:checked ~ .dt-toggle-thumb {{ left: 20px; }}
  /* Button */
  .dt-btn {{
    background: var(--dt-btn-bg); border: 1px solid var(--dt-btn-border);
    color: var(--dt-text); border-radius: 7px; padding: 4px 14px;
    font-size: 12px; cursor: pointer; transition: background .15s;
  }}
  .dt-btn:hover {{ filter: brightness(1.1); }}
</style>
</head>
<body>
<div class="dt-widget">
  <!-- Zone 1: Metric Strip -->
  <div class="dt-metrics">
    {metrics_html}
  </div>
  <!-- Zone 2: Diagram Canvas -->
  <div class="dt-canvas" id="dt-canvas-zone">
    {canvas_zone}
  </div>
  <!-- Zone 3: Controls -->
  <div class="dt-controls">
    {controls_html}
  </div>
</div>
<script>
document.addEventListener('DOMContentLoaded', function() {{
  /* Control state */
  var values = {{}};
  {init_values_js}

  /* Helper: update a metric pill text by id */
  function updateMetric(id, text) {{
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }}

  /* Canvas setup */
  {canvas_setup_js}

  /* Wire controls */
  {wire_js}

  /* LLM-provided update logic */
  function runUpdate() {{
    {update_canvas_call}
    {update_js}
  }}

  /* Initial render */
  runUpdate();
}});
</script>
</body>
</html>"""


__all__ = [
    "build_fallback_html",
    "build_widget_from_spec",
    "extract_code_block",
    "extract_json_object",
    "is_valid_html_document",
    "is_widget_spec",
]
