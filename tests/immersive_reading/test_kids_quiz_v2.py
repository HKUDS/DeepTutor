"""Contracts for age-adaptive, source-grounded chapter quizzes."""

from __future__ import annotations

import asyncio
import json


def _question(index: int, kind: str) -> dict:
    return {
        "id": f"q{index}",
        "kind": kind,
        "question": f"Question {index}?",
        "choices": ["Correct", "Wrong one", "Wrong two", "Wrong three"],
        "answer_index": 0,
        "explanation": "The chapter states this directly.",
    }


def test_v2_prompt_samples_long_chapters_and_requires_age_adaptive_kinds(
    reading_service, monkeypatch
) -> None:
    import deeptutor.immersive_reading.service as service_module

    filler = "The quiet harbor carries the story forward without changing its direction. "
    source = (
        "# Long Chapter\n"
        "Alpha saw the ancient compass at the observable beginning. "
        + filler * 110
        + " Middle: the brave sailor explained the narrow passage. " * 100
        + filler * 110
        + " Omega returned to the bright harbor at the peaceful end."
    )
    document = reading_service.import_document("long-chapter.txt", source.encode())
    section = document["sections"][-1]
    captured = {}

    async def fake_complete(**kwargs):
        captured.update(kwargs)
        return json.dumps(
            {
                "questions": [
                    _question(1, "comprehension"),
                    _question(2, "inference"),
                    _question(3, "vocabulary"),
                ]
            }
        )

    monkeypatch.setattr(service_module, "complete", fake_complete)
    result = asyncio.run(
        reading_service.generate_kids_quiz(document["id"], section["id"], age_band="9-12")
    )

    assert tuple(item.kind for item in result.questions) == (
        "comprehension",
        "inference",
        "vocabulary",
    )
    assert result.prompt_version == "kids-quiz-v2"
    assert result.age_band == "9-12"
    sampled_source = reading_service._kids_quiz_source_excerpt(source)
    assert "Alpha saw the ancient compass" in sampled_source
    assert "Middle: the brave sailor" in sampled_source
    assert "Omega returned to the bright harbor" in sampled_source
    assert "[... omitted ...]" in sampled_source
    prompt = captured["prompt"]
    assert "<story_text>" in prompt
    assert "Primary language: en" in prompt


def test_llm_failure_uses_deterministic_english_source_fallback_and_cache(
    reading_service, monkeypatch
) -> None:
    import deeptutor.immersive_reading.service as service_module

    source = """
# Harbor Chapter

Ada carried a small lantern through the narrow harbor gate.
Because the old map was faded, the brave sailor described the rocky shore.
The morning sun made the quiet water bright and clear.
Ada listened carefully while the compass needle pointed north.
The patient child opened the wooden chest near the boat.
A grateful bird glided above the ancient tower before sunset.
"""
    document = reading_service.import_document("fallback-book.txt", source.encode())
    section = document["sections"][-1]

    async def fail_llm(**kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(service_module, "complete", fail_llm)
    result = asyncio.run(
        reading_service.generate_kids_quiz(document["id"], section["id"], age_band="6-8")
    )
    assert tuple(item.kind for item in result.questions) == (
        "recall",
        "sequence",
        "vocabulary",
    )
    assert all(len(item.choices) == 4 for item in result.questions)
    assert result.model == "source-fallback"
    assert result.prompt_version == "kids-quiz-fallback-v2"

    async def fail_if_called(**kwargs):
        raise AssertionError("fallback cache must be reused")

    monkeypatch.setattr(service_module, "complete", fail_if_called)
    cached = asyncio.run(
        reading_service.generate_kids_quiz(document["id"], section["id"], age_band="6-8")
    )
    assert cached == result


def test_unconfigured_llm_still_uses_deterministic_fallback(reading_service, monkeypatch) -> None:
    import deeptutor.immersive_reading.service as service_module

    source = """
# Harbor Chapter

Ada carried a small lantern through the narrow harbor gate.
Because the old map was faded, the brave sailor described the rocky shore.
The morning sun made the quiet water bright and clear.
Ada listened carefully while the compass needle pointed north.
The patient child opened the wooden chest near the boat.
A grateful bird glided above the ancient tower before sunset.
"""
    document = reading_service.import_document("unconfigured-llm-book.txt", source.encode())
    section = document["sections"][-1]

    def fail_config():
        raise RuntimeError("No active LLM model is configured")

    monkeypatch.setattr(service_module, "get_llm_config", fail_config)
    result = asyncio.run(
        reading_service.generate_kids_quiz(document["id"], section["id"], age_band="6-8")
    )

    assert result.available is True
    assert len(result.questions) == 3
    assert result.model == "source-fallback"


def test_deterministic_fallback_follows_a_chinese_chapter_language(
    reading_service, monkeypatch
) -> None:
    import deeptutor.immersive_reading.service as service_module

    source = """
# 第一章

清晨的小女孩带着木灯笼走进狭窄港口。
因为旧地图已经模糊，勇敢的水手描述了礁石海岸。
明亮的阳光让安静海水显得清澈透明。
小女孩仔细听着罗盘指针指向北方。
耐心孩子打开了木船旁的小箱子。
黄昏前，一只感激的小鸟飞过古老灯塔。
"""
    document = reading_service.import_document("chinese-book.txt", source.encode())
    section = document["sections"][-1]

    async def fail_llm(**kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(service_module, "complete", fail_llm)
    result = asyncio.run(
        reading_service.generate_kids_quiz(document["id"], section["id"], age_band="6-8")
    )
    assert tuple(item.kind for item in result.questions) == (
        "recall",
        "sequence",
        "vocabulary",
    )
    for question in result.questions:
        assert any("\u4e00" <= char <= "\u9fff" for char in question.question)
        assert all(
            any("\u4e00" <= char <= "\u9fff" for char in choice) for choice in question.choices
        )


def test_v1_quiz_cache_is_regenerated_with_v2_prompt(
    reading_service, imported_document, monkeypatch
) -> None:
    from deeptutor.immersive_reading.models import KidsQuizQuestion, KidsQuizResult
    import deeptutor.immersive_reading.service as service_module

    document_id = imported_document["id"]
    section = imported_document["sections"][1]
    content = reading_service.get_section(document_id, section["id"])["content"]
    reading_service._save_kids_quiz_cache(
        document_id,
        section["id"],
        KidsQuizResult(
            document_id=document_id,
            section_id=section["id"],
            questions=[
                KidsQuizQuestion(id=f"q{i}", question=f"Old {i}?", choices=list("abcd"))
                for i in range(1, 4)
            ],
            content_hash=reading_service._content_hash(content),
            prompt_version="kids-quiz-v1",
        ),
    )

    async def fake_complete(**kwargs):
        return json.dumps(
            {
                "questions": [
                    _question(1, "recall"),
                    _question(2, "sequence"),
                    _question(3, "vocabulary"),
                ]
            }
        )

    monkeypatch.setattr(service_module, "complete", fake_complete)
    result = asyncio.run(
        reading_service.generate_kids_quiz(document_id, section["id"], age_band="6-8")
    )
    assert result.prompt_version == "kids-quiz-v2"
