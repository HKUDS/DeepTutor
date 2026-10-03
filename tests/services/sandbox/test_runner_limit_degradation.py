"""A rlimit the runner cannot apply must be visible, not swallowed.

``_apply`` runs as ``preexec_fn`` in the forked child, where logging is
unsafe (the issue behind the MEDIUM finding): a failure travels back over a
pipe to the parent instead. The parent marks the response with a
``limits_degraded`` field and prints one warning line to the runner log.
The command itself still executes — this observes the limits, it does not
change execution semantics.
"""

from __future__ import annotations

import os
import time

import pytest

from deeptutor.services.sandbox.runner import server as runner_server

pytestmark = pytest.mark.skipif(
    runner_server.resource is None or not runner_server._POSIX,
    reason="POSIX rlimits only",
)


def _open_fds() -> set[int]:
    """Snapshot this process's open descriptors (fstat adds none of its own)."""
    fds: set[int] = set()
    for fd in range(1024):
        try:
            os.fstat(fd)
        except OSError:
            continue
        fds.add(fd)
    return fds


def test_no_degradation_field_when_limits_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Not the real setrlimit: whether a host can apply RLIMIT_AS varies
    # (macOS, for one, refuses some values), and this test pins the contract
    # "every limit applied -> response unchanged", not the host's rlimits.
    monkeypatch.setattr(runner_server.resource, "setrlimit", lambda _w, _l: None)

    result = runner_server.execute({"command": "echo hi", "limits": {"timeout_s": 10}})

    assert result["error"] == ""
    assert result["stdout"].strip() == "hi"
    assert "limits_degraded" not in result


@pytest.mark.parametrize(
    "raised",
    [ValueError("negative limit"), OSError(1, "Operation not permitted")],
    ids=["value-error", "os-error"],
)
def test_failed_setrlimit_surfaces_in_response_and_log(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raised: Exception,
) -> None:
    def _refuse(_which: object, _limits: object) -> None:
        raise raised

    monkeypatch.setattr(runner_server.resource, "setrlimit", _refuse)

    result = runner_server.execute({"command": "echo hi", "limits": {"timeout_s": 10}})

    # Execution semantics are unchanged: the command still ran.
    assert result["error"] == ""
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "hi"
    # The guard's failure is now visible where it used to vanish.
    degraded = result["limits_degraded"]
    for limit in ("as", "cpu", "nofile"):
        assert limit in degraded
    log = capsys.readouterr().out
    assert "WARNING" in log
    assert "as" in log


def test_timeout_response_also_reports_degraded_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _refuse(_which: object, _limits: object) -> None:
        raise ValueError("negative limit")

    monkeypatch.setattr(runner_server.resource, "setrlimit", _refuse)

    result = runner_server.execute({"command": "sleep 5", "limits": {"timeout_s": 1}})

    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert "as" in result["limits_degraded"]


def test_background_process_returns_promptly_without_pipe_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: pass_fds on the report pipe cleared FD_CLOEXEC, so any
    # background process the command spawned inherited the write end and
    # execute() blocked on the drain read until that process exited. With
    # CLOEXEC kept, the pipe must stay inside the (direct) child only.
    monkeypatch.setattr(runner_server.resource, "setrlimit", lambda _w, _l: None)

    before = _open_fds()
    start = time.monotonic()
    result = runner_server.execute(
        {"command": "sleep 2 >/dev/null 2>&1 &", "limits": {"timeout_s": 10}}
    )
    elapsed = time.monotonic() - start

    assert result["error"] == ""
    assert result["exit_code"] == 0
    assert "limits_degraded" not in result
    # Must not wait out the 2s background sleep (the regression blocked for
    # its full duration); margin is generous for a slow spawn, still < 2s.
    assert elapsed < 1.5
    # Neither pipe end may outlive the call.
    assert not (_open_fds() - before)


def test_pipe_ends_released_when_execution_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The finally backstop in execute(): an exception that is neither
    # TimeoutExpired nor (OSError, ValueError) — e.g. KeyboardInterrupt or
    # cancellation — must still close both pipe ends instead of leaking them.
    def _interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner_server.subprocess, "run", _interrupt)
    monkeypatch.setattr(runner_server.resource, "setrlimit", lambda _w, _l: None)

    before = _open_fds()
    with pytest.raises(KeyboardInterrupt):
        runner_server.execute({"command": "echo hi", "limits": {"timeout_s": 10}})

    assert not (_open_fds() - before)
