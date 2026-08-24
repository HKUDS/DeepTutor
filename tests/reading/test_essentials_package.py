from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tomllib

import pytest

from deeptutor.reading.extensions import ReadingContext
from deeptutor.services.llm.exceptions import LLMConfigError

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "deeptutor-reading-essentials"


def _module():
    sys.path.insert(0, str(PACKAGE_ROOT))
    try:
        spec = importlib.util.find_spec("deeptutor_reading_essentials")
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(PACKAGE_ROOT))


def _context() -> ReadingContext:
    return ReadingContext(
        material_id="abc12345",
        locator=1,
        unit_text="The moon reflects sunlight. It travels around Earth.",
        visible_text="The moon reflects sunlight. It travels around Earth.",
        selection="moon",
    )


def _chinese_context() -> ReadingContext:
    text = "月亮反射太阳光。月亮绕着地球转动。"
    return ReadingContext(
        material_id="abc12345",
        locator=1,
        unit_text=text,
        visible_text=text,
        locale="zh-CN",
        selection="月亮",
    )


def test_package_contract_declares_all_five_entry_points() -> None:
    with (PACKAGE_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)

    entry_points = project["project"]["entry-points"]["deeptutor.reading_extensions"]
    assert entry_points == {
        "guided_learn": "deeptutor_reading_essentials:GuidedLearnExtension",
        "quiz": "deeptutor_reading_essentials:QuizExtension",
        "read_aloud": "deeptutor_reading_essentials:ReadAloudExtension",
        "translation": "deeptutor_reading_essentials:TranslationExtension",
        "vocabulary": "deeptutor_reading_essentials:VocabularyExtension",
    }
    assert project["tool"]["setuptools"]["packages"] == ["deeptutor_reading_essentials"]


@pytest.mark.asyncio
async def test_five_extensions_are_independently_constructible(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_READING_TRANSLATION_MODEL", raising=False)
    monkeypatch.delenv("DEEPTUTOR_READING_TRANSLATION_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPTUTOR_READING_LEARN_MODEL", raising=False)
    monkeypatch.delenv("DEEPTUTOR_READING_LEARN_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPTUTOR_READING_QUIZ_MODEL", raising=False)
    monkeypatch.delenv("DEEPTUTOR_READING_QUIZ_PROVIDER", raising=False)
    module = _module()
    rows = [
        module.GuidedLearnExtension(),
        module.QuizExtension(),
        module.ReadAloudExtension(),
        module.TranslationExtension(),
        module.VocabularyExtension(),
    ]
    assert {row.manifest.id for row in rows} == {
        "guided_learn",
        "quiz",
        "read_aloud",
        "translation",
        "vocabulary",
    }
    translation = next(row for row in rows if row.manifest.id == "translation")
    result = await translation.run_action("translate", _context())
    assert "DEEPTUTOR_READING_TRANSLATION_MODEL" in result.message


@pytest.mark.asyncio
async def test_guided_learn_fallback_extracts_page_concepts(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_READING_LEARN_MODEL", raising=False)
    result = await _module().GuidedLearnExtension().run_action("explain", _context())

    assert result.payload["overview"] == ("The moon reflects sunlight. It travels around Earth.")
    assert "moon" in {row["term"].lower() for row in result.payload["concept_details"]}
    assert any(row.startswith("moon:") for row in result.payload["concepts"])
    assert result.payload["reflection"].startswith("Why is ")
    assert result.payload["reflection_hint"]
    assert result.payload["source"] == "fallback"


@pytest.mark.asyncio
async def test_guided_learn_and_quiz_fallbacks_support_chinese_pages(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_READING_LEARN_MODEL", raising=False)
    monkeypatch.delenv("DEEPTUTOR_READING_QUIZ_MODEL", raising=False)
    module = _module()
    context = _chinese_context()

    learn = await module.GuidedLearnExtension().run_action("explain", context)
    assert learn.payload["overview"] == "月亮反射太阳光。月亮绕着地球转动。"
    assert learn.payload["reflection"].startswith("想一想：")

    quiz = await module.QuizExtension().run_action("start", context)
    assert len(quiz.payload["questions"]) == 3
    assert all(row["prompt"] for row in quiz.payload["questions"])


@pytest.mark.asyncio
async def test_guided_learn_uses_explicit_model_and_falls_back_safely(monkeypatch):
    calls = {}
    generated = {
        "overview": "The moon lights the night by reflecting sunlight.",
        "concepts": [
            {
                "term": "reflects",
                "explanation": "Light bounces from the sun off the moon.",
                "analogy": "Like a mirror bouncing a flashlight beam.",
            }
        ],
        "reflection": {
            "prompt": "Why does the moon shine?",
            "hint": "Follow the sunlight.",
            "answer": "It reflects sunlight.",
        },
    }

    async def fake_complete(_prompt, **kwargs):
        calls.update(kwargs)
        if calls.get("fail"):
            raise RuntimeError("model unavailable")
        return json.dumps(generated)

    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    monkeypatch.setenv("DEEPTUTOR_READING_LEARN_MODEL", "learn-model")
    monkeypatch.setenv("DEEPTUTOR_READING_LEARN_PROVIDER", "local-provider")
    extension = _module().GuidedLearnExtension()

    result = await extension.run_action("explain", _context())
    assert result.payload["source"] == "generated"
    assert result.payload["concept_details"][0]["analogy"].startswith("Like a mirror")
    assert calls["model"] == "learn-model"
    assert calls["binding"] == "local-provider"

    calls["fail"] = True
    fallback = await extension.run_action("explain", _context())
    assert fallback.payload["source"] == "fallback"


def test_vocabulary_reads_configured_local_dictionary(monkeypatch, tmp_path):
    dictionary = tmp_path / "dictionary.json"
    dictionary.write_text(json.dumps({"moon": "Earth's natural satellite"}), encoding="utf-8")
    monkeypatch.setenv("DEEPTUTOR_READING_DICTIONARY", str(dictionary))
    result = _module().VocabularyExtension().run_action("hint", _context())
    assert result.payload["definition"] == "Earth's natural satellite"
    assert result.message == "Local dictionary"


def test_vocabulary_uses_builtin_kids_word_hints_as_a_private_quiz(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_READING_DICTIONARY", raising=False)
    result = _module().VocabularyExtension().run_action("hint", _context())

    assert result.type == "quiz"
    question = result.payload["questions"][0]
    assert question["prompt"] == "Which meaning fits this word?"
    assert len(question["choices"]) == 3
    assert "the bright thing in the night sky" in question["choices"]
    assert "_metadata" in result.payload["_answers"]
    assert result.payload["_answers"]["_metadata"]["chinese"] == "月亮"
    assert "月亮" not in json.dumps(result.payload["questions"])

    correct = result.payload["_answers"]["meaning"]
    feedback = (
        _module()
        .VocabularyExtension()
        .submit(
            {"private": {"answers": result.payload["_answers"]}},
            {"answers": {"meaning": correct}},
        )
    )
    assert feedback.payload["correct"] is True
    assert feedback.payload["chinese"] == "月亮"
    assert feedback.message == "Correct! moon: 月亮"


@pytest.mark.asyncio
async def test_translation_uses_explicit_model(monkeypatch):
    calls = {}

    async def fake_complete(prompt, **kwargs):
        calls.update(prompt=prompt, **kwargs)
        return "月亮反射太阳光。"

    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    monkeypatch.setenv("DEEPTUTOR_READING_TRANSLATION_MODEL", "translation-model")
    monkeypatch.setenv("DEEPTUTOR_READING_TRANSLATION_PROVIDER", "local-provider")
    result = await _module().TranslationExtension().run_action("translate", _context())
    assert result.payload["translation"] == "月亮反射太阳光。"
    assert calls["model"] == "translation-model"
    assert calls["binding"] == "local-provider"


@pytest.mark.asyncio
async def test_translation_reports_configuration_errors_as_actionable_cards(monkeypatch):
    async def fake_complete(_prompt, **_kwargs):
        raise LLMConfigError("No API key is configured for this provider")

    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    monkeypatch.setenv("DEEPTUTOR_READING_TRANSLATION_MODEL", "translation-model")
    result = await _module().TranslationExtension().run_action("translate", _context())

    assert result.type == "card"
    assert "No API key is configured" in result.message
    assert result.payload["source_text"] == _context().selection


@pytest.mark.asyncio
async def test_quiz_uses_story_comprehension_and_keeps_answers_private_until_submit(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_READING_QUIZ_MODEL", raising=False)
    module = _module()
    quiz = module.QuizExtension()
    result = await quiz.run_action("start", _context())
    assert result.type == "quiz"
    questions = result.payload["questions"]
    assert len(questions) == 3
    assert len({row["prompt"] for row in questions}) == 3
    assert all(2 <= len(row["choices"]) <= 4 for row in questions)
    assert all("answer_index" not in row for row in questions)
    assert set(result.payload["_answers"]) == {"q1", "q2", "q3", "_metadata"}

    from deeptutor.api.routers.reading_extensions import _public_result

    assert "_answers" not in _public_result(result)["payload"]

    expected = result.payload["_answers"]
    feedback = quiz.submit(
        {"private": {"answers": expected}},
        {"answers": {key: value for key, value in expected.items() if key != "_metadata"}},
    )
    assert feedback.message == "3/3"
    assert feedback.payload["score"] == 3
    assert feedback.payload["total"] == 3


@pytest.mark.asyncio
async def test_quiz_uses_explicit_model_and_falls_back_safely(monkeypatch):
    calls = {"count": 0, "fail": False}

    async def fake_complete(_prompt, **kwargs):
        calls.update(kwargs)
        calls["count"] += 1
        if calls["fail"]:
            raise RuntimeError("model unavailable")
        return json.dumps(
            {
                "questions": [
                    {
                        "id": "model-q1",
                        "question": "What does the moon reflect?",
                        "choices": ["sunlight", "starlight", "firelight"],
                        "answer_index": 0,
                        "explanation": "The text says the moon reflects sunlight.",
                    }
                ]
            }
        )

    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    monkeypatch.setenv("DEEPTUTOR_READING_QUIZ_MODEL", "quiz-model")
    monkeypatch.setenv("DEEPTUTOR_READING_QUIZ_PROVIDER", "local-provider")
    extension = _module().QuizExtension()
    result = await extension.run_action("start", _context())

    assert result.payload["questions"][0]["prompt"] == "What does the moon reflect?"
    assert len(result.payload["questions"]) == 3
    assert calls["model"] == "quiz-model"
    assert calls["binding"] == "local-provider"

    calls["fail"] = True
    fallback = await extension.run_action("start", _context())
    assert len(fallback.payload["questions"]) == 3
    assert fallback.payload["questions"][0]["prompt"] != "What does the moon reflect?"
