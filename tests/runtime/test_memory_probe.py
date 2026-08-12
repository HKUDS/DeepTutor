from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from deeptutor.runtime import memory_probe


def test_capture_always_measures_at_least_this_process() -> None:
    snapshot = memory_probe.capture()

    if not snapshot.processes:
        pytest.skip("no memory backend on this platform (no psutil, not Linux)")
    assert snapshot.total_rss_bytes > 0
    assert any(p.pid == os.getpid() for p in snapshot.processes)


def test_capture_without_supervisor_anchor_reports_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(memory_probe.SUPERVISOR_PID_ENV, raising=False)

    snapshot = memory_probe.capture()

    if not snapshot.processes:
        pytest.skip("no memory backend on this platform (no psutil, not Linux)")
    # No anchor means the walk started at this process, so the number understates
    # the tree and the UI has to say so.
    assert snapshot.partial is True


def test_supervisor_pid_ignores_dead_and_malformed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alive = {os.getpid()}

    monkeypatch.setenv(memory_probe.SUPERVISOR_PID_ENV, "not-a-pid")
    assert memory_probe._supervisor_pid(lambda pid: pid in alive) is None

    monkeypatch.setenv(memory_probe.SUPERVISOR_PID_ENV, "0")
    assert memory_probe._supervisor_pid(lambda pid: pid in alive) is None

    # A pid recycled from a previous run must not silently anchor the walk onto
    # an unrelated tree.
    monkeypatch.setenv(memory_probe.SUPERVISOR_PID_ENV, "999999")
    assert memory_probe._supervisor_pid(lambda pid: pid in alive) is None

    monkeypatch.setenv(memory_probe.SUPERVISOR_PID_ENV, str(os.getpid()))
    assert memory_probe._supervisor_pid(lambda pid: pid in alive) == os.getpid()


def test_classify_never_echoes_the_command_line() -> None:
    label = memory_probe._classify(
        pid=os.getpid() + 1,
        name="node",
        cmdline="node server.js --token sk-secret-value",
    )

    assert label == "web"
    assert "sk-secret" not in label


def test_classify_maps_roles_and_falls_back_to_the_executable_name() -> None:
    self_pid = os.getpid()
    other = self_pid + 1

    assert memory_probe._classify(self_pid, "python3.11", "uvicorn") == "backend"
    assert memory_probe._classify(other, "python", "-m uvicorn deeptutor.api.main:app") == "backend"
    assert memory_probe._classify(other, "pocketbase", "serve") == "pocketbase"
    assert memory_probe._classify(other, "bwrap", "sandbox runner") == "sandbox"
    assert memory_probe._classify(other, "mineru-worker", "") == "mineru-worker"
    assert memory_probe._classify(other, "", "") == "process"


def test_classify_names_the_tree_root_by_pid_not_by_argv() -> None:
    """The supervisor runs as a bare `deeptutor` script — argv has nothing to match."""
    root = os.getpid() + 1

    assert memory_probe._classify(root, "python3.11", "/usr/bin/deeptutor", root_pid=root) == (
        "supervisor"
    )
    # Without the anchor there is no root to name, so it falls back to the name.
    assert memory_probe._classify(root, "python3.11", "/usr/bin/deeptutor") == "python3.11"
    # This process stays "backend" even when it is also the root of the walk.
    assert memory_probe._classify(os.getpid(), "python", "", root_pid=os.getpid()) == "backend"


def test_cgroup_limit_reads_v2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "memory.max").write_text("2147483648\n", encoding="utf-8")
    (tmp_path / "memory.current").write_text("536870912\n", encoding="utf-8")
    monkeypatch.setattr(memory_probe, "_CGROUP_V2_MAX", tmp_path / "memory.max")
    monkeypatch.setattr(memory_probe, "_CGROUP_V2_CURRENT", tmp_path / "memory.current")

    assert memory_probe._cgroup_limit() == (2147483648, 536870912)


def test_cgroup_limit_treats_unlimited_as_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # cgroup v2 writes the literal word; v1 writes a near-max sentinel.
    (tmp_path / "memory.max").write_text("max\n", encoding="utf-8")
    (tmp_path / "limit_in_bytes").write_text(f"{1 << 63}\n", encoding="utf-8")
    monkeypatch.setattr(memory_probe, "_CGROUP_V2_MAX", tmp_path / "memory.max")
    monkeypatch.setattr(memory_probe, "_CGROUP_V2_CURRENT", tmp_path / "missing")
    monkeypatch.setattr(memory_probe, "_CGROUP_V1_LIMIT", tmp_path / "limit_in_bytes")
    monkeypatch.setattr(memory_probe, "_CGROUP_V1_USAGE", tmp_path / "missing")

    assert memory_probe._cgroup_limit() is None


def test_container_limit_wins_over_host_ram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inside a container the host's RAM is the wrong denominator."""
    monkeypatch.setattr(memory_probe, "_cgroup_limit", lambda: (4 * 1024**3, 1024**3))
    monkeypatch.setattr(memory_probe, "_host_memory", lambda _psutil: (64 * 1024**3, 32 * 1024**3))

    snapshot = memory_probe.capture()

    assert snapshot.limit_source == "cgroup"
    assert snapshot.limit_bytes == 4 * 1024**3
    assert snapshot.available_bytes == 3 * 1024**3


def test_host_ram_used_when_cgroup_limit_exceeds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An uncapped cgroup often reports a limit larger than physical RAM."""
    monkeypatch.setattr(memory_probe, "_cgroup_limit", lambda: (128 * 1024**3, 1024**3))
    monkeypatch.setattr(memory_probe, "_host_memory", lambda _psutil: (16 * 1024**3, 8 * 1024**3))

    snapshot = memory_probe.capture()

    assert snapshot.limit_source == "host"
    assert snapshot.limit_bytes == 16 * 1024**3


def test_usage_ratio_is_none_without_a_denominator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_probe, "_cgroup_limit", lambda: None)
    monkeypatch.setattr(memory_probe, "_host_memory", lambda _psutil: (None, None))

    snapshot = memory_probe.capture()

    assert snapshot.limit_source == "unknown"
    assert snapshot.usage_ratio is None


def test_capture_falls_back_to_proc_without_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("the /proc fallback only applies to Linux")
    monkeypatch.setattr(memory_probe, "_load_psutil", lambda: None)

    snapshot = memory_probe.capture()

    assert snapshot.total_rss_bytes > 0
    assert any(p.pid == os.getpid() for p in snapshot.processes)


def test_capture_is_empty_when_no_backend_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_probe, "_load_psutil", lambda: None)
    monkeypatch.setattr(memory_probe.sys, "platform", "darwin")

    snapshot = memory_probe.capture()

    assert snapshot.processes == ()
    assert snapshot.total_rss_bytes == 0
