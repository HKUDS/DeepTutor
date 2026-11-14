import asyncio
import copy

import pytest

from deeptutor.learning import lesson_evidence, semantic_assessment
from deeptutor.services.llm.config import LLMConfig


@pytest.mark.parametrize("budget", [1800, 2200])
@pytest.mark.parametrize("effort", [None, "low", "high", "none", "minimal", "minimum"])
def test_assessment_recovers_without_changing_evidence_or_config(monkeypatch, effort, budget):
    config = LLMConfig(
        model="deepseek-flash", api_key="test", binding="deepseek", reasoning_effort=effort
    )
    images = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,test"}}]
    payload = [{"question_id": "q1", "answer": "the learner's answer"}]
    original = copy.deepcopy((payload, images))
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        if kwargs["max_tokens"] < 4096:
            return ""
        return '{"verdicts":[{"question_id":"q1","result":"ungraded","confidence":0.2,"feedback":"Insufficient evidence"}]}'

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    messages = [
        {"role": "system", "content": "Assess the supplied evidence"},
        {"role": "user", "content": payload},
        {"role": "user", "content": images},
    ]
    result = asyncio.run(
        lesson_evidence._complete_json(
            config,
            messages=messages,
            max_tokens=budget,
            allow_image_fallback=False,
        )
    )
    assert result["verdicts"][0]["result"] == "ungraded"
    assert [call["max_tokens"] for call in calls] == [budget, 8192]
    assert calls[0]["config"] is config
    assert calls[1]["config"] is not config
    assert calls[1]["config"].reasoning_effort == (
        effort if effort in {"none", "minimal", "minimum"} else "low"
    )
    assert config.reasoning_effort == effort
    assert calls[0]["messages"] == calls[1]["messages"]
    assert calls[1]["allow_image_fallback"] is False
    assert (payload, images) == original


def test_valid_json_needs_no_retry(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return '{"supported":false,"citations":[]}'

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    result = asyncio.run(
        lesson_evidence._complete_json(LLMConfig(model="test", api_key="test"), max_tokens=2200)
    )
    assert result["supported"] is False
    assert len(calls) == 1


def test_repeated_bad_output_remains_unavailable(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return '{"verdicts":['

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    with pytest.raises(semantic_assessment.AssessmentUnavailable, match="No grade was saved"):
        asyncio.run(
            semantic_assessment._request(LLMConfig(model="test", api_key="test"), "Assess", {})
        )
    assert len(calls) == 2


def test_connection_error_does_not_get_format_retry(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        raise ConnectionError("offline")

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    with pytest.raises(semantic_assessment.AssessmentUnavailable):
        asyncio.run(
            semantic_assessment._request(LLMConfig(model="test", api_key="test"), "Assess", {})
        )
    assert len(calls) == 1


def test_retry_does_not_reduce_larger_output_budget(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return "" if len(calls) == 1 else '{"supported":false}'

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    asyncio.run(
        lesson_evidence._complete_json(LLMConfig(model="test", api_key="test"), max_tokens=12000)
    )
    assert calls[1]["max_tokens"] == 12000
