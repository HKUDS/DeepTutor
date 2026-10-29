"""Remotion runtime for video lessons: install once, compile per lesson, wrap in a page.

The model writes ``Lesson.tsx`` against the shipped kit (``remotion/kit.tsx``).
``build.mjs`` compiles it with esbuild, renders sample frames in a
WebAssembly JavaScript sandbox, and bundles it with ``@remotion/player``.
The page this module writes is self-contained: the learner's browser plays the
composition live, so no video file is ever encoded on the server.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from html import escape
import json
import os
from pathlib import Path
import shutil

from deeptutor.services.path_service import get_path_service
from deeptutor.services.sandbox.backends import RestrictedSubprocessBackend
from deeptutor.services.sandbox.spec import ExecRequest, ExecResult, ResourceLimits

ASSETS_DIR = Path(__file__).resolve().parent / "remotion"
KIT_FILES = ("kit.tsx", "china_outline.json", "voice.ts")
BUILD_TIMEOUT_S = 600
INSTALL_TIMEOUT_S = 900
RENDER_TIMEOUT_S = 180

_install_lock = asyncio.Lock()


class VideoLessonRuntimeError(RuntimeError):
    """The Node toolchain for video lessons is missing or could not be installed."""


@dataclass
class BuildResult:
    ok: bool
    stage: str
    errors: list[str] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)


def runtime_dir() -> Path:
    """Where the npm packages live; ``DEEPTUTOR_REMOTION_RUNTIME`` overrides the default."""
    override = os.environ.get("DEEPTUTOR_REMOTION_RUNTIME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return get_path_service().get_runtime_state_dir() / "remotion"


def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise VideoLessonRuntimeError(
            "Video lessons need Node.js 22+ on the server (the `node` command was not found)."
        )
    return node


def _installed(root: Path) -> bool:
    manifest = json.loads((ASSETS_DIR / "package.json").read_text(encoding="utf-8"))
    for name, version in manifest["dependencies"].items():
        pkg = root / "node_modules" / name / "package.json"
        if not pkg.is_file():
            return False
        if json.loads(pkg.read_text(encoding="utf-8")).get("version") != version:
            return False
    return True


async def _run_tool(
    argv: list[str], *, timeout: int, cwd: Path | None = None, env: dict[str, str] | None = None
) -> ExecResult:
    """Run trusted tooling with bounded output and cancellation of its process tree.

    Model code runs inside WebAssembly, never in the host JavaScript context.
    This subprocess owns the trusted compiler and the Wasm interpreter.
    """
    return await RestrictedSubprocessBackend(inherit_virtualenv=False).exec(
        ExecRequest.of_argv(
            argv,
            workdir=str(cwd) if cwd else "",
            env=env or {},
            limits=ResourceLimits(timeout_s=timeout, max_output_chars=64_000),
        )
    )


def _require_success(result: ExecResult, action: str) -> None:
    if not result.ok or result.exit_code != 0:
        detail = result.error or result.stderr or result.stdout
        if result.timed_out:
            detail = "timed out"
        raise VideoLessonRuntimeError(f"{action} failed: {detail[-1500:]}")


async def ensure_runtime() -> Path:
    """Prepare pinned tooling and the isolated renderer; never fall back to host execution."""
    _node()
    root = runtime_dir()
    async with _install_lock:
        if not _installed(root):
            npm = shutil.which("npm")
            if not npm:
                raise VideoLessonRuntimeError("Video lessons need npm to install Remotion.")
            root.mkdir(parents=True, exist_ok=True)
            for name in ("package.json", "package-lock.json"):
                shutil.copy(ASSETS_DIR / name, root / name)
            result = await _run_tool(
                [npm, "ci", "--no-audit", "--no-fund", "--omit=dev"],
                timeout=INSTALL_TIMEOUT_S,
                cwd=root,
            )
            _require_success(result, "Installing Remotion")
            if not _installed(root):
                raise VideoLessonRuntimeError(
                    "Installed Remotion packages do not match the manifest."
                )
    return root


def prepare_workdir(work_dir: Path, code: str, voice: str | None = None) -> Path:
    """Write the lesson next to a fresh copy of the kit and return the lesson path.

    ``voice`` is the generated ``voice.ts`` module; without it the kit's empty default is used.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    for name in KIT_FILES:
        shutil.copy(ASSETS_DIR / name, work_dir / name)
    if voice is not None:
        (work_dir / "voice.ts").write_text(voice, encoding="utf-8")
    lesson = work_dir / "Lesson.tsx"
    lesson.write_text(code, encoding="utf-8")
    return lesson


async def build_lesson(lesson: Path, bundle: Path) -> BuildResult:
    """Compile the lesson and validate it through the deployment-independent JS sandbox."""
    root = await ensure_runtime()
    result = await _run_tool(
        [_node(), str(ASSETS_DIR / "build.mjs"), str(lesson), str(bundle)],
        timeout=BUILD_TIMEOUT_S,
        env={
            "DEEPTUTOR_REMOTION_RUNTIME": str(root),
            "DEEPTUTOR_RENDER_TIMEOUT_MS": str(RENDER_TIMEOUT_S * 1000),
        },
    )
    if result.timed_out:
        return BuildResult(False, "timeout", [f"build did not finish within {BUILD_TIMEOUT_S}s"])
    lines = result.stdout.strip().splitlines()
    try:
        data = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        return BuildResult(False, "build", [(result.error or result.stderr or "no output")[-1500:]])
    return BuildResult(
        ok=bool(data.get("ok")) and result.ok and result.exit_code == 0,
        stage=str(data.get("stage", "")),
        errors=[str(e) for e in data.get("errors") or []],
        frames=list(data.get("frames") or []),
    )


PAGE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&family=Lora:ital,wght@0,400;0,500;0,600;1,500&display=swap" rel="stylesheet">
<style>
* {{ box-sizing: border-box }}
html, body {{ margin: 0; background: #fdfcf9 }}
#player {{ width: 100%; max-width: 1280px; margin: 0 auto }}
</style>
</head>
<body>
<div id="player"></div>
<script>{bundle}</script>
</body>
</html>
"""


def write_page(bundle: Path, page: Path, *, title: str, language: str) -> Path:
    script = bundle.read_text(encoding="utf-8").replace("</script", "<\\/script")
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        PAGE.format(
            lang="zh-CN" if language.startswith("zh") else "en", title=escape(title), bundle=script
        ),
        encoding="utf-8",
    )
    return page


__all__ = [
    "BuildResult",
    "VideoLessonRuntimeError",
    "build_lesson",
    "ensure_runtime",
    "prepare_workdir",
    "runtime_dir",
    "write_page",
]
