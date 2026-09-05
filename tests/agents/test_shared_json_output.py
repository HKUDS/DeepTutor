from __future__ import annotations

from collections.abc import AsyncIterator
import json

from pydantic import BaseModel, ConfigDict
import pytest

from deeptutor.agents._shared.json_output import extract_json_object, require_json_object
from deeptutor.agents._shared.structured_llm import stream_and_validate_json


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", {}),
        ('{"value": 1}', {"value": 1}),
        ('Result:\n```json\n{"value": 2}\n```', {"value": 2}),
        ('Model preface\n{"value": 3}', {"value": 3}),
        ('{"value": 4}\nTrailing explanation', {"value": 4}),
    ],
)
def test_extract_json_object(text: str, expected: dict[str, int]) -> None:
    assert extract_json_object(text) == expected


def test_extract_json_object_rejects_output_without_an_object() -> None:
    with pytest.raises(json.JSONDecodeError, match="No JSON object found"):
        extract_json_object("No structured output")


def test_require_json_object_rejects_empty_content() -> None:
    with pytest.raises(json.JSONDecodeError, match="Empty model content"):
        require_json_object("")
    with pytest.raises(json.JSONDecodeError, match="Empty model content"):
        require_json_object("   ")


def test_require_json_object_parses_valid_payload() -> None:
    assert require_json_object('{"code": "pass"}') == {"code": "pass"}


class _ToyPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str = ""


@pytest.mark.asyncio
async def test_stream_and_validate_json_retries_after_null_content() -> None:
    calls: list[str] = []

    async def _stream(*, user_prompt: str, **_kwargs: object) -> AsyncIterator[str]:
        calls.append(user_prompt)
        if len(calls) == 1:
            # Simulate content: null → empty stream (reasoning-only reply).
            if False:  # pragma: no cover - keep this an async generator
                yield ""
            return
        yield '{"code": "from manim import *\\n"}'

    result = await stream_and_validate_json(
        stream=_stream,
        user_prompt="generate code",
        model_type=_ToyPayload,
        is_complete=lambda payload: bool(payload.code.strip()),
        max_attempts=3,
    )

    assert result.code.startswith("from manim")
    assert len(calls) == 2
    assert "IMPORTANT" in calls[1]


@pytest.mark.asyncio
async def test_stream_and_validate_json_retries_incomplete_payload() -> None:
    calls = 0

    async def _stream(*, user_prompt: str, **_kwargs: object) -> AsyncIterator[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            yield '{"code": ""}'
            return
        yield '{"code": "class MainScene(Scene):\\n    pass\\n"}'

    result = await stream_and_validate_json(
        stream=_stream,
        user_prompt="generate",
        model_type=_ToyPayload,
        is_complete=lambda payload: bool(payload.code.strip()),
    )
    assert "MainScene" in result.code
    assert calls == 2


@pytest.mark.asyncio
async def test_stream_and_validate_json_fails_soft_after_exhausted_retries() -> None:
    async def _stream(*, user_prompt: str, **_kwargs: object) -> AsyncIterator[str]:
        return
        yield ""  # pragma: no cover

    with pytest.raises(ValueError, match="unusable structured output"):
        await stream_and_validate_json(
            stream=_stream,
            user_prompt="generate",
            model_type=_ToyPayload,
            is_complete=lambda payload: bool(payload.code.strip()),
            max_attempts=2,
        )
