# HTTP contract tests for kids and kids_admin routers

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from deeptutor.immersive_reading.service import ImmersiveReadingService, KidsManager
from deeptutor.services.path_service import PathService


@pytest.fixture
def app_and_client(tmp_path, monkeypatch):
    import deeptutor.api.routers.immersive_reading as ir_router
    import deeptutor.api.routers.kids as kids_router
    import deeptutor.api.routers.kids_admin as kids_admin_router
    import deeptutor.immersive_reading.service as service_module

    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
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

    async def mock_llm_fail(**kwargs):
        raise ConnectionError("No network during test")

    monkeypatch.setattr(service_module, "complete", mock_llm_fail)

    ir_service = ImmersiveReadingService()
    kids_manager = KidsManager()

    monkeypatch.setattr(service_module, "get_immersive_reading_service", lambda: ir_service)
    monkeypatch.setattr(service_module, "get_kids_manager", lambda: kids_manager)
    monkeypatch.setattr(kids_router, "get_immersive_reading_service", lambda: ir_service)
    monkeypatch.setattr(kids_router, "get_kids_manager", lambda: kids_manager)
    monkeypatch.setattr(kids_admin_router, "get_immersive_reading_service", lambda: ir_service)
    monkeypatch.setattr(kids_admin_router, "get_kids_manager", lambda: kids_manager)
    monkeypatch.setattr(ir_router, "get_immersive_reading_service", lambda: ir_service)

    app = FastAPI()
    app.include_router(kids_admin_router.router, prefix="/api/v1/kids-admin")
    app.include_router(kids_router.router, prefix="/api/v1/kids")
    app.include_router(ir_router.router, prefix="/api/v1/immersive-reading")

    client = TestClient(app)
    return client, ir_service, kids_manager


def test_kids_admin_profile_crud_and_pin(app_and_client) -> None:
    client, _, _ = app_and_client

    # 1. Create profile
    res = client.post(
        "/api/v1/kids-admin/profiles",
        json={
            "name": "Emma",
            "avatar": "🦄",
            "birth_date": "2019-06-01",
            "help_language": "en",
            "narration_rate": 0.8,
            "daily_limit_minutes": 25,
            "parent_pin": "5678",
        },
    )
    assert res.status_code == 200
    data = res.json()["profile"]
    assert data["name"] == "Emma"
    assert data["avatar"] == "🦄"
    assert data["has_pin"] is True
    profile_id = data["id"]

    # 2. List profiles
    res = client.get("/api/v1/kids-admin/profiles")
    assert res.status_code == 200
    assert len(res.json()["profiles"]) == 1

    # 3. Verify PIN
    res = client.post(
        f"/api/v1/kids-admin/profiles/{profile_id}/verify-pin",
        json={"pin": "5678"},
    )
    assert res.status_code == 200
    assert res.json()["verified"] is True

    # 4. Update profile
    res = client.put(
        f"/api/v1/kids-admin/profiles/{profile_id}",
        json={"name": "Emma Rose", "daily_limit_minutes": 30},
    )
    assert res.status_code == 200
    assert res.json()["profile"]["name"] == "Emma Rose"


def test_kids_admin_book_assignment_and_adult_library(app_and_client) -> None:
    client, ir_service, kids_manager = app_and_client

    padding = "A peaceful morning in the farm barn with sunny skies and quiet breeze. " * 8
    source = (
        "Title page and preface.\n\n"
        f"# Chapter 1\nBefore Breakfast on the farm. {padding}\n\n"
        f"# Chapter 2\nWilbur the pig finds a new friend. {padding}\n\n"
        f"# Chapter 3\nEscape through the broken fence. {padding}"
    )
    doc = ir_service.import_document("charlotte.txt", source.encode("utf-8"))
    doc_id = doc["id"]
    profile = kids_manager.create_profile(name="Ben", birth_date="2018-03-01")

    # Adult library lists imported docs and assigned profile ids
    res = client.get("/api/v1/kids-admin/library")
    assert res.status_code == 200
    docs = res.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["id"] == doc_id

    # Assign book through Chapter 2 (index 2)
    res = client.post(
        f"/api/v1/kids-admin/profiles/{profile.id}/books",
        json={"document_id": doc_id, "available_through_section_index": 2},
    )
    assert res.status_code == 200
    assert res.json()["assignment"]["document_id"] == doc_id

    # List assigned books
    res = client.get(f"/api/v1/kids-admin/profiles/{profile.id}/books")
    assert res.status_code == 200
    lib = res.json()["library"]
    assert len(lib) == 1
    assert lib[0]["document"]["id"] == doc_id


def test_kids_child_auth_and_chapter_gating(app_and_client) -> None:
    client, ir_service, kids_manager = app_and_client

    padding = "Peter Rabbit ran across the green meadow looking for radishes and lettuce. " * 8
    source = (
        "Title page and publisher notes.\n\n"
        f"# Chapter 1\nPeter runs away into the garden. {padding}\n\n"
        f"# Chapter 2\nMr McGregor chases Peter with a rake. {padding}\n\n"
        f"# Chapter 3\nPeter escapes back home to his mother. {padding}"
    )
    doc = ir_service.import_document("peter_rabbit.txt", source.encode("utf-8"))
    doc_id = doc["id"]
    profile = kids_manager.create_profile(name="Peter", birth_date="2019-01-01", parent_pin="1234")
    # Gated through index 2 (Front Matter is 0, Chapter 1 is 1, Chapter 2 is 2)
    kids_manager.assign_book(profile.id, doc_id, available_through_section_index=2)

    # 1. Bootstrap
    res = client.get("/api/v1/kids/bootstrap")
    assert res.status_code == 200
    profiles = res.json()["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["has_pin"] is True

    # 2. Unlock with parent PIN
    res = client.post(
        "/api/v1/kids/parent-unlock",
        json={"profile_id": profile.id, "pin": "1234"},
    )
    assert res.status_code == 200
    token = res.json()["token"]
    assert token.startswith("kds_")

    headers = {"Authorization": f"Bearer {token}"}

    doc_id = doc["id"]
    # 3. Get book detail (allowed sections only: Front Matter, Chapter 1, Chapter 2)
    res = client.get(f"/api/v1/kids/books/{doc_id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["document"]["title"] == "peter_rabbit"
    assert len(data["document"]["sections"]) == 3

    # 4. Access allowed section (Chapter 1)
    sec_1 = doc["sections"][1]["id"]
    res = client.get(f"/api/v1/kids/books/{doc_id}/sections/{sec_1}", headers=headers)
    assert res.status_code == 200
    assert "Peter runs away" in res.json()["content"]

    # 5. Access disallowed section (Chapter 3, index 3) -> 403
    sec_3 = doc["sections"][3]["id"]
    res = client.get(f"/api/v1/kids/books/{doc_id}/sections/{sec_3}", headers=headers)
    assert res.status_code == 403
    assert "not available yet" in res.json()["detail"]


def test_kids_quiz_and_progress_flow(app_and_client) -> None:
    client, ir_service, kids_manager = app_and_client

    padding = "The cheerful little animals enjoyed the warm sunny day together in the yard. " * 8
    source = (
        "Title page and preface notes.\n\n"
        f"# Chapter 1\nThe little dog played with the big red ball under the sun. {padding}\n\n"
        f"# Chapter 2\nThe cat slept peacefully on the warm rug. {padding}\n\n"
        f"# Chapter 3\nThe bird flew high in the blue sky. {padding}"
    )
    doc = ir_service.import_document("animals.txt", source.encode("utf-8"))
    doc_id = doc["id"]
    profile = kids_manager.create_profile(name="Tommy", birth_date="2020-05-01")
    kids_manager.assign_book(profile.id, doc_id)

    # Select profile (no pin needed)
    res = client.post("/api/v1/kids/select-profile", json={"profile_id": profile.id})
    assert res.status_code == 200
    token = res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    sec_1 = doc["sections"][1]["id"]

    # 1. Update reading progress
    res = client.put(
        f"/api/v1/kids/books/{doc_id}/progress",
        headers=headers,
        json={
            "section_id": sec_1,
            "section_index": 1,
            "scroll_percent": 90.0,
            "epub_cfi": "cfi-123",
            "time_delta": 45.0,
            "completed": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["progress"]["completed_section_ids"] == [sec_1]

    # 2. Get quiz (falls back to deterministic sight-words quiz)
    res = client.post(
        f"/api/v1/kids/books/{doc_id}/quiz",
        headers=headers,
        json={"section_id": sec_1},
    )
    assert res.status_code == 200
    questions = res.json()["questions"]
    assert len(questions) >= 1
    # Check that answer_index is NOT leaked to child
    assert "answer_index" not in questions[0]

    # 3. Submit quiz with correct answers
    cached_quiz = ir_service._kids_quiz_path(doc_id, sec_1)
    import json

    with open(cached_quiz) as f:
        q_data = json.load(f)
    correct_answers = [q["answer_index"] for q in q_data["questions"]]

    res = client.post(
        f"/api/v1/kids/books/{doc_id}/quiz/submit",
        headers=headers,
        json={"section_id": sec_1, "answers": correct_answers},
    )
    assert res.status_code == 200
    grade = res.json()
    assert grade["score"] == len(correct_answers)
    assert grade["stars"] == 3
    assert len(grade["encouragements"]) > 0

    # 4. Verify learning report
    res = client.get(f"/api/v1/kids-admin/profiles/{profile.id}/report")
    assert res.status_code == 200
    report = res.json()
    assert report["total_stars"] == 3
    assert report["total_quiz_attempts"] == 1


def test_kids_translation_and_exit_verify(app_and_client) -> None:
    client, _, kids_manager = app_and_client
    import deeptutor.immersive_reading.service as service_module

    async def fake_translate(text, target_language="Chinese"):
        return f"翻译[{text}]到[{target_language}]"

    profile = kids_manager.create_profile(name="Lily", birth_date="2018-01-01", parent_pin="9999")
    res = client.post("/api/v1/kids/parent-unlock", json={"profile_id": profile.id, "pin": "9999"})
    token = res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    ir_service = service_module.get_immersive_reading_service()
    ir_service.translate = fake_translate

    # Translate
    res = client.post(
        "/api/v1/kids/translate",
        headers=headers,
        json={"text": "butterfly", "target_language": "Chinese"},
    )
    assert res.status_code == 200
    assert "翻译[butterfly]" in res.json()["translation"]

    # Exit verify with correct PIN
    res = client.post(
        "/api/v1/kids/exit-verify",
        json={"profile_id": profile.id, "pin": "9999"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # Exit verify with wrong PIN -> 403
    res = client.post(
        "/api/v1/kids/exit-verify",
        json={"profile_id": profile.id, "pin": "0000"},
    )
    assert res.status_code == 403
