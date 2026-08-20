"""Security and supervision contracts for the child reading experience."""

from __future__ import annotations

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

    monkeypatch.setattr(router_module, "get_immersive_reading_service", lambda: reading_service)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/kids")
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
                KidsQuizQuestion(id="q1", question="Word?", choices=["yes", "no"], answer_index=0),
                KidsQuizQuestion(id="q2", question="Other?", choices=["yes", "no"], answer_index=1),
            ],
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
    payload = {"section_id": section_id, "answers": [0, 1]}
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
