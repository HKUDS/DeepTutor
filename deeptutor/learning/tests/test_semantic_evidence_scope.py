"""The grader is told what evidence it actually has, and how to score confidence."""

import pytest

from deeptutor.learning import semantic_assessment as semantic


def _items(*with_sources: bool) -> list[dict]:
    return [
        {
            "question_id": f"q{index}",
            "prompt": "Explain the concept.",
            "expected_answer": "A rubric answer.",
            "answer": "The learner answer.",
            "source_evidence": {"sources": [{"ref": "doc#1"}]} if has_source else {},
        }
        for index, has_source in enumerate(with_sources, start=1)
    ]


async def _judge(monkeypatch, items):
    captured = {}

    async def request(config, instruction, payload, **kwargs):
        captured["instruction"] = instruction
        captured["payload"] = payload
        return {
            "verdicts": [
                {
                    "question_id": item["question_id"],
                    "result": "correct",
                    "confidence": 0.9,
                    "feedback": "Matches the rubric.",
                }
                for item in payload
            ]
        }

    monkeypatch.setattr(semantic, "_request", request)
    verdicts = await semantic.judge_answers(object(), items)
    return captured["instruction"], verdicts


@pytest.mark.asyncio
async def test_no_supplied_sources_are_not_held_against_the_answer(monkeypatch):
    instruction, verdicts = await _judge(monkeypatch, _items(False))

    assert "no source materials are supplied" in instruction
    assert "supplied source evidence." not in instruction
    assert "not a reason to lower confidence" in instruction
    assert verdicts["q1"].result == "correct"


@pytest.mark.asyncio
async def test_supplied_sources_are_still_weighed(monkeypatch):
    instruction, _ = await _judge(monkeypatch, _items(True))

    assert "the supplied source evidence" in instruction
    assert "no source materials are supplied" not in instruction


@pytest.mark.asyncio
async def test_mixed_batch_judges_each_item_on_its_own_evidence(monkeypatch):
    instruction, _ = await _judge(monkeypatch, _items(True, False))

    assert "any supplied source evidence" in instruction
    assert "items without sources" in instruction


@pytest.mark.asyncio
@pytest.mark.parametrize("with_sources", [(False,), (True,), (True, False)])
async def test_confidence_scale_is_defined_for_the_grader(monkeypatch, with_sources):
    instruction, _ = await _judge(monkeypatch, _items(*with_sources))

    assert "0.8-0.89" in instruction
    assert "below 0.8" in instruction
