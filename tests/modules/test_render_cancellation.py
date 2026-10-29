"""Cancellation cleans up a real render subprocess without requiring Manim."""

import asyncio
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("group_exists", [False, True])
def test_cleanup_rechecks_group_after_permission_race(monkeypatch, group_exists):
    from deeptutor.runtime import process

    calls = []

    def killpg(pid, signal):
        calls.append((pid, signal))
        if group_exists or len(calls) == 1:
            raise PermissionError("group changed during signal")
        raise ProcessLookupError("group already reaped")

    monkeypatch.setattr(process, "os", SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(process.time, "sleep", lambda _: None)
    if group_exists:
        with pytest.raises(PermissionError):
            process.kill_process_tree(12345)
    else:
        process.kill_process_tree(12345)
    assert len(calls) == (5 if group_exists else 2)
    assert all(call == (12345, process.signal.SIGKILL) for call in calls)


@pytest.mark.parametrize("returncode", [0, 128])
def test_windows_cleanup_targets_the_entire_owned_tree(monkeypatch, returncode):
    from deeptutor.runtime import process

    calls = []
    monkeypatch.setattr(process, "os", SimpleNamespace(name="nt"))

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(process.subprocess, "run", run)
    process.kill_process_tree(12345)
    assert calls[0][0] == ["taskkill", "/PID", "12345", "/T", "/F"]
    assert calls[0][1]["timeout"] == 10


@pytest.mark.asyncio
async def test_cancel_reaps_render_process(tmp_path, monkeypatch):
    from deeptutor.agents.math_animator import renderer

    real_popen = subprocess.Popen
    processes = []

    def spawn(_argv, **kwargs):
        process = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(renderer.subprocess, "Popen", spawn)
    service = renderer.ManimRenderService("cancel", output_dir=tmp_path, workspace_root=tmp_path)
    source = tmp_path / "scene.py"
    source.write_text("class Fixture(Scene): pass")
    task = asyncio.create_task(
        service._run_manim(
            code_path=source, scene_name="Fixture", quality="low", save_last_frame=False
        )
    )
    async with asyncio.timeout(3):
        while not processes:
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert processes[0].poll() is not None
