from __future__ import annotations

import json
from pathlib import Path
import tomllib

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading_extensions
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import ReadingContext, ReadingExtensionRegistry
from deeptutor.reading.translation import TranslationExtension
from deeptutor.services.path_service import PathService


def _context(
    selection: str = "verified phrase",
    locale: str = "en",
) -> ReadingContext:
    return ReadingContext(
        material_id="material",
        locator=1,
        locale=locale,
        selection=selection,
        visible_text=f"Before context {selection} after context",
    )


def _model_response(target_language: str = "en") -> str:
    return json.dumps(
        {
            "translation": "已验证短语" if target_language == "zh" else "verified phrase",
            "alternatives": ["checked phrase"] if target_language == "en" else [],
            "note": "The surrounding context supports this reading."
            if target_language == "en"
            else "",
            "target_language": target_language,
        }
    )


@pytest.mark.asyncio
async def test_translation_returns_a_bounded_card(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return _model_response()

    monkeypatch.setattr("deeptutor.reading.translation.complete", complete)
    result = await TranslationExtension().run_action("translate_en", _context())

    assert result.type == "card"
    assert result.title == "Translation"
    assert result.message == "Translation uses the selected passage."
    assert result.payload == {
        "translation": "verified phrase",
        "alternatives": ["checked phrase"],
        "note": "The surrounding context supports this reading.",
    }
    prompt = json.loads(calls[0]["prompt"])
    assert prompt["selection"] == "verified phrase"
    assert "Before context" in prompt["surrounding_context"]
    assert calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_translation_targets_the_requested_language_not_the_ui_locale(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return _model_response("zh")

    monkeypatch.setattr("deeptutor.reading.translation.complete", complete)
    result = await TranslationExtension().run_action(
        "translate_zh",
        _context(locale="en"),
    )

    assert result.title == "翻译"
    assert result.payload["translation"] == "已验证短语"
    assert "中文译文" in calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_translation_bounds_long_context(monkeypatch):
    text = "".join(f"sentence {index} " for index in range(2_000))
    selection = "sentence 1999"
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return _model_response()

    monkeypatch.setattr("deeptutor.reading.translation.complete", complete)
    await TranslationExtension().run_action(
        "translate_en",
        ReadingContext(
            material_id="material",
            locator=1,
            selection=selection,
            visible_text=text,
        ),
    )

    prompt = json.loads(calls[0]["prompt"])
    assert len(prompt["surrounding_context"]) <= 6_000
    assert selection in prompt["surrounding_context"]


@pytest.mark.asyncio
async def test_missing_selection_fails_before_an_llm_call(monkeypatch):
    async def complete(**_kwargs):
        pytest.fail("missing selection must not invoke the model")

    monkeypatch.setattr("deeptutor.reading.translation.complete", complete)
    with pytest.raises(ValueError, match="requires selected text"):
        await TranslationExtension().run_action("translate_en", _context(""))


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        json.dumps({"alternatives": [], "note": "", "target_language": "en"}),
        json.dumps(
            {
                "translation": "verified phrase",
                "alternatives": [],
                "note": "",
                "target_language": "fr",
            }
        ),
        json.dumps(
            {
                "translation": "verified phrase",
                "alternatives": [
                    "checked phrase",
                    "checked phrase",
                ],
                "note": "",
                "target_language": "en",
            }
        ),
        json.dumps(
            {
                "translation": "x" * 12_001,
                "alternatives": [],
                "note": "",
                "target_language": "en",
            }
        ),
        json.dumps(
            {
                "translation": "verified phrase",
                "alternatives": ["one", "two", "three", "four"],
                "note": "",
                "target_language": "en",
            }
        ),
    ],
)
@pytest.mark.asyncio
async def test_invalid_or_wrong_language_model_output_is_rejected(monkeypatch, response):
    async def complete(**_kwargs):
        return response

    monkeypatch.setattr("deeptutor.reading.translation.complete", complete)
    with pytest.raises(ValueError):
        await TranslationExtension().run_action("translate_en", _context())


def test_translation_is_registered_as_a_packaged_extension():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    group = project["project"]["entry-points"]["deeptutor.reading_extensions"]

    assert group["translation"] == "deeptutor.reading.translation:TranslationExtension"


def _client(monkeypatch) -> TestClient:
    registry = ReadingExtensionRegistry([TranslationExtension()])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    return TestClient(app)


def test_translation_crosses_the_api_boundary_with_stored_unit_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Stored passage with a verified phrase.", encoding="utf-8")
    material = ReadingStore().ingest(source)
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return _model_response()

    monkeypatch.setattr("deeptutor.reading.translation.complete", complete)
    client = _client(monkeypatch)
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}"
            "/extensions/translation/actions/translate_en",
            json={
                "locator": 1,
                "selection": "verified phrase",
                "visible_text": "forged phrase",
                "locale": "en",
            },
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == 200, response.text
    prompt = json.loads(captured["prompt"])
    assert prompt["selection"] == "verified phrase"
    assert "Stored passage with a verified phrase." in prompt["surrounding_context"]
    assert "forged phrase" not in prompt["surrounding_context"]


def test_forged_translation_selection_is_rejected_before_the_llm(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Stored passage with a verified phrase.", encoding="utf-8")
    material = ReadingStore().ingest(source)

    async def complete(**_kwargs):
        pytest.fail("a forged selection must not invoke the model")

    monkeypatch.setattr("deeptutor.reading.translation.complete", complete)
    client = _client(monkeypatch)
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}"
            "/extensions/translation/actions/translate_en",
            json={"locator": 1, "selection": "not in the material", "locale": "en"},
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == 400
    assert response.json()["detail"] == "Select text from the visible unit first."
