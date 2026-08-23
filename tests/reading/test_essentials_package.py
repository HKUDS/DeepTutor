from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from deeptutor.reading.extensions import ReadingContext

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


@pytest.mark.asyncio
async def test_five_extensions_are_independently_constructible(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_READING_TRANSLATION_MODEL", raising=False)
    monkeypatch.delenv("DEEPTUTOR_READING_TRANSLATION_PROVIDER", raising=False)
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


def test_vocabulary_reads_configured_local_dictionary(monkeypatch, tmp_path):
    dictionary = tmp_path / "dictionary.json"
    dictionary.write_text(json.dumps({"moon": "Earth's natural satellite"}), encoding="utf-8")
    monkeypatch.setenv("DEEPTUTOR_READING_DICTIONARY", str(dictionary))
    result = _module().VocabularyExtension().run_action("hint", _context())
    assert result.payload["definition"] == "Earth's natural satellite"
    assert result.message == "Local dictionary"


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


def test_quiz_keeps_answers_private_until_submit():
    module = _module()
    quiz = module.QuizExtension()
    result = quiz.run_action("start", _context())
    assert result.type == "quiz"
    assert result.payload["_answers"]
