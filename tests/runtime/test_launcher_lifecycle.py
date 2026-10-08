"""Lifecycle edge cases for ``deeptutor.runtime.launcher``.

Covers the tree-termination path (``_terminate`` / ``_send_tree_signal``),
port-listener cleanup (``_kill_port_listeners``) and marker-file corruption
tolerance for the packaged-web cache, the source production build and the
detached-runtime state. Every child process is mocked — no real service is
started and no product code is changed.
"""

from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
from typing import Any

import pytest

from deeptutor.runtime import launcher


class _FakeProcess:
    """Minimal ``subprocess.Popen`` stand-in for lifecycle calls."""

    def __init__(
        self,
        pid: int,
        *,
        returncode: int | None = None,
        wait_error: Exception | None = None,
    ) -> None:
        self.pid = pid
        self._returncode = returncode
        self._wait_error = wait_error

    def poll(self) -> int | None:
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        if self._wait_error is not None:
            raise self._wait_error
        return 0 if self._returncode is None else self._returncode


def _managed(pid: int, pgid: int | None = 4242, **kwargs: Any) -> launcher.ManagedProcess:
    return launcher.ManagedProcess(name="backend", process=_FakeProcess(pid, **kwargs), pgid=pgid)


class _SignalRecorder:
    """Records ``(pid, pgid, sig)`` calls aimed at ``_send_tree_signal``."""

    def __init__(self) -> None:
        self.calls: list[tuple[int | None, int | None, signal.Signals | int]] = []

    def __call__(self, pid: int | None, pgid: int | None, sig: Any) -> None:
        self.calls.append((pid, pgid, sig))

    @property
    def pids(self) -> list[int | None]:
        return [pid for pid, _pgid, _sig in self.calls]


class _FastClock:
    """``time`` stand-in whose ``monotonic`` outpaces every wait deadline."""

    def __init__(self) -> None:
        self._now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        self._now += 4.0
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


@pytest.fixture()
def fast_clock(monkeypatch: pytest.MonkeyPatch) -> _FastClock:
    clock = _FastClock()
    monkeypatch.setattr(launcher.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(launcher.time, "sleep", clock.sleep)
    return clock


# --------------------------------------------------------------------------
# _send_tree_signal — the process-group termination primitive
# --------------------------------------------------------------------------


def test_send_tree_signal_uses_process_group_when_known(monkeypatch) -> None:
    killpg_calls: list[tuple[int, signal.Signals]] = []
    kill_calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(launcher.os, "name", "posix")
    monkeypatch.setattr(launcher.os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)))
    monkeypatch.setattr(launcher.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))

    launcher._send_tree_signal(4242, 4242, signal.SIGTERM)

    assert killpg_calls == [(4242, signal.SIGTERM)]
    assert kill_calls == []


def test_send_tree_signal_falls_back_to_single_pid_without_pgid(monkeypatch) -> None:
    killpg_calls: list[tuple[int, signal.Signals]] = []
    kill_calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(launcher.os, "name", "posix")
    monkeypatch.setattr(launcher.os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)))
    monkeypatch.setattr(launcher.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))

    launcher._send_tree_signal(4242, None, signal.SIGTERM)

    assert kill_calls == [(4242, signal.SIGTERM)]
    assert killpg_calls == []


def test_send_tree_signal_ignores_missing_pid(monkeypatch) -> None:
    kill_calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(launcher.os, "name", "posix")
    monkeypatch.setattr(launcher.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))

    launcher._send_tree_signal(None, None, signal.SIGTERM)

    assert kill_calls == []


def test_send_tree_signal_windows_uses_taskkill_with_force_only_on_kill(
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.os, "name", "nt")
    monkeypatch.setattr(launcher.subprocess, "CREATE_NO_WINDOW", 0x0, raising=False)
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    launcher._send_tree_signal(4242, None, signal.SIGTERM)
    launcher._send_tree_signal(4242, None, launcher.KILL_SIGNAL)

    assert commands[0] == ["taskkill", "/PID", "4242", "/T"]
    assert commands[1] == ["taskkill", "/PID", "4242", "/T", "/F"]


# --------------------------------------------------------------------------
# _terminate — SIGTERM, wait, then escalate to KILL
# --------------------------------------------------------------------------


def test_terminate_skips_none_and_already_finished_processes(monkeypatch) -> None:
    signals = _SignalRecorder()
    monkeypatch.setattr(launcher, "_send_tree_signal", signals)
    monkeypatch.setattr(launcher, "_log", lambda _message: None)

    launcher._terminate(None)
    launcher._terminate(_managed(4242, returncode=0))

    assert signals.calls == []


def test_terminate_sends_sigterm_to_the_process_group(monkeypatch) -> None:
    signals = _SignalRecorder()
    monkeypatch.setattr(launcher, "_send_tree_signal", signals)
    monkeypatch.setattr(launcher, "_log", lambda _message: None)

    launcher._terminate(_managed(4242))

    assert signals.calls == [(4242, 4242, signal.SIGTERM)]


def test_terminate_escalates_to_kill_when_sigterm_times_out(monkeypatch) -> None:
    signals = _SignalRecorder()
    monkeypatch.setattr(launcher, "_send_tree_signal", signals)
    monkeypatch.setattr(launcher, "_log", lambda _message: None)
    proc = _managed(4242, wait_error=subprocess.TimeoutExpired(cmd="uvicorn", timeout=8))

    launcher._terminate(proc)

    assert signals.calls == [
        (4242, 4242, signal.SIGTERM),
        (4242, 4242, launcher.KILL_SIGNAL),
    ]


def test_terminate_swallows_signal_errors_and_still_reaps(monkeypatch) -> None:
    waited: list[float] = []

    def failing_signal(_pid, _pgid, _sig) -> None:
        raise OSError("signal delivery failed")

    class _ReapingProcess(_FakeProcess):
        def wait(self, timeout: float | None = None) -> int:
            waited.append(timeout or 0.0)
            return 0

    proc = launcher.ManagedProcess(
        name="backend",
        process=_ReapingProcess(4242),
        pgid=4242,
    )
    monkeypatch.setattr(launcher, "_send_tree_signal", failing_signal)
    monkeypatch.setattr(launcher, "_log", lambda _message: None)

    launcher._terminate(proc)

    assert waited == [8]


# --------------------------------------------------------------------------
# _kill_port_listeners — SIGTERM, wait for the port, escalate to KILL
# --------------------------------------------------------------------------


def test_guarded_reclaim_does_not_signal_a_replaced_process(monkeypatch, fast_clock) -> None:
    """#1795: revalidate ownership before both TERM and KILL, not just once."""
    owned = {"current": True}
    signals = []

    def signal_target(pid, pgid, sig):
        signals.append(sig)
        owned["current"] = False

    monkeypatch.setattr(launcher, "_send_tree_signal", signal_target)
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda _port: True)
    launcher._kill_port_listeners(
        {8000: [(4242, "old backend")]},
        listener_guard=lambda _port, _pid: owned["current"],
    )
    assert signals == [signal.SIGTERM]


def test_kill_port_listeners_sigterm_frees_the_port(monkeypatch, fast_clock) -> None:
    occupied = {8000}
    signals = _SignalRecorder()
    logs: list[str] = []

    def fake_signal(pid, _pgid, _sig) -> None:
        signals(pid, None, _sig)
        occupied.discard(8000)

    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(launcher, "_send_tree_signal", fake_signal)
    monkeypatch.setattr(launcher, "_log", logs.append)

    launcher._kill_port_listeners({8000: [(1234, "python uvicorn")]})

    assert signals.calls == [(1234, None, signal.SIGTERM)]
    assert logs and "8000" in " ".join(logs)


def test_kill_port_listeners_escalates_to_kill_when_port_stays_busy(
    monkeypatch,
    fast_clock,
) -> None:
    occupied = {8000}
    signals = _SignalRecorder()
    logs: list[str] = []

    def fake_signal(pid, _pgid, sig) -> None:
        signals(pid, None, sig)
        if sig == launcher.KILL_SIGNAL:
            occupied.discard(8000)

    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(launcher, "_send_tree_signal", fake_signal)
    monkeypatch.setattr(launcher, "_log", logs.append)

    launcher._kill_port_listeners({8000: [(1234, "python uvicorn")]})

    assert signals.calls == [
        (1234, None, signal.SIGTERM),
        (1234, None, launcher.KILL_SIGNAL),
    ]
    assert "8000" in " ".join(logs)


def test_kill_port_listeners_reports_failure_when_port_never_frees(
    monkeypatch,
    fast_clock,
) -> None:
    signals = _SignalRecorder()
    logs: list[str] = []

    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda _port: True)
    monkeypatch.setattr(launcher, "_send_tree_signal", signals)
    monkeypatch.setattr(launcher, "_log", logs.append)

    launcher._kill_port_listeners({8000: [(1234, "python uvicorn"), (1235, "node server.js")]})

    assert signals.pids == [1234, 1235, 1234, 1235]
    assert signal.SIGTERM in {sig for _pid, _pgid, sig in signals.calls}
    assert launcher.KILL_SIGNAL in {sig for _pid, _pgid, sig in signals.calls}
    joined = " ".join(logs)
    assert "8000" in joined and "1234" in joined


def test_kill_port_listeners_tolerates_signal_errors(monkeypatch, fast_clock) -> None:
    occupied = {8000}
    attempts: list[int] = []

    def failing_signal(_pid, _pgid, _sig) -> None:
        attempts.append(1)
        raise OSError("no such process")

    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(launcher, "_send_tree_signal", failing_signal)
    monkeypatch.setattr(launcher, "_log", lambda _message: None)

    launcher._kill_port_listeners({8000: [(1234, "python uvicorn")]})

    assert len(attempts) >= 2  # SIGTERM attempt and KILL escalation both ran


# --------------------------------------------------------------------------
# marker-file corruption tolerance — packaged web cache
# --------------------------------------------------------------------------


def _make_packaged(packaged: Path) -> None:
    (packaged / ".next" / "sub").mkdir(parents=True, exist_ok=True)
    (packaged / "server.js").write_text(
        "start(__NEXT_PUBLIC_API_BASE_PLACEHOLDER__)", encoding="utf-8"
    )
    (packaged / ".next" / "sub" / "chunk.js").write_text(
        "auth=__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__;", encoding="utf-8"
    )


def test_packaged_web_cache_rebuilds_when_marker_is_corrupt(tmp_path: Path) -> None:
    packaged = tmp_path / "pkg"
    _make_packaged(packaged)

    home = tmp_path / "home"
    cache = home / launcher.WEB_CACHE_DIR
    cache.mkdir(parents=True)
    (cache / "server.js").write_text("stale build", encoding="utf-8")
    (cache / "orphan.txt").write_text("stale orphan", encoding="utf-8")
    marker = cache / ".deeptutor-web-runtime.json"
    marker.write_text("{not valid json", encoding="utf-8")

    result = launcher._copy_packaged_web_if_needed(
        packaged,
        home=home,
        api_base="http://127.0.0.1:8001",
        auth_enabled=True,
    )

    assert result == cache
    server_js = (cache / "server.js").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8001" in server_js
    assert "__NEXT_PUBLIC_API_BASE_PLACEHOLDER__" not in server_js
    chunk = (cache / ".next" / "sub" / "chunk.js").read_text(encoding="utf-8")
    assert "auth=true;" in chunk
    assert not (cache / "orphan.txt").exists()  # cache was rebuilt, not patched in place
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["api_base"] == "http://127.0.0.1:8001"
    assert payload["auth_enabled"] is True
    assert payload["source"] == str(packaged)


def test_packaged_web_cache_hit_with_valid_marker_skips_rebuild(tmp_path: Path) -> None:
    packaged = tmp_path / "pkg"
    packaged.mkdir()
    (packaged / "server.js").write_text("server", encoding="utf-8")
    home = tmp_path / "home"
    kwargs: dict[str, Any] = {
        "home": home,
        "api_base": "http://127.0.0.1:8001",
        "auth_enabled": False,
    }

    first = launcher._copy_packaged_web_if_needed(packaged, **kwargs)
    (first / "sentinel.txt").write_text("local file", encoding="utf-8")
    second = launcher._copy_packaged_web_if_needed(packaged, **kwargs)

    assert second == first
    assert (first / "sentinel.txt").read_text(encoding="utf-8") == "local file"


# --------------------------------------------------------------------------
# marker-file corruption tolerance — source production build
# --------------------------------------------------------------------------


def test_source_production_build_rebuilds_when_marker_is_corrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "web"
    source.mkdir()
    (source / "package.json").write_text('{"scripts":{"build":"next build"}}', encoding="utf-8")
    next_env = source / "next-env.d.ts"
    next_env.write_text("// developer dist types\n", encoding="utf-8")
    (source / "app").mkdir()
    (source / "app" / "page.tsx").write_text(
        "export default function Page() { return null; }", encoding="utf-8"
    )

    dist = source / launcher.SOURCE_PRODUCTION_DIST_DIR
    (dist / "standalone").mkdir(parents=True)
    (dist / "BUILD_ID").write_text("build-1", encoding="utf-8")
    (dist / "standalone" / "server.js").write_text("", encoding="utf-8")
    marker = dist / launcher.SOURCE_BUILD_MARKER
    marker.write_text("][ corrupted", encoding="utf-8")

    builds: list[list[str]] = []

    def _run(command, cwd, env, **_kwargs):
        builds.append(list(command))
        next_env.write_text("// production dist types\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.subprocess, "run", _run)
    kwargs: dict[str, Any] = {
        "api_base": "http://127.0.0.1:8001",
        "auth_enabled": False,
    }

    launcher._ensure_source_production_build(source, "npm", **kwargs)
    assert builds == [["npm", "run", "build"]]
    assert next_env.read_text(encoding="utf-8") == "// developer dist types\n"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert set(payload) == {"fingerprint"}

    launcher._ensure_source_production_build(source, "npm", **kwargs)
    assert builds == [["npm", "run", "build"]]  # fresh marker reuses the build


# --------------------------------------------------------------------------
# detached-runtime state — corrupt files and foreign tokens
# --------------------------------------------------------------------------


def test_read_detached_state_rejects_corrupt_and_non_object_payloads(tmp_path: Path) -> None:
    paths = launcher._detached_launcher_paths(tmp_path)

    assert launcher._read_detached_state(paths) is None  # missing file

    paths.state.parent.mkdir(parents=True, exist_ok=True)
    paths.state.write_text("{not json", encoding="utf-8")
    assert launcher._read_detached_state(paths) is None

    paths.state.write_text('["not", "an", "object"]', encoding="utf-8")
    assert launcher._read_detached_state(paths) is None

    paths.state.write_text('{"token": "t", "pid": 1}', encoding="utf-8")
    assert launcher._read_detached_state(paths) == {"token": "t", "pid": 1}


def test_clear_detached_runtime_keeps_files_from_a_foreign_token(tmp_path: Path) -> None:
    paths = launcher._detached_launcher_paths(tmp_path)
    launcher._write_detached_state(paths, {"token": "other-launch", "pid": 4242})
    paths.stop.write_text("other-launch", encoding="utf-8")

    launcher._clear_detached_runtime(paths, "launch-token")

    assert paths.state.exists()
    assert paths.stop.exists()


def test_clear_detached_runtime_removes_matching_state_and_stop(tmp_path: Path) -> None:
    paths = launcher._detached_launcher_paths(tmp_path)
    launcher._write_detached_state(paths, {"token": "launch-token", "pid": 4242})
    paths.stop.write_text("launch-token\n", encoding="utf-8")

    launcher._clear_detached_runtime(paths, "launch-token")

    assert not paths.state.exists()
    assert not paths.stop.exists()


def test_clear_detached_runtime_still_clears_stop_marker_of_own_token(
    tmp_path: Path,
) -> None:
    paths = launcher._detached_launcher_paths(tmp_path)
    launcher._write_detached_state(paths, {"token": "other-launch", "pid": 4242})
    paths.stop.write_text("launch-token", encoding="utf-8")

    launcher._clear_detached_runtime(paths, "launch-token")

    assert paths.state.exists()  # state belongs to the other launcher run
    assert not paths.stop.exists()  # but this run's stop request is consumed
