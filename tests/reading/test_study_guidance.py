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
from deeptutor.reading.study_guidance import StudyGuidanceExtension
from deeptutor.services.path_service import PathService


def _context(selection: str = "verified phrase") -> ReadingContext:
    return ReadingContext(
        material_id="material",
        locator=1,
        locale="en",
        selection=selection,
        visible_text=f"Before context {selection} after context",
    )


@pytest.mark.asyncio
async def test_study_guidance_returns_a_bounded_card(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "focus": "Connect the phrase to its surrounding argument.",
                "steps": [
                    "Locate the two claims nearest the selected phrase.",
                    "Explain how the phrase links those two claims.",
                    "Rewrite the linked idea in one sentence.",
                ],
            }
        )

    monkeypatch.setattr("deeptutor.reading.study_guidance.complete", complete)
    result = await StudyGuidanceExtension().run_action("guide", _context())

    assert result.type == "card"
    assert result.title == "Study guidance"
    assert result.message == "Connect the phrase to its surrounding argument."
    assert result.payload["steps"] == [
        "Locate the two claims nearest the selected phrase.",
        "Explain how the phrase links those two claims.",
        "Rewrite the linked idea in one sentence.",
    ]
    prompt = json.loads(calls[0]["prompt"])
    assert prompt["selection"] == "verified phrase"
    assert "Before context" in prompt["surrounding_context"]
    assert calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_study_guidance_bounds_long_context(monkeypatch):
    text = "".join(f"sentence {index} " for index in range(2_000))
    selection = "sentence 1999"
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "focus": "Trace the final sentence back through the section.",
                "steps": ["Find the claim.", "Link the claim.", "Restate the idea."],
            }
        )

    monkeypatch.setattr("deeptutor.reading.study_guidance.complete", complete)
    await StudyGuidanceExtension().run_action(
        "guide",
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

    monkeypatch.setattr("deeptutor.reading.study_guidance.complete", complete)
    with pytest.raises(ValueError, match="requires selected text"):
        await StudyGuidanceExtension().run_action("guide", _context(""))


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        json.dumps({"focus": "too short steps", "steps": ["one", "two", "three"]}),
        json.dumps(
            {
                "focus": "A valid focus for this selected reading passage.",
                "steps": ["x" * 300, "Link the claim.", "Restate the idea."],
            }
        ),
    ],
)
@pytest.mark.asyncio
async def test_invalid_or_overlong_model_output_is_rejected(monkeypatch, response):
    async def complete(**_kwargs):
        return response

    monkeypatch.setattr("deeptutor.reading.study_guidance.complete", complete)
    with pytest.raises(ValueError, match="invalid (?:JSON|shape)"):
        await StudyGuidanceExtension().run_action("guide", _context())


def test_study_guidance_is_registered_as_a_packaged_extension():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    group = project["project"]["entry-points"]["deeptutor.reading_extensions"]

    assert group["guided_learning"] == ("deeptutor.reading.study_guidance:StudyGuidanceExtension")


def _client(monkeypatch, extension) -> TestClient:
    registry = ReadingExtensionRegistry([extension])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    return TestClient(app)


def test_study_guidance_crosses_the_api_boundary_with_verified_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Stored passage with a verified phrase.", encoding="utf-8")
    material = ReadingStore().ingest(source)
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return json.dumps(
            {
                "focus": "Connect the phrase to the stored passage.",
                "steps": ["Find the phrase.", "Link the phrase.", "Restate the idea."],
            }
        )

    monkeypatch.setattr("deeptutor.reading.study_guidance.complete", complete)
    client = _client(monkeypatch, StudyGuidanceExtension())
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}"
            "/extensions/guided_learning/actions/guide",
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


def test_forged_selection_is_rejected_before_the_extension_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Stored passage.", encoding="utf-8")
    material = ReadingStore().ingest(source)
    monkeypatch.setattr(
        "deeptutor.reading.study_guidance.complete",
        lambda **_kwargs: pytest.fail("forged selection must not invoke the model"),
    )
    client = _client(monkeypatch, StudyGuidanceExtension())
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}"
            "/extensions/guided_learning/actions/guide",
            json={"locator": 1, "selection": "forged phrase"},
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == 400
