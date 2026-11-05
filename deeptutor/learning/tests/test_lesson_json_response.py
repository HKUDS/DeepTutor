"""Reading source-preparation JSON from reasoning-model replies (#2367)."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.learning import lesson_evidence as lessons
from deeptutor.learning.lesson_evidence import LessonUnavailable, _json_response
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT

PAYLOAD = {"queries": ["membrane lipid bilayer"]}


@pytest.mark.parametrize(
    "reply",
    [
        '{"queries": ["membrane lipid bilayer"]}',
        '<think>Draft: {"queries": ["draft"]}</think>\n{"queries": ["membrane lipid bilayer"]}',
        '<THINKING>\nI could return {"queries": []}.\n</THINKING>{"queries": ["membrane lipid bilayer"]}',
        'Here are the queries: {"queries": ["membrane lipid bilayer"]}',
        'Sources {as requested}: {"queries": ["membrane lipid bilayer"]}',
        'Sure.\n```json\n{"queries": ["membrane lipid bilayer"]}\n```\nLet me know.',
        'See [1].\n```\n{"queries": ["membrane lipid bilayer"]}\n```',
    ],
    ids=["plain", "think", "thinking", "prose", "prose-brace", "fence", "array-before-fence"],
)
def test_reads_the_object_around_reasoning_prose_and_fences(reply):
    assert _json_response(reply) == PAYLOAD


def test_nested_braces_inside_strings_survive():
    reply = 'Result: {"note": "use {braces}, \\"}\\" and ```", "n": {"m": [1, {"k": 2}]}} done.'
    assert _json_response(reply) == {
        "note": 'use {braces}, "}" and ```',
        "n": {"m": [1, {"k": 2}]},
    }


def test_a_complete_reply_keeps_tags_inside_its_strings():
    reply = '{"note": "<think>kept</think>"}'
    assert _json_response(reply) == {"note": "<think>kept</think>"}


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "I cannot help with that.",
        '{"queries": ["membrane", "lip',  # truncated by the token budget
        '{"sources": [{"id": 1}, {"id": 2}, {"id"',  # never a nested fragment
        '<think>Still reasoning, maybe {"queries": ["draft"]}',  # cut off mid-thought
    ],
    ids=["empty", "prose", "truncated", "truncated-nested", "unclosed-think"],
)
def test_invalid_replies_still_raise_lesson_unavailable(reply):
    with pytest.raises(LessonUnavailable, match="invalid source-selection response"):
        _json_response(reply)


@pytest.mark.parametrize("reply", ['[{"queries": []}]', "Here: [1, 2]", '"text"'])
def test_non_object_replies_are_rejected(reply):
    with pytest.raises(LessonUnavailable, match="not an object"):
        _json_response(reply)


def _config() -> LLMConfig:
    return LLMConfig(model="vision-test", api_key="k", binding="openai", reasoning_effort="max")


def test_ask_retries_once_with_reasoning_turned_down(monkeypatch):
    efforts = []

    async def complete(**kwargs):
        efforts.append(kwargs["config"].reasoning_effort)
        assert kwargs["max_tokens"] == 1800
        # The first reply spent its budget thinking and returned no answer.
        return "<think>Considering the objective" if len(efforts) == 1 else '{"queries": ["a"]}'

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    result = asyncio.run(lessons._ask(_config(), "Return only JSON", {"objective": "x"}))
    assert result == {"queries": ["a"]}
    assert efforts == ["max", RETRY_REASONING_EFFORT]


def test_ask_does_not_retry_a_usable_reply_or_a_provider_failure(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return '<think>ok</think>{"queries": ["a"]}'

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    assert asyncio.run(lessons._ask(_config(), "Return only JSON", {})) == {"queries": ["a"]}
    assert len(calls) == 1

    async def broken(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("connection refused")

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", broken)
    with pytest.raises(LessonUnavailable, match="could not complete source preparation"):
        asyncio.run(lessons._ask(_config(), "Return only JSON", {}))
    assert len(calls) == 2


def test_ask_reports_invalid_json_after_the_retry(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return "No JSON here."

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    with pytest.raises(LessonUnavailable, match="invalid source-selection response"):
        asyncio.run(lessons._ask(_config(), "Return only JSON", {}))
    assert len(calls) == 2


def test_assessment_requests_share_the_parser_and_retry(monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    efforts = []

    async def complete(**kwargs):
        efforts.append(kwargs["config"].reasoning_effort)
        assert kwargs["max_tokens"] == 2200
        if len(efforts) == 1:
            return ""
        return 'Verdicts follow.\n```json\n{"verdicts": []}\n```'

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    assert asyncio.run(semantic._request(_config(), "Judge", {})) == {"verdicts": []}
    assert efforts == ["max", RETRY_REASONING_EFFORT]
