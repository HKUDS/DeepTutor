"""Browser layout check for a built video lesson.

The compile/render check proves the lesson runs; it cannot see that a drawing
crosses a title or that a label lands on a card. This opens the finished page
in headless Chrome at sample frames, measures every visible text box and
samples points along every visible SVG stroke, and reports collisions in the
1920x1080 composition's own coordinates so the writer can move things.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess  # nosec B404 - fixed argv, local file only
import tempfile

CAPTION_TOP = 880  # the kit's captions own everything below this line
_MAX_ISSUES = 14

_PROBE = r"""
<script>
(function () {
  function opacityOf(el) {
    let o = 1;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === "none" || cs.visibility === "hidden") return 0;
      o *= parseFloat(cs.opacity || "1");
    }
    return o;
  }
  // Computed CSS colors can carry alpha independently of fill/stroke opacity.
  // Unknown paints (including gradients and patterns) stay conservatively visible.
  function paintAlpha(paint) {
    const color = (paint || '').trim().toLowerCase();
    if (color === 'transparent' || color === 'none') return 0;
    const slash = color.match(/\/\s*([\d.]+%?)\s*\)$/);
    const rgba = color.match(/^rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+%?)\s*\)$/);
    const alpha = slash?.[1] ?? rgba?.[1];
    if (alpha !== undefined) {
      const n = parseFloat(alpha) / (alpha.endsWith('%') ? 100 : 1);
      return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 1;
    }
    return 1;
  }
  function probe() {
    if (__STRICT_FRAME__) {
      const target = Number(new URLSearchParams(location.search).get("frame"));
      if (typeof window.__videoLessonGetFrame !== "function" || window.__videoLessonGetFrame() !== target)
        return {error: "player did not reach the requested frame"};
    }
    const expectedScenes = __EXPECTED_SCENES__;
    if (expectedScenes !== null && JSON.stringify(window.__videoLessonSceneLengths) !== JSON.stringify(expectedScenes))
      return {error: "browser scene timeline differs from isolated render"};
    const root = [...document.querySelectorAll("div")].find(
      (d) => d.style.width === "1920px" && d.style.height === "1080px");
    if (!root) return {error: "composition root not found"};
    const r = root.getBoundingClientRect(), k = r.width / 1920;
    const toC = (x, y) => [(x - r.left) / k, (y - r.top) / k];
    const texts = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const s = n.textContent.trim();
      if (!s || !n.parentElement || opacityOf(n.parentElement) < 0.15) continue;
      const range = document.createRange(); range.selectNodeContents(n);
      for (const b of range.getClientRects()) {
        if (b.width < 2 || b.height < 2) continue;
        const [x0, y0] = toC(b.left, b.top), [x1, y1] = toC(b.right, b.bottom);
        const cap = !!n.parentElement.closest('div[style*="bottom: 64px"]');
        texts.push({el: n.parentElement, s: s.slice(0, 48), cap, x0, y0, x1, y1});
      }
    }
    const issues = [];
    const frame = Number(new URLSearchParams(location.search).get("frame"));
    if (frame === 0) {
      const content = root.querySelector("[data-scene-content]");
      const problem = texts.some((t) => !t.cap && content && content.contains(t.el) && !t.el.closest("[data-title]"));
      if (content && !problem) issues.push("frame 0 shows the title without the visible problem, givens or goal; show that text immediately and do not delay it");
    }
    // A clipped region is not a valid layout even if the hidden part cannot be seen.
    for (const region of root.querySelectorAll('[data-scene-content], [data-scene-graphic]')) {
      if (opacityOf(region) < 0.15) continue;
      // SVG canvases can be larger than their drawing (the kit uses full-frame canvases).
      // Exclude those canvases while measuring HTML overflow; the actual SVG paths are
      // checked against clipping ancestors below. Restore inline styles synchronously.
      const svgs = [...region.querySelectorAll('svg')].filter((svg) =>
        !svg.parentElement.closest('svg') && /^(absolute|fixed)$/.test(getComputedStyle(svg).position));
      const displays = svgs.map((svg) => [svg, svg.style.getPropertyValue('display'), svg.style.getPropertyPriority('display')]);
      let htmlOverflow;
      try {
        for (const [svg] of displays) svg.style.setProperty('display', 'none', 'important');
        htmlOverflow = region.scrollHeight > region.clientHeight + 2 || region.scrollWidth > region.clientWidth + 2;
      } finally {
        for (const [svg, value, priority] of displays) {
          if (value) svg.style.setProperty('display', value, priority);
          else svg.style.removeProperty('display');
        }
      }
      if (htmlOverflow) issues.push(`scene region content overflows or is clipped; split or resize it`);
      const bounds = region.getBoundingClientRect();
      for (const t of texts) {
        if (!region.contains(t.el)) continue;
        const [x0, y0] = toC(bounds.left, bounds.top), [x1, y1] = toC(bounds.right, bounds.bottom);
        if (t.x0 < x0 - 2 || t.y0 < y0 - 2 || t.x1 > x1 + 2 || t.y1 > y1 + 2)
          issues.push(`text "${t.s}" overflows its scene region (${Math.round(t.x0)},${Math.round(t.y0)}-${Math.round(t.x1)},${Math.round(t.y1)} vs ${Math.round(x0)},${Math.round(y0)}-${Math.round(x1)},${Math.round(y1)})`);
      }
    }
    // text on text
    for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
      const a = texts[i], b = texts[j];
      if (a.cap || b.cap || a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0), h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
      if (w > 4 && h > 4) issues.push(`text "${a.s}" overlaps text "${b.s}" near x=${Math.round(Math.max(a.x0, b.x0))}, y=${Math.round(Math.max(a.y0, b.y0))}`);
    }
    // text leaving the safe area
    for (const t of texts) {
      if (t.cap) {
        if (t.y0 < __CAPTION_TOP__ - 60) issues.push(`the caption "${t.s}" wraps to three lines and climbs to y=${Math.round(t.y0)}; split that narration sentence (keep each under 18 words)`);
        continue;
      }
      if (t.y1 > __CAPTION_TOP__ + 2) issues.push(`text "${t.s}" reaches y=${Math.round(t.y1)}, inside the caption band (keep everything above y=${__CAPTION_TOP__})`);
      if (t.x0 < 40 || t.x1 > 1880 || t.y0 < 20) issues.push(`text "${t.s}" runs off the frame edge`);
    }
    // strokes through text / into the caption band
    // opaque boxes (cards, panels) covering text that is not inside them
    const opaque = (cs) => {
      const m = (cs.backgroundColor || "").match(/rgba?\(([^)]+)\)/);
      if (!m) return false;
      const parts = m[1].split(",").map(Number);
      return parts.length < 4 || parts[3] > 0.6;
    };
    for (const box of root.querySelectorAll("div,section,aside")) {
      if (box === root || opacityOf(box) < 0.15 || !opaque(getComputedStyle(box))) continue;
      const b = box.getBoundingClientRect();
      const [bx0, by0] = toC(b.left, b.top), [bx1, by1] = toC(b.right, b.bottom);
      if (bx1 - bx0 < 40 || by1 - by0 < 20 || (bx1 - bx0 > 1800 && by1 - by0 > 1000)) continue;
      const label = (box.textContent || "").trim().slice(0, 32);
      for (const t of texts) {
        if (t.cap || box.contains(t.el) || t.el.contains(box)) continue;
        const w = Math.min(t.x1, bx1) - Math.max(t.x0, bx0), h = Math.min(t.y1, by1) - Math.max(t.y0, by0);
        if (w > 4 && h > 4) issues.push(`the box "${label}" (x ${Math.round(bx0)}-${Math.round(bx1)}, y ${Math.round(by0)}-${Math.round(by1)}) covers the text "${t.s}"; move one of them`);
      }
    }
    const crossed = new Map(); const bandHits = [];
    const clippingAncestors = (element) => {
      const clips = [];
      for (let p = element.parentElement; p && p !== root; p = p.parentElement) {
        const ps = getComputedStyle(p);
        const clipX = /^(hidden|clip|scroll|auto)$/.test(ps.overflowX);
        const clipY = /^(hidden|clip|scroll|auto)$/.test(ps.overflowY);
        if (clipX || clipY) clips.push({rect: p.getBoundingClientRect(), clipX, clipY});
      }
      return clips;
    };
    // SVG images draw pixels, unlike the full-canvas SVG container itself.
    for (const image of root.querySelectorAll('svg image')) {
      if (opacityOf(image) < 0.15) continue;
      const b = image.getBoundingClientRect();
      if (b.width < 1 || b.height < 1) continue;
      if (clippingAncestors(image).some(({rect, clipX, clipY}) =>
        (clipX && (b.left < rect.left - 2 * k || b.right > rect.right + 2 * k)) ||
        (clipY && (b.top < rect.top - 2 * k || b.bottom > rect.bottom + 2 * k))))
        issues.push('drawn SVG image is clipped; move or resize it');
    }
    const shapes = root.querySelectorAll("path,line,polyline,polygon,circle,ellipse,rect");
    for (const g of shapes) {
      const opacity = opacityOf(g);
      if (!g.getTotalLength || opacity < 0.15) continue;
      const cs = getComputedStyle(g);
      const hasStroke = cs.stroke !== "none" && parseFloat(cs.strokeWidth || "0") > 0 &&
        opacity * parseFloat(cs.strokeOpacity || "1") * paintAlpha(cs.stroke) >= 0.15;
      const hasFill = cs.fill !== "none" && !["line", "polyline"].includes(g.tagName.toLowerCase()) &&
        opacity * parseFloat(cs.fillOpacity || "1") * paintAlpha(cs.fill) >= 0.15;
      if (!hasStroke && !hasFill) continue;
      const clips = clippingAncestors(g);
      let L; try { L = g.getTotalLength(); } catch (e) { continue; }
      if (!L || L < 4) continue;
      let visible = L;
      const dash = (cs.strokeDasharray || "none").split(/[ ,]+/).map(parseFloat).filter((v) => !isNaN(v));
      if (dash.length && dash[0] >= L * 0.95) visible = Math.max(0, L - Math.abs(parseFloat(cs.strokeDashoffset || "0")));
      const m = g.getScreenCTM(); if (!m) continue;
      // Transform the stroke's circular half-width into screen-space x/y radii.
      const halfStroke = hasStroke ? parseFloat(cs.strokeWidth) / 2 : 0;
      const nonScaling = cs.vectorEffect === 'non-scaling-stroke';
      const strokeX = halfStroke * (nonScaling ? 1 : Math.hypot(m.a, m.c));
      const strokeY = halfStroke * (nonScaling ? 1 : Math.hypot(m.b, m.d));
      const svg = g.ownerSVGElement;
      const hitText = new Map(); let inBand = null; let clipped = null;
      const n = Math.min(400, Math.max(8, Math.ceil(visible / 6)));
      for (let i = 0; i <= n; i++) {
        const p = g.getPointAtLength((visible * i) / n);
        const sp = svg.createSVGPoint(); sp.x = p.x; sp.y = p.y;
        const q = sp.matrixTransform(m); const [x, y] = toC(q.x, q.y);
        if (clips.some(({rect, clipX, clipY}) =>
          (clipX && (q.x - strokeX < rect.left - 2 * k || q.x + strokeX > rect.right + 2 * k)) ||
          (clipY && (q.y - strokeY < rect.top - 2 * k || q.y + strokeY > rect.bottom + 2 * k)))) clipped = clipped || [x, y];
        if (y > __CAPTION_TOP__ + 3 && y < 1080 && x > 0 && x < 1920) inBand = inBand || [x, y];
        for (const t of texts) {
          if (x > t.x0 + 2 && x < t.x1 - 2 && y > t.y0 + 2 && y < t.y1 - 2) {
            const e = hitText.get(t.s) || {count: 0, x, y}; e.count++; hitText.set(t.s, e);
          }
        }
      }
      if (clipped) issues.push(`drawn shape is clipped near x=${Math.round(clipped[0])}, y=${Math.round(clipped[1])}; move or resize it`);
      for (const [s, e] of hitText) if (hasStroke && e.count >= 2) {
        const c = crossed.get(s) || {n: 0, x: e.x, y: e.y}; c.n++; crossed.set(s, c);
      }
      if (inBand) bandHits.push(inBand);
    }
    for (const [s, c] of crossed) issues.push(`${c.n} drawn line${c.n > 1 ? "s" : ""} cross the text "${s}" near x=${Math.round(c.x)}, y=${Math.round(c.y)}; move the text or shrink/move the drawing so they no longer meet`);
    if (bandHits.length) {
      const ys = bandHits.map((p) => p[1]), xs = bandHits.map((p) => p[0]);
      issues.push(`${bandHits.length} drawn shape${bandHits.length > 1 ? "s" : ""} enter the caption band (x ${Math.round(Math.min(...xs))}-${Math.round(Math.max(...xs))}, down to y=${Math.round(Math.max(...ys))}); keep every drawing above y=${__CAPTION_TOP__}`);
    }
    return {issues: [...new Set(issues)]};
  }
  window.addEventListener("load", () => setTimeout(() => {
    let out; try { out = probe(); } catch (e) { out = {error: String(e)}; }
    parent.postMessage({frame: new URLSearchParams(location.search).get("frame"), ...out}, "*");
  }, 1500));
})();
</script>
"""

_HOST = """<!doctype html><html><body><pre id="out"></pre><script>
const frames = __FRAMES__, got = {};
for (const f of frames) {
  const i = document.createElement("iframe");
  i.width = 1280; i.height = 760; i.src = "probe.html?frame=" + f;
  document.body.appendChild(i);
}
addEventListener("message", (e) => {
  got[e.data.frame] = e.data;
  if (Object.keys(got).length === frames.length) document.getElementById("out").textContent = JSON.stringify(got);
});
</script></body></html>"""


def chrome_path() -> str | None:
    """Use an explicit browser first, then standard cross-platform installs."""
    configured = os.environ.get("DEEPTUTOR_CHROME_EXECUTABLE", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_file() else None
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
        "msedge",
    ):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ]
    for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(name)
        if root:
            candidates.extend(
                Path(root) / suffix
                for suffix in (
                    "Google/Chrome/Application/chrome.exe",
                    "Microsoft/Edge/Application/msedge.exe",
                )
            )
    return next((str(path) for path in candidates if path.is_file()), None)


def valid_scene_lengths(lengths: object, total: int) -> bool:
    """Validate bounded lengths before using sandbox output for browser sampling."""
    return (
        isinstance(lengths, list)
        and 0 < len(lengths) <= 64
        and all(type(length) is int and 0 < length <= total for length in lengths)
        and sum(lengths) == total
    )


def scene_sample_points(lengths: list[int], fps: int = 30) -> set[int]:
    """Scene starts, early frames, and last frames on the fixed player timeline."""
    starts = []
    start = 0
    for length in lengths:
        starts.append(start)
        start += length
    return {
        point
        for start, length in zip(starts, lengths)
        for point in (start, start + min(length - 1, max(1, fps // 2)), start + length - 1)
    }


def sample_frames(
    total: int, fps: int = 30, every_s: float = 4.0, *, scene_lengths: list[int] | None = None
) -> list[int]:
    """At most 48 samples, prioritizing validated scene transitions."""
    if total <= 1:
        return [0]
    chosen = {0}
    if valid_scene_lengths(scene_lengths, total):
        starts = []
        start = 0
        for length in scene_lengths:
            starts.append((start, length))
            start += length
        for points in (
            [start for start, _ in starts],
            [start + min(length - 1, max(1, fps // 2)) for start, length in starts],
            [start + length - 1 for start, length in starts],
        ):
            for point in points:
                if len(chosen) == 48:
                    break
                chosen.add(point)
    step = max(1, int(every_s * fps))
    periodic = range(max(1, step // 2), max(total - 1, 1), step)
    remaining = 48 - len(chosen)
    if remaining > 0 and periodic:
        if len(periodic) > remaining:
            indices = [
                round(i * (len(periodic) - 1) / max(1, remaining - 1)) for i in range(remaining)
            ]
            chosen.update(periodic[i] for i in indices)
        else:
            chosen.update(periodic)
    return sorted(chosen)


def check_layout(
    page: Path,
    frames: list[int],
    timeout_s: int = 180,
    *,
    require_player_frame: bool = False,
    expected_scene_lengths: list[int] | None = None,
) -> list[str] | None:
    """Collision report; ``None`` if a browser or a required frame is unavailable."""
    chrome = chrome_path()
    if not chrome or not frames:
        return None
    probe = (
        _PROBE.replace("__CAPTION_TOP__", str(CAPTION_TOP))
        .replace("__STRICT_FRAME__", "true" if require_player_frame else "false")
        .replace("__EXPECTED_SCENES__", json.dumps(expected_scene_lengths))
    )
    with tempfile.TemporaryDirectory(prefix="vl-layout-") as tmp:
        html = page.read_text(encoding="utf-8")
        Path(tmp, "probe.html").write_text(
            html.replace("</body>", probe + "</body>", 1), encoding="utf-8"
        )
        Path(tmp, "host.html").write_text(
            _HOST.replace("__FRAMES__", json.dumps(frames)), encoding="utf-8"
        )
        argv = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--allow-file-access-from-files",
            f"--user-data-dir={tmp}/profile",
            f"--virtual-time-budget={8000 + 400 * len(frames)}",
            "--dump-dom",
            f"file://{tmp}/host.html",
        ]
        try:
            # --dump-dom is UTF-8 and quotes the lesson's own text; the server's
            # ANSI code page (cp936, cp932, ...) would mangle it into bad JSON.
            proc = subprocess.run(  # nosec B603
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return None
    if proc.returncode != 0:
        return None
    m = re.search(r'<pre id="out">(.*?)</pre>', proc.stdout, re.S)
    if not m or not m.group(1).strip():
        return None
    try:
        data = json.loads(
            m.group(1)
            .replace("&quot;", '"')
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
        )
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or any(
        not isinstance(data.get(str(frame)), dict)
        or data[str(frame)].get("error")
        or not isinstance(data[str(frame)].get("issues"), list)
        or any(not isinstance(issue, str) for issue in data[str(frame)]["issues"])
        for frame in frames
    ):
        return None
    seen: dict[str, list[int]] = {}
    for frame in sorted(data, key=lambda f: int(f)):
        for issue in data[frame].get("issues") or []:
            seen.setdefault(issue, []).append(int(frame))
    issues = [
        f"at {', '.join(f'frame {f} ({f / 30:.2f}s)' for f in frames[:4])}: {issue}"
        for issue, frames in seen.items()
    ]
    return issues[:_MAX_ISSUES]
