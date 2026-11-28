"""``ConfigTestRunner`` lookups must not raise for an unknown run id.

Runs live in memory only. A restart, or a Settings page that reconnects with an
id from an earlier process, asks for a run the runner no longer has; that is a
normal outcome, not a crash.
"""

from __future__ import annotations

import pytest

from deeptutor.services.config import test_runner as test_runner_module
from deeptutor.services.config.test_runner import ConfigTestRunner


class _NoThread:
    """Keep ``start`` from launching the real probing thread."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> ConfigTestRunner:
    monkeypatch.setattr(test_runner_module.threading, "Thread", _NoThread)
    return ConfigTestRunner()


def test_get_unknown_run_returns_none(runner: ConfigTestRunner) -> None:
    assert runner.get("llm-never-started") is None


def test_get_started_run_returns_it(runner: ConfigTestRunner) -> None:
    run = runner.start("llm", catalog={})

    assert runner.get(run.id) is run


def test_cancel_unknown_run_reports_false(runner: ConfigTestRunner) -> None:
    assert runner.cancel("llm-never-started") is False


def test_cancel_known_run_sets_flag_and_reports_true(runner: ConfigTestRunner) -> None:
    run = runner.start("llm", catalog={})

    assert runner.cancel(run.id) is True
    assert run.cancelled
