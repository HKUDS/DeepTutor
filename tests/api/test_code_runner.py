"""Learner code runner: policy gate, raw output, public-test comparison."""

from __future__ import annotations

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import code_runner
from deeptutor.services.sandbox.source import SourceRun
from deeptutor.services.sandbox.spec import ExecResult


def _run(stdout: str = "", *, stderr: str = "", exit_code: int = 0) -> SourceRun:
    return SourceRun(
        result=ExecResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        ),
        command="python3 main.py",
        workdir="/tmp/work",
        call_dir="/tmp/work/.deeptutor/exec_calls/python_1",
    )


@pytest.mark.asyncio
async def test_run_is_rejected_when_policy_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def deny(_user=None) -> bool:
        return False

    monkeypatch.setattr(code_runner, "can_execute_for_user", deny)

    with pytest.raises(HTTPException) as excinfo:
        await code_runner.code_run(code_runner.CodeRunRequest(language="python", code="print(1)"))

    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_run_returns_raw_output_and_marks_passing_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow(_user=None) -> bool:
        return True

    calls: list[str] = []

    async def fake_run_source(**kwargs):
        calls.append(kwargs["stdin"])
        if kwargs["stdin"] == "bad\n":
            return _run("0\n")
        return _run("6\n")

    monkeypatch.setattr(code_runner, "can_execute_for_user", allow)
    monkeypatch.setattr(code_runner, "run_source", fake_run_source)

    response = await code_runner.code_run(
        code_runner.CodeRunRequest(
            language="python",
            code="print(6)",
            tests=[
                code_runner.CodeTest(name="ok", stdin="1\n", expected_stdout="6\n"),
                code_runner.CodeTest(name="bad", stdin="bad\n", expected_stdout="6"),
            ],
        )
    )

    assert response.stdout == "6\n"
    assert response.exit_code == 0
    assert response.total == 2
    assert response.passed == 1
    assert [test.passed for test in response.tests] == [True, False]
    assert response.tests[0].expected_stdout == "6\n"
    assert calls == ["", "1\n", "bad\n"]


@pytest.mark.asyncio
async def test_run_treats_nonzero_exit_as_failed_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow(_user=None) -> bool:
        return True

    async def fake_run_source(**kwargs):
        return _run("", stderr="boom", exit_code=1)

    monkeypatch.setattr(code_runner, "can_execute_for_user", allow)
    monkeypatch.setattr(code_runner, "run_source", fake_run_source)

    response = await code_runner.code_run(
        code_runner.CodeRunRequest(
            language="python",
            code="raise SystemExit(1)",
            tests=[code_runner.CodeTest(name="fail", expected_stdout="")],
        )
    )

    assert response.passed == 0
    assert response.tests[0].stderr == "boom"
    assert response.tests[0].exit_code == 1


@pytest.mark.asyncio
async def test_capabilities_hide_languages_when_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.sandbox.spec import IsolationLevel

    class FakeService:
        async def isolation_level(self):
            return IsolationLevel.APPLICATION

    async def deny(_user=None) -> bool:
        return False

    monkeypatch.setattr(code_runner, "get_sandbox_service", lambda: FakeService())
    monkeypatch.setattr(code_runner, "can_execute_for_user", deny)

    capabilities = await code_runner.code_capabilities()

    assert capabilities.available is False
    assert capabilities.isolation == "application"
    assert capabilities.languages == []
