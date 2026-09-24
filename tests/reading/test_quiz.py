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
from deeptutor.reading.quiz import ReadingQuizExtension
from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT
from deeptutor.services.path_service import PathService


def _context(selection: str = "") -> ReadingContext:
    return ReadingContext(
        material_id="material",
        locator=1,
        locale="en",
        selection=selection,
        visible_text=("Before context verified phrase supports the answer after context " * 4),
    )


def _model_response(evidence: str = "verified phrase supports the answer") -> str:
    return json.dumps(
        {
            "questions": [
                {
                    "prompt": "Which phrase does the passage verify?",
                    "choices": [
                        "An unrelated phrase",
                        "A checked phrase",
                        "A guessed phrase",
                        "An omitted phrase",
                    ],
                    "correct_choice_index": 1,
                    "evidence": evidence,
                }
            ]
            * 3
        }
    )


@pytest.mark.asyncio
async def test_quiz_returns_a_bounded_quiz_without_grounding_metadata(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return _model_response()

    monkeypatch.setattr("deeptutor.reading.quiz.complete", complete)
    result = await ReadingQuizExtension().run_action("start", _context())

    assert result.type == "quiz"
    assert result.title == "Reading quiz"
    assert result.message == "Questions use the current passage."
    assert len(result.payload["questions"]) == 3
    assert result.payload["questions"][0] == {
        "id": "q_1",
        "prompt": "Which phrase does the passage verify?",
        "choices": [
            "An unrelated phrase",
            "A checked phrase",
            "A guessed phrase",
            "An omitted phrase",
        ],
        "correct_choice_index": 1,
    }
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_quiz_retries_an_empty_model_answer_with_lower_reasoning(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return "" if len(calls) == 1 else _model_response()

    monkeypatch.setattr("deeptutor.reading.quiz.complete", complete)
    result = await ReadingQuizExtension().run_action("start", _context())

    assert len(result.payload["questions"]) == 3
    assert [call["reasoning_effort"] for call in calls] == [
        None,
        RETRY_REASONING_EFFORT,
    ]
    assert calls[0]["prompt"] == calls[1]["prompt"]


@pytest.mark.asyncio
async def test_quiz_stops_after_two_empty_model_answers(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return ""

    monkeypatch.setattr("deeptutor.reading.quiz.complete", complete)
    with pytest.raises(ValueError, match="invalid JSON"):
        await ReadingQuizExtension().run_action("start", _context())

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_quiz_bounds_and_centers_the_verified_context(monkeypatch):
    text = "".join(f"sentence {index} " for index in range(2_000))
    selection = "sentence 1999"
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return _model_response(evidence=selection)

    monkeypatch.setattr("deeptutor.reading.quiz.complete", complete)
    await ReadingQuizExtension().run_action(
        "start",
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
async def test_missing_visible_text_fails_before_an_llm_call(monkeypatch):
    async def complete(**_kwargs):
        pytest.fail("missing visible text must not invoke the model")

    monkeypatch.setattr("deeptutor.reading.quiz.complete", complete)
    with pytest.raises(ValueError, match="requires visible text"):
        await ReadingQuizExtension().run_action(
            "start",
            ReadingContext(
                material_id="material",
                locator=1,
                visible_text=" ",
            ),
        )


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        json.dumps({"questions": []}),
        json.dumps(
            {
                "questions": [
                    {
                        "prompt": "Which phrase does the passage verify?",
                        "choices": [
                            "A checked phrase",
                            "A checked phrase",
                            "A guessed phrase",
                            "An omitted phrase",
                        ],
                        "correct_choice_index": 0,
                        "evidence": "verified phrase supports the answer",
                    }
                ]
                * 3
            }
        ),
        _model_response(evidence="outside facts are forbidden"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_or_ungrounded_model_output_is_rejected(monkeypatch, response):
    async def complete(**_kwargs):
        return response

    monkeypatch.setattr("deeptutor.reading.quiz.complete", complete)
    with pytest.raises(ValueError):
        await ReadingQuizExtension().run_action("start", _context())


def test_quiz_is_registered_as_a_packaged_extension():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    group = project["project"]["entry-points"]["deeptutor.reading_extensions"]

    assert group["quiz"] == "deeptutor.reading.quiz:ReadingQuizExtension"


def _client(monkeypatch) -> TestClient:
    registry = ReadingExtensionRegistry([ReadingQuizExtension()])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    return TestClient(app)


def test_quiz_crosses_the_api_boundary_with_stored_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text(
        "Stored passage where a verified phrase supports the answer.",
        encoding="utf-8",
    )
    material = ReadingStore().ingest(source)
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ""
        return _model_response(evidence="verified phrase supports the answer")

    monkeypatch.setattr("deeptutor.reading.quiz.complete", complete)
    client = _client(monkeypatch)
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}/extensions/quiz/actions/start",
            json={
                "locator": 1,
                "selection": "verified phrase supports the answer",
                "visible_text": "forged phrase",
                "locale": "en",
            },
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "quiz"
    assert len(body["payload"]["questions"]) == 3
    assert len(calls) == 2
    prompt = json.loads(calls[1]["prompt"])
    assert prompt["selection"] == "verified phrase supports the answer"
    assert (
        "Stored passage where a verified phrase supports the answer."
        in prompt["surrounding_context"]
    )
    assert "forged phrase" not in prompt["surrounding_context"]


@pytest.mark.asyncio
async def test_evidence_matches_across_margin_line_numbers(monkeypatch):
    """A review copy's line numbers sit on lines of their own in the unit text;
    a model quoting the sentence leaves them out and rejoins the hyphenated
    word, and that is still a quote from the page."""
    context = ReadingContext(
        material_id="material",
        locator=1,
        locale="en",
        visible_text=(
            "while existing RAG systems fall short in\n3\ndelivering personalized, "
            "guided feedback. To bridge this gap, we present DeepTu-\n4\ntor, a fully "
            "open-source agentic framework"
        ),
    )

    async def complete(**_kwargs):
        return _model_response(
            evidence="fall short in delivering personalized, guided feedback. "
            "To bridge this gap, we present DeepTutor"
        )

    monkeypatch.setattr("deeptutor.reading.quiz.complete", complete)
    result = await ReadingQuizExtension().run_action("start", context)
    assert len(result.payload["questions"]) == 3
