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
from deeptutor.reading.vocabulary import VocabularyExtension
from deeptutor.services.path_service import PathService


def _context(selection: str = "verified phrase") -> ReadingContext:
    return ReadingContext(
        material_id="material",
        locator=1,
        locale="en",
        selection=selection,
        visible_text=f"Before context {selection} after context",
    )


def _model_response() -> str:
    return json.dumps(
        {
            "terms": [
                {
                    "term": "verified",
                    "meaning": "The passage presents this phrase as checked evidence.",
                    "usage": "It modifies the noun that carries the passage's main claim.",
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_vocabulary_returns_a_bounded_card(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return _model_response()

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    result = await VocabularyExtension().run_action("explain", _context())

    assert result.type == "card"
    assert result.title == "Vocabulary help"
    assert result.message == "Explanations use the selected passage."
    assert result.payload["terms"] == [
        {
            "term": "verified",
            "meaning": "The passage presents this phrase as checked evidence.",
            "usage": "It modifies the noun that carries the passage's main claim.",
        }
    ]
    prompt = json.loads(calls[0]["prompt"])
    assert prompt["selection"] == "verified phrase"
    assert "Before context" in prompt["surrounding_context"]
    assert calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_vocabulary_bounds_long_context(monkeypatch):
    text = "".join(f"sentence {index} " for index in range(2_000))
    selection = "sentence 1999"
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "terms": [
                    {
                        "term": "sentence",
                        "meaning": "The passage is organized into individual statements.",
                        "usage": "Each numbered sentence supplies one step of context.",
                    }
                ]
            }
        )

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    await VocabularyExtension().run_action(
        "explain",
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

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    with pytest.raises(ValueError, match="requires selected text"):
        await VocabularyExtension().run_action("explain", _context(""))


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        json.dumps({"terms": []}),
        json.dumps(
            {
                "terms": [
                    {
                        "term": "outside",
                        "meaning": "This term is not part of the selected text.",
                        "usage": "The passage does not use this term at all.",
                    }
                ]
            }
        ),
        json.dumps(
            {
                "terms": [
                    {
                        "term": "ified",
                        "meaning": "A word fragment is not an exact vocabulary term.",
                        "usage": "The passage contains it only inside another word.",
                    }
                ]
            }
        ),
        json.dumps(
            {
                "terms": [
                    {
                        "term": "verified",
                        "meaning": "The passage presents this phrase as checked evidence.",
                        "usage": "It modifies the noun that carries the passage's main claim.",
                    },
                    {
                        "term": "VERIFIED",
                        "meaning": "The passage presents this phrase as checked evidence.",
                        "usage": "It modifies the noun that carries the passage's main claim.",
                    },
                ]
            }
        ),
    ],
)
@pytest.mark.asyncio
async def test_invalid_or_ungrounded_model_output_is_rejected(monkeypatch, response):
    async def complete(**_kwargs):
        return response

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    with pytest.raises(ValueError):
        await VocabularyExtension().run_action("explain", _context())


def test_vocabulary_is_registered_as_a_packaged_extension():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    group = project["project"]["entry-points"]["deeptutor.reading_extensions"]

    assert group["vocabulary"] == "deeptutor.reading.vocabulary:VocabularyExtension"


def _client(monkeypatch) -> TestClient:
    registry = ReadingExtensionRegistry([VocabularyExtension()])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    return TestClient(app)


def test_vocabulary_crosses_the_api_boundary_with_verified_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Stored passage with a verified phrase.", encoding="utf-8")
    material = ReadingStore().ingest(source)
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return _model_response()

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    client = _client(monkeypatch)
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}/extensions/vocabulary/actions/explain",
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
