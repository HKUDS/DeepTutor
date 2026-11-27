"""Real Wasm checks; CI enables these with DEEPTUTOR_TEST_VIDEO_SANDBOX=1."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from deeptutor.agents.video_lesson import runtime

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("DEEPTUTOR_TEST_VIDEO_SANDBOX") != "1",
        reason="requires Node and the Remotion npm runtime",
    ),
]

CONFIG = "export const LESSON = {durationInFrames:60, fps:30, width:1920, height:1080};\n"
VALID = CONFIG + 'export const Lesson = () => <div>{"A safe lesson. ".repeat(50)}</div>;'


@pytest.fixture(autouse=True)
def no_docker(monkeypatch: pytest.MonkeyPatch):
    """Every integration test must work with Docker unavailable, even on CI hosts."""
    which = runtime.shutil.which

    def without_docker(name, *args, **kwargs):
        if name in {"docker", "podman", "bwrap", "sandbox-exec"}:
            pytest.fail(f"Video lessons must not probe deployment tooling: {name}")
        return which(name, *args, **kwargs)

    monkeypatch.setattr(runtime.shutil, "which", without_docker)
    # A stray Docker invocation would also fail even on a runner with Docker installed.
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:1")


async def test_real_render_and_runtime_error(tmp_path: Path) -> None:
    lesson = runtime.prepare_workdir(tmp_path, VALID)
    result = await runtime.build_lesson(lesson, tmp_path / "player.js")
    assert result.ok and len(result.frames) == 25, result.errors
    assert (tmp_path / "player.js").stat().st_size > 0
    lesson.write_text(CONFIG + 'export const Lesson = () => {throw new Error("fixture failure")};')
    result = await runtime.build_lesson(lesson, tmp_path / "player.js")
    assert not result.ok and any("fixture failure" in error for error in result.errors)


async def test_real_kit_animation_and_captions(tmp_path: Path) -> None:
    code = (
        CONFIG
        + """
import {Sequence} from "remotion";
import {Stage, Title, Body, Narration} from "./kit";
export const Lesson = () => <Stage eyebrow="Test">
  <Sequence durationInFrames={60}>
    <Title>安全运行 · Safe rendering</Title>
    <Body x={120} y={300}>A complete lesson with animation and captions.</Body>
    <Narration lines={[{at: 0, text: "不需要 Docker"}, {at: 30, text: "Second caption"}]} />
  </Sequence>
</Stage>;
"""
    )
    lesson = runtime.prepare_workdir(tmp_path, code)
    result = await runtime.build_lesson(lesson, tmp_path / "player.js")
    assert result.ok and len(result.frames) == 25, result.errors
    assert len({frame["chars"] for frame in result.frames}) > 1


async def test_model_cannot_read_host_secrets_files_or_connect_to_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "host-secret.txt"
    marker.write_text("dummy-host-secret")
    monkeypatch.setenv("DT_REVIEW_SENTINEL", "dummy-environment-secret")
    code = """
for (const name of ["process", "require", "fetch", "XMLHttpRequest", "WebSocket", "Worker"]) {
  if (typeof globalThis[name] !== "undefined") throw new Error("host API exposed: " + name);
}
if (({}).constructor.constructor("return typeof process")() !== "undefined")
  throw new Error("constructor escaped to the host");
if (eval("typeof process") !== "undefined") throw new Error("eval escaped to the host");
export const Lesson = () => <div>{"Isolated lesson. ".repeat(50)}</div>;
"""
    lesson = runtime.prepare_workdir(tmp_path, CONFIG + code)
    result = await runtime.build_lesson(lesson, tmp_path / "player.js")
    assert result.ok, result.errors
    assert marker.read_text() == "dummy-host-secret"
    assert "dummy-host-secret" not in (tmp_path / "player.js").read_text()
    assert "dummy-environment-secret" not in (tmp_path / "player.js").read_text()


@pytest.mark.parametrize("specifier", ["node:fs", "node:child_process", "../host-secret.json"])
async def test_host_imports_are_rejected(tmp_path: Path, specifier: str) -> None:
    (tmp_path / "host-secret.json").write_text('{"secret":"dummy-host-secret"}')
    lesson = runtime.prepare_workdir(
        tmp_path / "source",
        CONFIG + f"import secret from {json.dumps(specifier)};\n"
        "export const Lesson = () => <div>{JSON.stringify(secret)}</div>;",
    )
    result = await runtime.build_lesson(lesson, tmp_path / "source" / "player.js")
    assert not result.ok and result.stage == "compile"
    assert not (tmp_path / "source" / "player.js").exists()


async def test_cancelled_render_reaps_build_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await runtime.ensure_runtime()
    original = asyncio.create_subprocess_exec
    started = asyncio.Event()
    processes = []

    async def observe(*argv, **kwargs):
        process = await original(*argv, **kwargs)
        if str(runtime.ASSETS_DIR / "build.mjs") in argv:
            processes.append(process)
            started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observe)
    lesson = runtime.prepare_workdir(
        tmp_path, CONFIG + "export const Lesson = () => { while (true) {} };"
    )
    task = asyncio.create_task(runtime.build_lesson(lesson, tmp_path / "player.js"))
    try:
        await asyncio.wait_for(started.wait(), 30)
        await asyncio.sleep(1)
        assert not task.done(), "infinite renderer should still be running"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert processes and all(p.returncode is not None for p in processes)
        assert not (tmp_path / "player.js").exists()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_timed_out_render_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "RENDER_TIMEOUT_S", 1)
    lesson = runtime.prepare_workdir(
        tmp_path, CONFIG + "export const Lesson = () => { while (true) {} };"
    )
    result = await runtime.build_lesson(lesson, tmp_path / "player.js")
    assert not result.ok and result.stage == "render"
    assert any("interrupt" in e or "timed out" in e for e in result.errors)
    assert not (tmp_path / "player.js").exists()


async def test_build_script_uses_isolation_without_container_configuration(tmp_path: Path) -> None:
    root = await runtime.ensure_runtime()
    lesson = runtime.prepare_workdir(tmp_path, VALID)
    result = await runtime._run_tool(
        [
            runtime._node(),
            str(runtime.ASSETS_DIR / "build.mjs"),
            str(lesson),
            str(tmp_path / "player.js"),
        ],
        timeout=30,
        env={"DEEPTUTOR_REMOTION_RUNTIME": str(root)},
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["ok"]
    assert (tmp_path / "player.js").exists()


@pytest.mark.parametrize("with_audio", [False, True])
async def test_narrated_scenes_with_and_without_audio(tmp_path: Path, with_audio: bool) -> None:
    code = """
import {Stage, Title, Scenes, lessonLength} from "./kit";
const scenes = [{voice: "s1", frames: 60, content: <Stage><Title>声音与字幕</Title></Stage>}];
export const LESSON = {durationInFrames:lessonLength(scenes), fps:30, width:1920, height:1080};
export const Lesson = () => <Scenes scenes={scenes} />;
"""
    clip = {"text": "声音与字幕", "frames": 45, "captions": [{"at": 0, "text": "声音与字幕"}]}
    if with_audio:
        clip["src"] = "data:audio/mpeg;base64,SUQz"
    voice = "export const VOICE = " + json.dumps({"s1": clip}) + ";"
    lesson = runtime.prepare_workdir(tmp_path, code, voice=voice)
    result = await runtime.build_lesson(lesson, tmp_path / "player.js")
    assert result.ok and len(result.frames) == 25, result.errors


async def test_memory_exhaustion_is_rejected(tmp_path: Path) -> None:
    lesson = runtime.prepare_workdir(
        tmp_path,
        CONFIG
        + "export const Lesson = () => { const a=[]; while(true) a.push(new Uint8Array(1024*1024)); };",
    )
    result = await runtime.build_lesson(lesson, tmp_path / "player.js")
    assert not result.ok and result.stage == "render"
    assert not (tmp_path / "player.js").exists()


async def test_compiler_rejects_local_file_and_symlink_imports(tmp_path: Path) -> None:
    lesson = runtime.prepare_workdir(
        tmp_path,
        CONFIG
        + 'import secret from "./secret.json"; export const Lesson = () => <div>{secret}</div>;',
    )
    (tmp_path / "secret.json").write_text('"dummy-host-secret"')
    result = await runtime.build_lesson(lesson, tmp_path / "player.js")
    assert not result.ok and result.stage == "compile"
    (tmp_path / "china_outline.json").unlink()
    try:
        (tmp_path / "china_outline.json").symlink_to(tmp_path / "secret.json")
    except OSError:
        pytest.skip("symlinks unavailable on this Windows account")
    lesson.write_text(lesson.read_text().replace("./secret.json", "./china_outline.json"))
    result = await runtime.build_lesson(lesson, tmp_path / "player.js")
    assert not result.ok and result.stage == "compile"
    assert not (tmp_path / "player.js").exists()
