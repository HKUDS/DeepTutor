"""Real subprocess regression checks without MinerU/model downloads."""

from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from deeptutor.services.parsing import progress
from deeptutor.services.parsing.engines.mineru import local


def _await_settled(pid: int, timeout: float = 0.25) -> bool:
    """Whether an owned descendant is gone, or killed and awaiting reaping.

    The tree is SIGKILLed, so the only thing left to observe is reaping, and
    that is done by init for an orphaned grandchild. An immediate
    ``pid_exists`` check races that window: it failed 2 of 8 whole-file runs on
    40c051b7 and 5 of 8 on f7aed0744. A zombie pid is a settled tree; a
    running pid is a leak.

    The timeout only covers signal delivery, never reaping, so it must stay
    small: the fixture child lives 2s, and a window of 1s would let a missed
    kill die of old age and pass while ``elapsed`` approaches its 1.5s bound.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            status = psutil.Process(pid).status()
        except psutil.NoSuchProcess:
            return True
        if status in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def run_fixture(tmp_path, monkeypatch, code, run=None, idle=0.05, timeout=30, extra_env=None):
    source = tmp_path / "lesson.pdf"
    source.write_bytes(b"controlled fixture")
    popen = subprocess.Popen

    def spawn(cmd, **kwargs):
        if cmd[0] != sys.executable:
            return popen(cmd, **kwargs)
        output = cmd[cmd.index("-o") + 1]
        return popen([sys.executable, "-c", code, output], **kwargs)

    monkeypatch.setattr(local.subprocess, "Popen", spawn)
    monkeypatch.setattr(progress, "current_run", lambda: run or SimpleNamespace(check=lambda: None))
    monkeypatch.setattr(local, "_LOCAL_PARSE_IDLE_TIMEOUT_SECONDS", idle)
    monkeypatch.setattr(local, "_LOCAL_PARSE_TIMEOUT_SECONDS", timeout)
    monkeypatch.delenv("MINERU_TASK_RESULT_TIMEOUT_SECONDS", raising=False)
    started = time.monotonic()
    result = local.parse_document_with_mineru_result(
        source,
        tmp_path / "out",
        cli_command=sys.executable,
        extra_env=extra_env,
    )
    return result, time.monotonic() - started


def test_quiet_inference_is_not_killed_for_log_silence(tmp_path, monkeypatch):
    code = (
        "import sys,time,pathlib; time.sleep(0.7); "
        "p=pathlib.Path(sys.argv[1]); (p/'lesson.md').write_text('# parsed',encoding='utf-8')"
    )
    result, elapsed = run_fixture(tmp_path, monkeypatch, code)
    assert result.ok, result
    assert elapsed < 2


def test_explicit_client_timeout_also_bounds_parent_runtime(tmp_path, monkeypatch):
    code = (
        "import os,sys,time,pathlib; p=pathlib.Path(sys.argv[1]); "
        "(p/'deadline.txt').write_text(os.environ['MINERU_TASK_RESULT_TIMEOUT_SECONDS']); "
        "time.sleep(10)"
    )
    result, elapsed = run_fixture(
        tmp_path,
        monkeypatch,
        code,
        extra_env={"MINERU_TASK_RESULT_TIMEOUT_SECONDS": "1.2"},
    )
    assert result.reason is local.LocalParseReason.TIMEOUT
    assert "1.2 seconds" in result.detail
    assert elapsed < 2.5
    (deadline,) = (tmp_path / "out").glob(".mineru-attempt-*/output/deadline.txt")
    assert deadline.read_text() == "1.2"


def test_parent_exit_does_not_wait_for_descendant_stdout(tmp_path, monkeypatch):
    # A finite child keeps the red test bounded even with the old broken reader.
    code = (
        "import sys,subprocess,pathlib; p=pathlib.Path(sys.argv[1]); "
        "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'],"
        "stdout=sys.stdout,stderr=sys.stderr); "
        "(p/'child.pid').write_text(str(c.pid)); "
        "(p/'lesson.md').write_text('# parsed',encoding='utf-8')"
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        result, elapsed = run_fixture(tmp_path, monkeypatch, code, idle=10)
        assert result.ok, result
        assert elapsed < 1.5, "Waiting for inherited stdout instead of parent exit"
        child = int((tmp_path / "out" / "lesson" / "child.pid").read_text())
        assert _await_settled(child), "Owned child survived cleanup"
        assert unrelated.poll() is None, "Cleanup touched an unrelated process"
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


@pytest.mark.parametrize("cancelled", [False, True])
def test_deadline_and_cancellation_settle_the_owned_tree(tmp_path, monkeypatch, cancelled):
    code = (
        "import sys,subprocess,pathlib,time; p=pathlib.Path(sys.argv[1]); "
        "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)']); "
        "(p/'child.pid').write_text(str(c.pid)); time.sleep(10)"
    )

    def check():
        if cancelled and list((tmp_path / "out").glob(".mineru-attempt-*/output/child.pid")):
            raise progress.IndexingCancelled("controlled cancellation")

    result, elapsed = run_fixture(
        tmp_path,
        monkeypatch,
        code,
        run=SimpleNamespace(check=check),
        timeout=0.8,
    )
    assert result.reason is (
        local.LocalParseReason.CANCELLED if cancelled else local.LocalParseReason.TIMEOUT
    )
    assert elapsed < 2
    (child_file,) = (tmp_path / "out").glob(".mineru-attempt-*/output/child.pid")
    assert _await_settled(int(child_file.read_text()))


def test_settled_rejects_a_running_child() -> None:
    """Both answers, with real processes: a live pid is not settled.

    The cleanup assertions above only ever see the settled answer, so without
    this they would keep passing if the helper lost its running/zombie
    distinction and the original flake came back.
    """
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        assert _await_settled(child.pid, timeout=0.05) is False
        child.kill()
        # Not reaped here: an unreaped kill is the zombie the flake was about.
        assert _await_settled(child.pid) is True
    finally:
        child.kill()
        child.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_group_probe_distinguishes_live_and_unreaped_members():
    from deeptutor.services.parsing.engines.mineru._process import _process_group_alive

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    try:
        assert _process_group_alive(process.pid)
        process.kill()
        deadline = time.monotonic() + 2
        while psutil.Process(process.pid).status() != psutil.STATUS_ZOMBIE:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert not _process_group_alive(process.pid)
    finally:
        process.kill()
        process.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_permission_error_never_confirms_group_cleanup(monkeypatch):
    from deeptutor.services.parsing.engines.mineru import _process

    def denied(*_args):
        raise PermissionError

    monkeypatch.setattr(_process.os, "killpg", denied)
    assert _process._process_group_alive(12345)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_unsettled_tree_is_reported_as_cleanup_failed(tmp_path, monkeypatch):
    """A tree that never settles gets its own reason and is not published (#2426).

    The probe is patched rather than the exception: ``_process_group_alive``
    answering "still alive" is exactly what a wedged tree looks like, so this
    runs the real settle loop, its real deadline and the real handler in
    ``local.py``. Injecting ``ProcessTreeNotSettled`` from the context manager,
    as an earlier attempt did, would skip all three.

    Driving it with a real unkillable child is not practical: ``SIGKILL`` cannot
    be blocked, so a genuine process would settle in practice. The loop is
    therefore exercised here, and the "can a tree really hang" question stays
    open — stated in the PR rather than implied by a green test.
    """
    from deeptutor.services.parsing.engines.mineru import _process

    monkeypatch.setattr(_process, "_PROCESS_SETTLE_SECONDS", 0.2)
    monkeypatch.setattr(_process, "_process_group_alive", lambda _pgid: True)

    result, elapsed = run_fixture(
        tmp_path,
        monkeypatch,
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
        "(p/'lesson.md').write_text('# parsed',encoding='utf-8')",
        idle=10,
    )

    assert not result.ok
    assert result.reason is local.LocalParseReason.CLEANUP_FAILED, result.reason
    assert "ProcessTreeNotSettled" in result.detail
    # A deliberately short deadline, so the poll ends instead of waiting 5s.
    assert elapsed < 3
    # Publication is withheld: the attempt was never renamed into the visible
    # location, so a late write cannot land in a result a caller already has.
    assert not (tmp_path / "out" / "lesson").exists()
    (state_file,) = (tmp_path / "out").glob(".mineru-attempt-*/state.json")
    assert '"cleanup_failed"' in state_file.read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_other_failures_keep_reporting_exception(tmp_path, monkeypatch):
    """The new reason is narrow: an unrelated failure is still ``EXCEPTION``."""

    def boom(*_args, **_kwargs):
        raise ValueError("something else broke")

    # ``local`` binds ``cli_process`` at import, so patch it there rather than
    # in ``_process``.
    monkeypatch.setattr(local, "cli_process", boom)

    result, _ = run_fixture(tmp_path, monkeypatch, "import time; time.sleep(0.1)")

    assert not result.ok
    assert result.reason is local.LocalParseReason.EXCEPTION, result.reason


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_settled_tree_still_publishes(tmp_path, monkeypatch):
    """The normal path is untouched: a settling tree publishes and succeeds."""
    from deeptutor.services.parsing.engines.mineru import _process

    calls: list[int] = []

    def settles(pgid: int) -> bool:
        calls.append(pgid)
        return False  # First poll: already empty.

    monkeypatch.setattr(_process, "_process_group_alive", settles)

    result, elapsed = run_fixture(
        tmp_path,
        monkeypatch,
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
        "(p/'lesson.md').write_text('# parsed',encoding='utf-8')",
        idle=10,
    )

    assert result.ok, result
    assert calls, "the settle probe must be consulted even when it clears at once"
    assert (tmp_path / "out" / "lesson" / "lesson.md").read_text() == "# parsed"
    assert elapsed < 3
