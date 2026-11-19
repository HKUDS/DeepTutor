"""Learner-facing code execution for coding exercises.

This surface is deliberately separate from the agent's ``exec`` tool: the
request shape is a code-exercise payload (source, stdin, public samples) and
the response is raw process output, not a model-facing tool message. Both
execute through :mod:`deeptutor.services.sandbox.source`, and both answer to
the same per-user policy in :mod:`deeptutor.services.sandbox.policy`.
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.multi_user.context import get_current_user_or_none
from deeptutor.services.sandbox import get_sandbox_service
from deeptutor.services.sandbox.policy import can_execute_for_user
from deeptutor.services.sandbox.source import resource_limits, run_source

router = APIRouter()

MAX_CODE_CHARS = 200_000
MAX_STDIN_CHARS = 20_000
MAX_TESTS = 10
MAX_TIMEOUT_S = 30
MAX_TOTAL_TEST_SECONDS = 60


class CodeTest(BaseModel):
    name: str = Field(default="", max_length=80)
    stdin: str = Field(default="", max_length=MAX_STDIN_CHARS)
    expected_stdout: str = Field(max_length=MAX_STDIN_CHARS)


class CodeRunRequest(BaseModel):
    language: Literal["python", "c", "cpp"] = "python"
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    stdin: str = Field(default="", max_length=MAX_STDIN_CHARS)
    timeout: int = Field(default=10, ge=1, le=MAX_TIMEOUT_S)
    tests: list[CodeTest] = Field(default_factory=list, max_length=MAX_TESTS)


class CodeTestResult(BaseModel):
    name: str
    passed: bool
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    expected_stdout: str
    duration_ms: int


class CodeRunResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    error: str = ""
    tests: list[CodeTestResult] = Field(default_factory=list)
    passed: int = 0
    total: int = 0
    duration_ms: int = 0


class CodeCapabilities(BaseModel):
    available: bool
    isolation: str
    languages: list[str] = Field(default_factory=list)
    max_timeout: int = MAX_TIMEOUT_S
    max_tests: int = MAX_TESTS


def _normalize_output(value: str) -> str:
    """Compare program output the way a learner reads it.

    Trailing newlines and whitespace do not change the answer; internal
    whitespace does, so a sum written ``1 2`` is not accepted for ``12``.
    """
    return str(value or "").replace("\r\n", "\n").strip()


def _clip(value: str, limit: int = 10_000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n... ({len(text) - limit:,} chars truncated) ...\n{text[-half:]}"


def _user_id() -> str:
    user = get_current_user_or_none()
    return str(getattr(user, "id", "") or "anonymous")


async def _require_execution_allowed() -> None:
    if not await can_execute_for_user(get_current_user_or_none()):
        raise HTTPException(
            status_code=403,
            detail=(
                "Code execution is unavailable for this account on this "
                "deployment. Ask an administrator to enable a system-isolated "
                "sandbox."
            ),
        )


@router.get("/capabilities", response_model=CodeCapabilities, operation_id="code_capabilities")
async def code_capabilities() -> CodeCapabilities:
    """Tell the editor whether the Run buttons may be shown."""
    level = await get_sandbox_service().isolation_level()
    available = await can_execute_for_user(get_current_user_or_none())
    return CodeCapabilities(
        available=available,
        isolation=str(getattr(level, "value", level)),
        languages=["python", "c", "cpp"] if available else [],
        max_timeout=MAX_TIMEOUT_S,
        max_tests=MAX_TESTS,
    )


@router.post("/run", response_model=CodeRunResponse, operation_id="code_run")
async def code_run(payload: CodeRunRequest) -> CodeRunResponse:
    """Run a learner's source once and, when supplied, against public samples."""
    await _require_execution_allowed()

    user_id = _user_id()
    limits = resource_limits(payload.timeout)
    started = time.perf_counter()

    run = await run_source(
        language=payload.language,
        code=payload.code,
        stdin=payload.stdin,
        timeout_s=payload.timeout,
        user_id=user_id,
    )
    result = run.result
    response = CodeRunResponse(
        stdout=_clip(result.stdout, limits.max_output_chars),
        stderr=_clip(result.stderr, limits.max_output_chars),
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        error=_clip(result.error, limits.max_output_chars),
        total=len(payload.tests),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )

    deadline = started + MAX_TOTAL_TEST_SECONDS
    for test in payload.tests:
        if time.perf_counter() > deadline:
            response.error = response.error or "Total test time budget exceeded."
            break
        test_started = time.perf_counter()
        test_run = await run_source(
            language=payload.language,
            code=payload.code,
            stdin=test.stdin,
            timeout_s=payload.timeout,
            user_id=user_id,
        )
        test_result = test_run.result
        actual = _clip(test_result.stdout, limits.max_output_chars)
        passed = (
            not test_result.error
            and not test_result.timed_out
            and test_result.exit_code == 0
            and _normalize_output(actual) == _normalize_output(test.expected_stdout)
        )
        if passed:
            response.passed += 1
        response.tests.append(
            CodeTestResult(
                name=test.name or f"Test {len(response.tests) + 1}",
                passed=passed,
                stdout=actual,
                stderr=_clip(test_result.stderr, limits.max_output_chars),
                exit_code=test_result.exit_code,
                timed_out=test_result.timed_out,
                expected_stdout=test.expected_stdout,
                duration_ms=int((time.perf_counter() - test_started) * 1000),
            )
        )
        if test_result.error and not response.error:
            response.error = _clip(test_result.error, limits.max_output_chars)

    return response


__all__ = [
    "CodeCapabilities",
    "CodeRunRequest",
    "CodeRunResponse",
    "CodeTest",
    "CodeTestResult",
    "router",
]
