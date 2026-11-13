"""Geometric layout review for a Manim scene.

The renderer proves a scene runs; it cannot see that a label sits on a curve
or a formula hangs off the frame, and vision review needs a vision model. This
replays the scene with Manim's ``dry_run`` (no frames are drawn), records where
every visible text and stroke sits after each ``play``/``wait``, and reports
collisions in scene units so the code generator can move things.

Run as ``python layout_probe.py <scene.py> <SceneName>``; prints one JSON line.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import sys
import tempfile

# Finish before the retry manager's 120 s advisory review deadline.
PROBE_TIMEOUT_S = 90
_MAX_ISSUES = 12
_SCENE_RE = re.compile(r"class\s+([A-Za-z_]\w*)\s*\(\s*[\w.]*Scene\s*\)")


def _probe(code_path: str, scene_name: str) -> dict:
    import importlib.util

    from manim import MarkupText, Paragraph, Scene, SingleStringMathTex, Text, VMobject, config
    from manim.mobject.text.numbers import DecimalNumber
    import numpy as np

    config.dry_run = True
    config.disable_caching = True
    config.verbosity = "ERROR"
    config.progress_bar = "none"

    text_types = (Text, MarkupText, Paragraph, SingleStringMathTex, DecimalNumber)
    half_w, half_h = config.frame_width / 2, config.frame_height / 2
    issues: dict[str, list[float]] = {}

    def label(m) -> str:
        s = (
            getattr(m, "original_text", None)
            or getattr(m, "tex_string", None)
            or getattr(m, "text", None)
        )
        if s is None and hasattr(m, "get_value"):
            s = f"{m.get_value():g}"
        return re.sub(r"\s+", " ", str(s or type(m).__name__))[:40]

    def visible_text(m) -> bool:
        return any(sm.get_fill_opacity() > 0.1 for sm in m.family_members_with_points())

    def curve_samples(m) -> np.ndarray:
        pts = m.points
        n = len(pts) // 4
        if n == 0:
            return np.empty((0, 3))
        c = pts[: n * 4].reshape(n, 4, 3)
        t = np.linspace(0, 1, 7)[:, None, None]
        b = (
            ((1 - t) ** 3) * c[:, 0]
            + 3 * ((1 - t) ** 2) * t * c[:, 1]
            + 3 * (1 - t) * t**2 * c[:, 2]
            + t**3 * c[:, 3]
        )
        return b.reshape(-1, 3)

    def collect(mobjects, texts, shapes):
        for m in mobjects:
            if isinstance(m, text_types):
                if visible_text(m) and len(m.get_all_points()):
                    texts.append(m)
                continue
            try:  # trackers, images and other non-vector mobjects have no stroke
                if (
                    isinstance(m, VMobject)
                    and len(m.points)
                    and m.get_stroke_opacity() > 0.1
                    and m.get_stroke_width() > 0
                ):
                    shapes.append(m)
            except (AttributeError, ValueError, IndexError):
                pass
            collect(m.submobjects, texts, shapes)

    def note(msg: str, t: float) -> None:
        issues.setdefault(msg, []).append(round(t, 1))

    def snapshot(scene) -> None:
        t = float(getattr(scene.renderer, "time", 0.0))
        frame = getattr(getattr(scene, "camera", None), "frame", None)
        cx, cy = frame.get_center()[:2] if frame is not None else (0.0, 0.0)
        fw = frame.width / 2 if frame is not None else half_w
        fh = frame.height / 2 if frame is not None else half_h
        texts, shapes = [], []
        collect(scene.mobjects, texts, shapes)
        boxes = []
        for m in texts:
            (x0, y0, _), (x1, y1, _) = m.get_corner([-1, -1, 0]), m.get_corner([1, 1, 0])
            boxes.append((m, x0, y0, x1, y1))
            if (
                x0 < cx - fw - 0.05
                or x1 > cx + fw + 0.05
                or y0 < cy - fh - 0.05
                or y1 > cy + fh + 0.05
            ):
                note(
                    f'text "{label(m)}" is cut off by the frame edge (x {x0:.1f}..{x1:.1f}, y {y0:.1f}..{y1:.1f}; '
                    f"frame is x ±{fw:.1f}, y ±{fh:.1f})",
                    t,
                )
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                w = min(a[3], b[3]) - max(a[1], b[1])
                h = min(a[4], b[4]) - max(a[2], b[2])
                if w > 0.06 and h > 0.06:
                    note(
                        f'text "{label(a[0])}" overlaps text "{label(b[0])}" near ({max(a[1], b[1]):.1f}, '
                        f"{max(a[2], b[2]):.1f})",
                        t,
                    )
        crossed: dict[str, list] = {}
        offscreen = 0
        for s in shapes:
            p = curve_samples(s)
            if not len(p):
                continue
            out = (np.abs(p[:, 0] - cx) > fw + 0.02) | (np.abs(p[:, 1] - cy) > fh + 0.02)
            offscreen += int(out.any())
            for m, x0, y0, x1, y1 in boxes:
                if s in m.get_family():
                    continue
                inside = (
                    (p[:, 0] > x0 + 0.03)
                    & (p[:, 0] < x1 - 0.03)
                    & (p[:, 1] > y0 + 0.03)
                    & (p[:, 1] < y1 - 0.03)
                )
                if int(inside.sum()) >= 2:
                    q = p[inside][0]
                    crossed.setdefault(label(m), [0, q])[0] += 1
        for name, (count, q) in crossed.items():
            note(
                f'{count} line{"s" if count > 1 else ""} cross the text "{name}" near ({q[0]:.1f}, {q[1]:.1f})',
                t,
            )
        if offscreen:
            note(
                f"{offscreen} drawn shape{'s' if offscreen > 1 else ''} run past the frame edge", t
            )

    spec = importlib.util.spec_from_file_location("probe_scene", code_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scene_cls = getattr(module, scene_name)

    orig_play, orig_wait = Scene.play, Scene.wait

    def play(self, *a, **k):
        r = orig_play(self, *a, **k)
        snapshot(self)
        return r

    def wait(self, *a, **k):
        r = orig_wait(self, *a, **k)
        snapshot(self)
        return r

    Scene.play, Scene.wait = play, wait
    scene_cls().render()
    return {
        "issues": [
            f"at {', '.join(f'{x:g}s' for x in ts[:4])}: {msg}" for msg, ts in issues.items()
        ][:_MAX_ISSUES]
    }


def scene_name_of(code: str) -> str | None:
    m = _SCENE_RE.search(code)
    return m.group(1) if m else None


async def geometry_review(code: str):
    """Layout review of a video scene; ``None`` when it could not run (never blocks the render)."""
    from deeptutor.agents.math_animator.models import VisualReviewResult

    scene = scene_name_of(code)
    if not scene:
        return None
    with tempfile.TemporaryDirectory(prefix="manim-probe-") as tmp:
        path = Path(tmp) / "scene.py"
        path.write_text(code, encoding="utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(Path(__file__).resolve()),
                str(path),
                scene,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmp,
            )
        except (OSError, NotImplementedError):
            # Windows SelectorEventLoop cannot create asyncio subprocesses.
            return None
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT_S)
        except (TimeoutError, asyncio.CancelledError) as exc:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return None
    lines = [ln for ln in stdout.decode(errors="replace").splitlines() if ln.startswith("{")]
    if proc.returncode != 0 or not lines:
        return None
    issues = json.loads(lines[-1]).get("issues") or []
    if not issues:
        return VisualReviewResult(
            passed=True, summary="Layout check: no overlaps or off-frame elements."
        )
    return VisualReviewResult(
        passed=False,
        summary=f"Layout check found {len(issues)} problem(s) (scene units, frame is about x ±7.1, y ±4): "
        + " | ".join(issues),
        issues=issues,
        suggested_fix=(
            "Move or scale the named mobjects so no text overlaps other text, no line passes through a label, "
            "and everything stays inside the frame. Use next_to(..., buff>=0.25), arrange(), to_edge(), scale(), "
            "or FadeOut earlier elements before adding new ones. Keep the rest of the animation unchanged."
        ),
    )


if __name__ == "__main__":
    print(json.dumps(_probe(sys.argv[1], sys.argv[2])))
