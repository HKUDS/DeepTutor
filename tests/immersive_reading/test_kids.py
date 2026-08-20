"""Security and supervision contracts for the child reading experience."""

from __future__ import annotations

import asyncio
import io
import time
from types import SimpleNamespace
import zipfile

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from deeptutor.immersive_reading.models import KidsQuizQuestion, KidsQuizResult
from deeptutor.immersive_reading.service import get_kids_manager


@pytest.fixture
def kids_manager(reading_service, monkeypatch):
    import deeptutor.immersive_reading.service as service_module

    service_module._kids_manager = None
    monkeypatch.setattr(
        service_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="test-model",
            binding="test-binding",
            context_window=128_000,
            max_tokens=4_096,
        ),
    )
    manager = get_kids_manager()
    yield manager
    service_module._kids_manager = None


@pytest.fixture
def client(reading_service, kids_manager, monkeypatch) -> TestClient:
    import deeptutor.api.routers.kids as router_module
    import deeptutor.api.routers.kids_admin as admin_router_module

    monkeypatch.setattr(router_module, "get_immersive_reading_service", lambda: reading_service)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/kids")
    app.include_router(admin_router_module.router, prefix="/api/v1/kids-admin")
    return TestClient(app)


@pytest.fixture
def protected_profile(document_with_cover, kids_manager):
    profile = kids_manager.create_profile("Ada", birth_date="2018-01-01", parent_pin="1234")
    kids_manager.assign_book(
        profile.id, document_with_cover["id"], available_through_section_index=2
    )
    return profile


@pytest.fixture
def document_with_cover(reading_service, imported_document):
    (reading_service._document_root(imported_document["id"]) / "cover.png").write_bytes(
        b"fake-cover"
    )
    return imported_document


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def child_token(client: TestClient, profile_id: str, pin: str = "1234") -> str:
    response = client.post(
        "/api/v1/kids/parent-unlock",
        json={"profile_id": profile_id, "pin": pin},
    )
    assert response.status_code == 200
    return response.json()["token"]


def test_assignment_requires_explicit_parent_content_confirmation(
    client: TestClient,
    kids_manager,
    imported_document: dict,
    protected_profile,
) -> None:
    profile_id = protected_profile.id
    document_id = imported_document["id"]
    kids_manager.unassign_book(profile_id, document_id)

    unconfirmed = client.post(
        f"/api/v1/kids-admin/profiles/{profile_id}/books",
        json={"document_id": document_id, "content_confirmed": False},
    )
    assert unconfirmed.status_code == 422

    confirmed = client.post(
        f"/api/v1/kids-admin/profiles/{profile_id}/books",
        json={"document_id": document_id, "content_confirmed": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["assignment"]["content_confirmed"] is True

    kids_manager.update_assignment(profile_id, document_id, content_confirmed=False)
    assert kids_manager.list_assignments(profile_id)[0].content_confirmed is False
    token = child_token(client, profile_id)
    blocked = client.get(f"/api/v1/kids/books/{document_id}", headers=auth_headers(token))
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "parent_confirmation_required"


def test_child_resources_require_a_persisted_device_session(
    client: TestClient, imported_document: dict, protected_profile
) -> None:
    document_id = imported_document["id"]

    assert client.get("/api/v1/kids/library").status_code == 401
    assert (
        client.get(
            "/api/v1/kids/library", headers={"X-Profile-Id": protected_profile.id}
        ).status_code
        == 401
    )
    assert client.get(f"/api/v1/kids/books/{document_id}/cover").status_code == 401

    response = client.post("/api/v1/kids/select-profile", json={"profile_id": protected_profile.id})
    assert response.status_code == 403
    assert (
        client.post(
            "/api/v1/kids/parent-unlock",
            json={"profile_id": protected_profile.id, "pin": "0000"},
        ).status_code
        == 403
    )

    response = client.post(
        "/api/v1/kids/parent-unlock",
        json={"profile_id": protected_profile.id, "pin": "1234"},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    assert client.get("/api/v1/kids/library", headers=auth_headers(token)).status_code == 200
    assert (
        client.get(
            f"/api/v1/kids/books/{document_id}/cover", headers=auth_headers(token)
        ).status_code
        == 200
    )

    assert (
        client.post("/api/v1/kids/session/logout", headers=auth_headers(token)).status_code == 200
    )
    assert client.get("/api/v1/kids/library", headers=auth_headers(token)).status_code == 401


def test_children_receive_an_epub_limited_to_assigned_sections(
    client: TestClient, imported_document: dict, protected_profile
) -> None:
    token = client.post(
        "/api/v1/kids/parent-unlock",
        json={"profile_id": protected_profile.id, "pin": "1234"},
    ).json()["token"]
    response = client.get(
        f"/api/v1/kids/books/{imported_document['id']}/epub",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "OEBPS/chapter-1.xhtml" in names
        assert "OEBPS/chapter-2.xhtml" in names
        combined = "\n".join(
            archive.read(name).decode("utf-8") for name in names if name.endswith(".xhtml")
        )
        assert "Chapter 2" in combined
        assert "Chapter 3" not in combined

    later_section = imported_document["sections"][3]["id"]
    assert (
        client.get(
            f"/api/v1/kids/books/{imported_document['id']}/sections/{later_section}",
            headers=auth_headers(token),
        ).status_code
        == 403
    )


def test_daily_limit_uses_capped_server_elapsed_time(kids_manager, protected_profile) -> None:
    _session, token = kids_manager.create_device_session(protected_profile.id)
    session = kids_manager.validate_device_session(token)
    assert session is not None
    session.last_seen_at = time.time() - 60

    document_id = kids_manager.list_assignments(protected_profile.id)[0].document_id
    status = kids_manager.record_reading_heartbeat(session, document_id=document_id)

    assert status["used_seconds"] == 60
    assert status["remaining_seconds"] == protected_profile.daily_limit_minutes * 60 - 60
    assert kids_manager.load_kids_progress(
        protected_profile.id, document_id
    ).time_spent_seconds == pytest.approx(60, abs=0.1)

    session.last_seen_at = time.time() - 600
    status = kids_manager.record_reading_heartbeat(session)
    assert status["used_seconds"] == 240  # 60 initial + 180-second cap


def test_assigning_books_to_multiple_profiles_preserves_every_assignment(
    kids_manager, imported_document, protected_profile
) -> None:
    second_profile = kids_manager.create_profile("Grace", birth_date="2018-05-01")
    first = kids_manager.assign_book(
        protected_profile.id,
        imported_document["id"],
        available_through_section_index=2,
        content_confirmed=True,
    )
    second = kids_manager.assign_book(
        second_profile.id,
        imported_document["id"],
        available_through_section_index=2,
        content_confirmed=True,
    )

    first_assignments = kids_manager.list_assignments(protected_profile.id)
    second_assignments = kids_manager.list_assignments(second_profile.id)

    assert [assignment.id for assignment in first_assignments] == [first.id]
    assert [assignment.id for assignment in second_assignments] == [second.id]
    assert len(kids_manager.list_assignments()) == 2


def test_each_completed_chapter_gets_a_three_question_quiz_and_book_summary(
    client: TestClient,
    reading_service,
    kids_manager,
    imported_document: dict,
    protected_profile,
) -> None:
    document_id = imported_document["id"]
    chapter_one = imported_document["sections"][1]
    chapter_two = imported_document["sections"][2]
    token = child_token(client, protected_profile.id)
    headers = auth_headers(token)

    opening = client.put(
        f"/api/v1/kids/books/{document_id}/progress",
        json={"section_id": chapter_one["id"], "scroll_percent": 50},
        headers=headers,
    )
    assert opening.status_code == 200
    assert (
        client.post(
            f"/api/v1/kids/books/{document_id}/quiz",
            json={"section_id": chapter_one["id"]},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/kids/books/{document_id}/progress",
            json={"section_id": chapter_one["id"], "scroll_percent": 90, "completed": True},
            headers=headers,
        ).status_code
        == 403
    )

    completed = client.put(
        f"/api/v1/kids/books/{document_id}/progress",
        json={"section_id": chapter_one["id"], "scroll_percent": 100, "completed": True},
        headers=headers,
    )
    assert completed.status_code == 200
    assert chapter_one["id"] in completed.json()["progress"]["completed_section_ids"]

    blocked_next = client.put(
        f"/api/v1/kids/books/{document_id}/progress",
        json={"section_id": chapter_two["id"], "scroll_percent": 20},
        headers=headers,
    )
    assert blocked_next.status_code == 409
    assert blocked_next.json()["detail"]["code"] == "chapter_quiz_required"
    assert blocked_next.json()["detail"]["section_id"] == chapter_one["id"]

    for section, answer in ((chapter_one, 0), (chapter_two, 1)):
        kinds = ("recall", "sequence", "vocabulary")
        reading_service._save_kids_quiz_cache(
            document_id,
            section["id"],
            KidsQuizResult(
                document_id=document_id,
                section_id=section["id"],
                questions=[
                    KidsQuizQuestion(
                        id=f"q{i}",
                        kind=kind,
                        question=f"Question {i}?",
                        choices=["yes", "no", "maybe", "never"],
                        answer_index=answer,
                    )
                    for i, kind in enumerate(kinds, 1)
                ],
                age_band="6-8",
                available=True,
                content_hash=reading_service._content_hash(
                    reading_service.get_section(document_id, section["id"])["content"]
                ),
                prompt_version=reading_service.KIDS_QUIZ_PROMPT_VERSION,
            ),
        )

    first_quiz = client.post(
        f"/api/v1/kids/books/{document_id}/quiz",
        json={"section_id": chapter_one["id"]},
        headers=headers,
    )
    assert first_quiz.status_code == 200
    assert len(first_quiz.json()["questions"]) == 3
    first_grade = client.post(
        f"/api/v1/kids/books/{document_id}/quiz/submit",
        json={"section_id": chapter_one["id"], "answers": [0, 0, 0]},
        headers=headers,
    )
    assert first_grade.status_code == 200
    assert first_grade.json()["total"] == 3
    assert first_grade.json()["section_id"] == chapter_one["id"]
    assert first_grade.json()["earned_stars"] == 3
    opened_after_quiz = client.get(
        f"/api/v1/kids/books/{document_id}/sections/{chapter_two['id']}",
        headers=headers,
    )
    assert opened_after_quiz.status_code == 200

    # A sequential chapter transition is a valid completion signal for the
    # chapter the child just left, even though relocation now reports chapter 2.
    skipped_chapter = client.put(
        f"/api/v1/kids/books/{document_id}/progress",
        json={
            "section_id": chapter_two["id"],
            "scroll_percent": 100,
            "completed": True,
        },
        headers=headers,
    )
    assert skipped_chapter.status_code == 409
    assert (
        client.post(
            f"/api/v1/kids/books/{document_id}/quiz",
            json={"section_id": chapter_two["id"]},
            headers=headers,
        ).status_code
        == 403
    )

    opened_two = client.put(
        f"/api/v1/kids/books/{document_id}/progress",
        json={"section_id": chapter_two["id"], "scroll_percent": 40},
        headers=headers,
    )
    assert opened_two.status_code == 200
    assert (
        client.post(
            f"/api/v1/kids/books/{document_id}/quiz/submit",
            json={"section_id": chapter_two["id"], "answers": [0, 0, 0]},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/kids/books/{document_id}/progress",
            json={"section_id": chapter_two["id"], "scroll_percent": 100, "completed": True},
            headers=headers,
        ).status_code
        == 200
    )
    second_quiz = client.post(
        f"/api/v1/kids/books/{document_id}/quiz",
        json={"section_id": chapter_two["id"]},
        headers=headers,
    )
    assert second_quiz.status_code == 200
    assert len(second_quiz.json()["questions"]) == 3
    second_grade = client.post(
        f"/api/v1/kids/books/{document_id}/quiz/submit",
        json={"section_id": chapter_two["id"], "answers": [1, 1, 1]},
        headers=headers,
    )
    assert second_grade.status_code == 200
    assert second_grade.json()["earned_stars"] == 3
    assert second_grade.json()["is_complete"] is True

    final_book = client.get(f"/api/v1/kids/books/{document_id}", headers=headers)
    assert final_book.status_code == 200
    final_progress = final_book.json()["progress"]
    assert final_progress["quiz_section_attempts"][chapter_one["id"]] == 1
    assert final_progress["quiz_section_attempts"][chapter_two["id"]] == 1
    assert final_book.json()["document"]["is_complete"] is True


def test_deterministic_fallback_quiz_cache_is_reused(
    reading_service,
    imported_document: dict,
    monkeypatch,
) -> None:
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
                KidsQuizQuestion(
                    id=f"q{i}",
                    kind=kind,
                    question=f"Question {i}?",
                    choices=["Correct", "Wrong one", "Wrong two", "Wrong three"],
                    answer_index=0,
                )
                for i, kind in enumerate(("recall", "sequence", "vocabulary"), 1)
            ],
            age_band="6-8",
            available=True,
            content_hash=reading_service._content_hash(content),
            model="source-fallback",
            prompt_version=service_module.KIDS_FALLBACK_QUIZ_PROMPT_VERSION,
        ),
    )

    async def fail_llm(*args, **kwargs):
        raise AssertionError("cached fallback quiz must not call the LLM")

    monkeypatch.setattr(service_module, "complete", fail_llm)
    result = asyncio.run(
        reading_service.generate_kids_quiz(document_id, section["id"], age_band="6-8")
    )
    assert len(result.questions) == 3


def test_completion_and_quiz_stars_are_idempotent(
    client: TestClient,
    reading_service,
    kids_manager,
    imported_document: dict,
    protected_profile,
) -> None:
    document_id = imported_document["id"]
    section_id = imported_document["sections"][1]["id"]

    first = kids_manager.mark_section_completed(protected_profile.id, document_id, section_id)
    second = kids_manager.mark_section_completed(protected_profile.id, document_id, section_id)
    assert first.total_stars == 1
    assert second.total_stars == 1

    reading_service._save_kids_quiz_cache(
        document_id,
        section_id,
        KidsQuizResult(
            document_id=document_id,
            section_id=section_id,
            questions=[
                KidsQuizQuestion(
                    id="q1",
                    kind="recall",
                    question="Word?",
                    choices=["yes", "no", "maybe", "never"],
                    answer_index=0,
                ),
                KidsQuizQuestion(
                    id="q2",
                    kind="sequence",
                    question="Other?",
                    choices=["yes", "no", "maybe", "never"],
                    answer_index=1,
                ),
                KidsQuizQuestion(
                    id="q3",
                    kind="vocabulary",
                    question="Last?",
                    choices=["yes", "no", "maybe", "never"],
                    answer_index=0,
                ),
            ],
            age_band="6-8",
            available=True,
            content_hash=reading_service._content_hash(
                reading_service.get_section(document_id, section_id)["content"]
            ),
            prompt_version=reading_service.KIDS_QUIZ_PROMPT_VERSION,
        ),
    )
    token = client.post(
        "/api/v1/kids/parent-unlock",
        json={"profile_id": protected_profile.id, "pin": "1234"},
    ).json()["token"]
    payload = {"section_id": section_id, "answers": [0, 1, 0]}
    first_quiz = client.post(
        f"/api/v1/kids/books/{document_id}/quiz/submit",
        json=payload,
        headers=auth_headers(token),
    ).json()
    second_quiz = client.post(
        f"/api/v1/kids/books/{document_id}/quiz/submit",
        json=payload,
        headers=auth_headers(token),
    ).json()

    assert first_quiz["stars"] == 3
    assert first_quiz["earned_stars"] == 3
    assert second_quiz["stars"] == 3
    assert second_quiz["earned_stars"] == 0
