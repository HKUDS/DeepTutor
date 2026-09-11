"""Focused tests for the home chat's dynamic composer line."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.services import chat_hints


@pytest.fixture(autouse=True)
def clear_hint_state() -> None:
    chat_hints._cache.clear()
    chat_hints._inflight.clear()


def _material() -> chat_hints._Material:
    return chat_hints._Material(
        transcript=[
            ("user", "How do retries work here?"),
            ("assistant", "It retries up to three times with backoff."),
        ],
        transcript_length=2,
    )


def test_sanitize_allows_non_question_lines() -> None:
    # Unlike the mastery/reading hints, this one must NOT require a question
    # mark — a plausible next turn is often a request, not a question.
    assert chat_hints._sanitize("Make the tone more casual", "en") == "Make the tone more casual"


def test_sanitize_rejects_meta_and_assistant_voice() -> None:
    assert chat_hints._sanitize("You could ask about the retry limit", "en") == ""
    assert chat_hints._sanitize("Sure, here's a more casual version.", "en") == ""
    assert chat_hints._sanitize("好的，这是更随意一点的版本。", "zh") == ""
    assert chat_hints._sanitize("你可以问问重试上限", "zh") == ""


def test_sanitize_rejects_echo_of_last_user_message() -> None:
    assert (
        chat_hints._sanitize("How do retries work here?", "en", "How do retries work here?") == ""
    )
    assert chat_hints._sanitize(
        "What happens after the third retry fails?",
        "en",
        "How do retries work here?",
    )


@pytest.mark.asyncio
async def test_empty_transcript_never_calls_the_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def call_llm(_material: chat_hints._Material, _language: str) -> str:
        nonlocal calls
        calls += 1
        return "should not be reached"

    monkeypatch.setattr(chat_hints, "_call_llm", call_llm)

    async def collect(_session_id: str) -> chat_hints._Material:
        return chat_hints._Material(transcript=[], transcript_length=0)

    monkeypatch.setattr(chat_hints, "_collect", collect)

    result = await chat_hints.get_ask_hint("session-1")

    assert result["hint"] == ""
    assert calls == 0


@pytest.mark.asyncio
async def test_cache_hit_does_not_invoke_llm_again(monkeypatch: pytest.MonkeyPatch) -> None:
    material = _material()
    calls = 0

    async def collect(_session_id: str) -> chat_hints._Material:
        return material

    async def call_llm(_material: chat_hints._Material, _language: str) -> str:
        nonlocal calls
        calls += 1
        return "What happens after the third retry fails?"

    monkeypatch.setattr(chat_hints, "_collect", collect)
    monkeypatch.setattr(chat_hints, "_call_llm", call_llm)
    monkeypatch.setattr(chat_hints, "_response_language", lambda: "en")

    first = await chat_hints.get_ask_hint("session-1")
    second = await chat_hints.get_ask_hint("session-1")

    assert first == second
    assert first["hint"] == "What happens after the third retry fails?"
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [asyncio.TimeoutError(), RuntimeError("model unavailable")],
    ids=["timeout", "failure"],
)
async def test_llm_failure_returns_empty_hint(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    async def collect(_session_id: str) -> chat_hints._Material:
        return _material()

    async def fail_llm(_material: chat_hints._Material, _language: str) -> str:
        raise error

    monkeypatch.setattr(chat_hints, "_collect", collect)
    monkeypatch.setattr(chat_hints, "_call_llm", fail_llm)
    monkeypatch.setattr(chat_hints, "_response_language", lambda: "en")

    result = await chat_hints.get_ask_hint("session-1")

    assert result["hint"] == ""
