"""Tests for Family Kids Library isolation, parent review flow, and device pairing."""

from __future__ import annotations

import io

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from deeptutor.immersive_reading.service import ImmersiveReadingService, get_kids_manager


@pytest.fixture
def client(reading_service: ImmersiveReadingService, monkeypatch) -> TestClient:
    import deeptutor.api.routers.immersive_reading as ir_router_module
    import deeptutor.api.routers.kids as kids_router_module
    import deeptutor.api.routers.kids_admin as admin_router_module

    monkeypatch.setattr(ir_router_module, "get_immersive_reading_service", lambda: reading_service)
    monkeypatch.setattr(kids_router_module, "get_immersive_reading_service", lambda: reading_service)
    monkeypatch.setattr(admin_router_module, "get_immersive_reading_service", lambda: reading_service)

    app = FastAPI()
    app.include_router(ir_router_module.router, prefix="/api/v1/immersive-reading")
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    app.include_router(admin_router_module.router, prefix="/api/v1/kids-admin")
    return TestClient(app)


def test_library_isolation_and_review_flow(client: TestClient, reading_service: ImmersiveReadingService) -> None:
    # 1. Parent creates a child profile
    manager = get_kids_manager()
    profile = manager.create_profile("Bao", birth_date="2018-07-16")

    # 2. Upload an adult personal book
    adult_book_content = b"# Adult Chapter 1\nComplex adult literature passage."
    res_adult = client.post(
        "/api/v1/immersive-reading/documents/import",
        files={"file": ("adult-novel.txt", io.BytesIO(adult_book_content), "text/plain")},
    )
    assert res_adult.status_code == 200
    adult_doc_id = res_adult.json()["document"]["id"]

    # 3. Upload a kids book via kids-admin import
    kids_book_content = b"# Chapter 1\nLittle Bear goes to the forest with a blue compass."
    res_kids = client.post(
        "/api/v1/kids-admin/library/import",
        files={"file": ("little-bear.txt", io.BytesIO(kids_book_content), "text/plain")},
        data={"auto_approve": "false", "age_bands": "6-8"},
    )
    assert res_kids.status_code == 200
    kids_doc_id = res_kids.json()["document"]["id"]

    # 4. Check Personal Bookshelf: must contain adult book, must NOT contain kids book
    personal_res = client.get("/api/v1/immersive-reading/documents")
    assert personal_res.status_code == 200
    personal_ids = [d["id"] for d in personal_res.json()["documents"]]
    assert adult_doc_id in personal_ids
    assert kids_doc_id not in personal_ids

    # 5. Check Kids Family Library: must contain kids book with status 'pending'
    kids_lib_res = client.get("/api/v1/kids-admin/library")
    assert kids_lib_res.status_code == 200
    kids_lib_items = kids_lib_res.json()["items"]
    kids_item = next(item for item in kids_lib_items if item["document"]["id"] == kids_doc_id)
    assert kids_item["entry"]["kids_review_status"] == "pending"

    # 6. Device pairing for Bao
    pair_res = client.post("/api/v1/kids-admin/devices/pair", json={"profile_id": profile.id})
    assert pair_res.status_code == 200
    code = pair_res.json()["pairing"]["code"]
    assert len(code) == 6

    # Child redeems pairing code
    redeem_res = client.post("/api/v1/kids/pair", json={"code": code, "device_name": "Bao iPad"})
    assert redeem_res.status_code == 200
    child_token = redeem_res.json()["token"]
    assert redeem_res.json()["profile"]["id"] == profile.id

    # 7. Parent reviews and approves the kids book, then assigns it
    review_res = client.put(
        f"/api/v1/kids-admin/library/{kids_doc_id}/review",
        json={"status": "approved", "approved_age_bands": ["6-8"], "reviewer_note": "Safe and fun"},
    )
    assert review_res.status_code == 200
    assert review_res.json()["entry"]["kids_review_status"] == "approved"

    assign_res = client.post(
        f"/api/v1/kids-admin/library/{kids_doc_id}/assign",
        json={"profile_ids": [profile.id], "content_confirmed": True},
    )
    assert assign_res.status_code == 200
    assert profile.id in assign_res.json()["assigned_profile_ids"]

    # 8. Child accesses library
    headers = {"Authorization": f"Bearer {child_token}"}
    child_lib_res = client.get("/api/v1/kids/library", headers=headers)
    assert child_lib_res.status_code == 200
    child_books = child_lib_res.json()["library"]
    assert len(child_books) == 1
    assert child_books[0]["assignment"]["document_id"] == kids_doc_id

    # 9. Cross-library sharing: share adult book to kids library
    share_res = client.post(
        f"/api/v1/kids-admin/library/from-personal/{adult_doc_id}",
        json={"auto_approve": True, "approved_age_bands": ["9-12"]},
    )
    assert share_res.status_code == 200
    assert "kids_family" in share_res.json()["entry"]["scopes"]
    assert "personal" in share_res.json()["entry"]["scopes"]

    # 10. Archive kids book: child library should no longer show it
    archive_res = client.post(f"/api/v1/kids-admin/library/{kids_doc_id}/archive")
    assert archive_res.status_code == 200
    child_lib_after_archive = client.get("/api/v1/kids/library", headers=headers)
    assert len(child_lib_after_archive.json()["library"]) == 0
