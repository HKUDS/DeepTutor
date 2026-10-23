"""Real subprocess regression checks without MinerU/model downloads."""

from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from deeptutor.knowledge import indexing_run
from deeptutor.services.parsing.engines.mineru import local


def run_fixture(tmp_path, monkeypatch, code, run=None, idle=0.05, timeout=30, extra_env=None):
    source = tmp_path / "lesson.pdf"
    source.write_bytes(b"controlled fixture")
    popen = subprocess.Popen

    def spawn(cmd, **kwargs):
        output = cmd[cmd.index("-o") + 1]
        return popen([sys.executable, "-c", code, output], **kwargs)

    monkeypatch.setattr(local.subprocess, "Popen", spawn)
    monkeypatch.setattr(
        indexing_run, "current_run", lambda: run or SimpleNamespace(check=lambda: None)
    )
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
        assert not psutil.pid_exists(child), "Owned child escaped cleanup"
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
            raise indexing_run.IndexingCancelled("controlled cancellation")

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
    assert not psutil.pid_exists(int(child_file.read_text()))
