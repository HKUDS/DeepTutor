"""The shipped Remotion runtime assets and the player page."""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.agents.video_lesson.runtime import ASSETS_DIR, KIT_FILES, prepare_workdir, write_page


def test_shipped_runtime_assets_exist() -> None:
    for name in (
        *KIT_FILES,
        "build.mjs",
        "render-platform.ts",
        "package.json",
        "package-lock.json",
    ):
        assert (ASSETS_DIR / name).is_file(), name
    deps = json.loads((ASSETS_DIR / "package.json").read_text(encoding="utf-8"))["dependencies"]
    # Pinned exactly: a lesson that compiled once must compile the same way later.
    assert all(v[0].isdigit() for v in deps.values())


def test_prepare_workdir_copies_the_kit(tmp_path: Path) -> None:
    lesson = prepare_workdir(tmp_path / "source", "export const x = 1;")
    assert lesson.read_text(encoding="utf-8") == "export const x = 1;"
    for name in KIT_FILES:
        assert (tmp_path / "source" / name).is_file()


def test_write_page_inlines_the_bundle_safely(tmp_path: Path) -> None:
    bundle = tmp_path / "player.js"
    bundle.write_text('console.log("</script><b>x</b>");', encoding="utf-8")
    page = write_page(bundle, tmp_path / "out" / "lesson.html", title="a < b", language="zh")
    html = page.read_text(encoding="utf-8")
    assert html.count("</script>") == 1
    assert "<\/script><b>x</b>" in html
    assert "<title>a &lt; b</title>" in html
    assert 'lang="zh-CN"' in html


def test_prepare_workdir_writes_the_voice_module(tmp_path: Path) -> None:
    prepare_workdir(tmp_path / "source", "", voice="export const VOICE = {s1: {}};")
    assert "s1" in (tmp_path / "source" / "voice.ts").read_text(encoding="utf-8")


def test_video_lesson_available_without_docker(monkeypatch) -> None:
    from types import SimpleNamespace

    from deeptutor.app.facade import DeepTutorApp

    monkeypatch.setattr(
        "deeptutor.modules.catalog.shutil.which",
        lambda name: name if name in {"node", "npm"} else None,
    )
    app = SimpleNamespace(resolve_capability=lambda value: value)
    availability = DeepTutorApp.get_capability_availability(app, "video_lesson")
    assert availability.available
    assert not availability.install_hint
