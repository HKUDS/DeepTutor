"""Synthetic coverage for question-bound Reading help, without a model call."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading_extensions
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingExtensionManifest,
    ReadingExtensionRegistry,
    ReadingExtensionResult,
)
from deeptutor.services.path_service import PathService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def help_case(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "passage.txt"
    source.write_text("A verified phrase supports the answer.", encoding="utf-8")
    material = ReadingStore().ingest(source)
    stores = {
        name: SQLiteSessionStore(db_path=tmp_path / f"{name}.db") for name in ("learner", "other")
    }
    asyncio.run(stores["learner"].create_session(session_id="help-session"))
    questions = [
        {
            "id": qid,
            "prompt": "Which phrase?",
            "choices": ["made up", "verified"],
            "correct_choice_index": 1,
        }
        for qid in ("generation:one", "generation:two")
    ]
    asyncio.run(stores["learner"].put_reading_quiz_pending(material.material_id, 1, questions))
    current_account = ContextVar("quiz_help_test_account", default="learner")
    monkeypatch.setattr(
        "deeptutor.services.session.get_sqlite_session_store",
        lambda: stores[current_account.get()],
    )
    monkeypatch.setattr(reading_extensions, "assert_learning_material", lambda _: None)
    calls = []

    async def run(action, context):
        calls.append((action, context))
        return ReadingExtensionResult(type="card", payload={"steps": ["Read the selected text."]})

    extension = SimpleNamespace(
        manifest=ReadingExtensionManifest(
            id="guided_learning",
            version="1",
            name="Guidance",
            actions=[ReadingAction(id="guide", label="Guide me", requires=["selection"])],
            result_types=["card"],
        ),
        run_action=run,
    )
    registry = ReadingExtensionRegistry([extension])
    monkeypatch.setattr(reading_extensions, "get_reading_extension_registry", lambda: registry)
    app = FastAPI()

    @app.middleware("http")
    async def account_scope(request, call_next):
        token = current_account.set(request.headers.get("X-Test-Account", "learner"))
        try:
            return await call_next(request)
        finally:
            current_account.reset(token)

    app.include_router(reading_extensions.router, prefix="/api/reading")
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            material=material.material_id,
            stores=stores,
            calls=calls,
            extension=extension,
            questions=questions,
        )
    registry.close()
    PathService.reset_instance()


def _help(case, **overrides):
    payload = {
        "locator": 1,
        "selection": "verified phrase",
        "locale": "en",
        "question_id": "generation:one",
        "help_request_id": "help-request-1",
    }
    payload.update(overrides)
    return case.client.post(
        f"/api/reading/materials/{case.material}/extensions/guided_learning/actions/guide",
        json=payload,
    )


def _answer(case, question_id="generation:one", **overrides):
    payload = {
        "locator": 1,
        "session_id": "help-session",
        "answers": [{"question_id": question_id, "selected_index": 1}],
    }
    payload.update(overrides)
    return case.client.post(
        f"/api/reading/materials/{case.material}/extensions/quiz/answers",
        json=payload,
    )


def test_successful_help_is_question_bound_and_replayed_without_counting_twice(help_case):
    case = help_case
    first = _help(case)
    assert first.status_code == 200, first.text
    assert first.json()["quiz_help"] == {"question_id": "generation:one", "hints_used": 1}
    replay = _help(case)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert len(case.calls) == 1
    events = asyncio.run(case.stores["learner"].list_reading_quiz_help_events(case.material))
    assert len(events) == 1
    assert events[0]["help_kind"] == "guided_learning:guide"
    assert _answer(case).status_code == 200
    assert _answer(case, "generation:two").status_code == 200
    entries = asyncio.run(case.stores["learner"].list_notebook_entries())["items"]
    by_id = {row["question_id"]: row for row in entries}
    assert by_id["generation:one"]["hints_used"] == 1
    assert by_id["generation:two"]["hints_used"] == 0
    assert by_id["generation:one"]["is_correct"] is True
    assert (
        asyncio.run(case.stores["learner"].list_reading_quiz_rewards(case.material))[0]["stars"]
        == 2
    )


@pytest.mark.parametrize("field,value", [("question_id", "old:one"), ("locator", 2)])
def test_unknown_or_wrong_locator_question_rejected_before_help(help_case, field, value):
    response = _help(help_case, **{field: value})
    assert response.status_code in (400, 409)
    assert help_case.calls == []


def test_other_account_cannot_use_learner_question(help_case):
    case = help_case
    response = case.client.post(
        f"/api/reading/materials/{case.material}/extensions/guided_learning/actions/guide",
        headers={"X-Test-Account": "other"},
        json={
            "locator": 1,
            "selection": "verified phrase",
            "question_id": "generation:one",
            "help_request_id": "other-help",
        },
    )
    assert response.status_code == 409
    assert case.calls == []


def test_failed_help_is_not_counted_and_same_request_can_retry(help_case):
    case = help_case
    successful_run = case.extension.run_action

    async def fail(*_):
        raise ValueError("Synthetic provider failure")

    case.extension.run_action = fail
    assert _help(case).status_code == 503
    assert _answer(case).status_code == 200
    entries = asyncio.run(case.stores["learner"].list_notebook_entries())["items"]
    assert entries[0]["hints_used"] == 0
    case.extension.run_action = successful_run
    assert _help(case).json()["quiz_help"]["hints_used"] == 1
    assert _answer(case, submission_id="after-help").status_code == 200
    attempts = asyncio.run(case.stores["learner"].list_assessment_attempts("help-session"))
    assert [row["hints_used"] for row in attempts] == [0, 1]
    asyncio.run(case.stores["learner"].put_reading_quiz_pending(case.material, 1, []))
    events = asyncio.run(case.stores["learner"].list_reading_quiz_help_events(case.material))
    assert len(events) == 1
    assert events[0]["question_id"] == "generation:one"
    assert asyncio.run(case.stores["learner"].list_assessment_attempts("help-session")) == attempts


def test_regeneration_during_help_does_not_record_or_return_success(help_case):
    case = help_case

    async def regenerate(*_):
        await case.stores["learner"].put_reading_quiz_pending(case.material, 1, [])
        return ReadingExtensionResult(type="card", payload={"steps": ["A late help result"]})

    case.extension.run_action = regenerate
    response = _help(case)
    assert response.status_code == 409
    assert "quiz_help" not in response.json()


def test_request_id_cannot_be_reused_for_another_selection(help_case):
    assert _help(help_case).status_code == 200
    assert _help(help_case, selection="supports the answer").status_code == 409
    assert len(help_case.calls) == 1


def test_unbound_reading_help_does_not_mark_a_question(help_case):
    case = help_case
    response = _help(case, question_id="", help_request_id="")
    assert response.status_code == 200
    assert "quiz_help" not in response.json()
    assert _answer(case).status_code == 200
    assert (
        asyncio.run(case.stores["learner"].list_notebook_entries())["items"][0]["hints_used"] == 0
    )


def test_question_help_requires_permission_and_verified_selection(help_case, monkeypatch):
    case = help_case
    assert _help(case, selection="not in this reading unit").status_code == 400
    monkeypatch.setattr(reading_extensions, "allowed_reading_extensions", lambda: {"quiz"})
    assert _help(case).status_code == 403
    assert case.calls == []


@pytest.mark.parametrize("field", ["question_id", "help_request_id"])
def test_question_help_requires_both_ids(help_case, field):
    assert _help(help_case, **{field: " "}).status_code == 422
    assert help_case.calls == []


def test_timeout_does_not_count_and_releases_request(help_case, monkeypatch):
    case = help_case
    successful_run = case.extension.run_action

    async def slow(*_):
        await asyncio.sleep(1)

    monkeypatch.setattr(reading_extensions, "ACTION_TIMEOUT_S", 0.01)
    case.extension.run_action = slow
    assert _help(case).status_code == 503
    case.extension.run_action = successful_run
    assert _help(case).json()["quiz_help"]["hints_used"] == 1


def test_revoked_policy_during_help_does_not_persist_success(help_case, monkeypatch):
    case = help_case

    async def revoke(*_):
        monkeypatch.setattr(reading_extensions, "allowed_reading_extensions", lambda: {"quiz"})
        return ReadingExtensionResult(type="card", payload={"steps": ["Late result"]})

    case.extension.run_action = revoke
    assert _help(case).status_code == 403
    assert _answer(case).status_code == 200
    entries = asyncio.run(case.stores["learner"].list_notebook_entries())["items"]
    assert entries[0]["hints_used"] == 0


def test_quiz_permission_is_required_even_when_help_extension_is_allowed(help_case, monkeypatch):
    monkeypatch.setattr(
        reading_extensions, "allowed_reading_extensions", lambda: {"guided_learning"}
    )
    assert _help(help_case).status_code == 403
    assert help_case.calls == []


@pytest.mark.parametrize("fail_provider", [False, True])
def test_cleanup_failure_does_not_replace_response(help_case, monkeypatch, fail_provider):
    case = help_case
    store = case.stores["learner"]
    original = store.reading_quiz_help
    aborts = []

    async def failing_cleanup(*args, **kwargs):
        if args[6] == "abort":
            aborts.append(True)
            raise OSError("Synthetic cleanup failure")
        return await original(*args, **kwargs)

    monkeypatch.setattr(store, "reading_quiz_help", failing_cleanup)
    if fail_provider:

        async def fail(*_):
            raise ValueError("Synthetic provider failure")

        case.extension.run_action = fail
    response = _help(case)
    assert response.status_code == (503 if fail_provider else 200)
    assert len(aborts) == int(fail_provider)
    if not fail_provider:
        assert response.json()["quiz_help"]["hints_used"] == 1
