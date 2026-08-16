"""HTTP contract tests for bilingual reading-position endpoints."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def client(monkeypatch):
    import deeptutor.api.routers.immersive_reading as router_module

    position = {
        "pairing_id": "pair001",
        "chapter_id": "ch001",
        "chapter_index": 0,
        "group_index": 1,
        "epub_cfi": "epubcfi(/6/4)",
        "section_href": "chapter1.xhtml",
        "scroll_percent": 50,
        "text_fingerprint": "fingerprint",
        "updated_at": 1,
    }
    bookmark = {
        **position,
        "id": "bm001",
        "title": "Chapter one",
        "chapter_title": "Chapter 1",
        "preview": "The cat sat.",
        "created_at": 2,
    }
    navigation = {
        "current": position,
        "back_stack": [],
        "forward_stack": [],
        "can_back": False,
        "can_forward": False,
    }

    class FakePairingService:
        def load_reading_position(self, pairing_id):
            assert pairing_id == "pair001"
            return position

        def update_reading_position(self, pairing_id, request_position):
            assert pairing_id == "pair001"
            assert request_position["group_index"] == 1
            return position

        def list_bookmarks(self, pairing_id):
            assert pairing_id == "pair001"
            return [bookmark]

        def add_bookmark(self, pairing_id, request_position, *, title, preview):
            assert (pairing_id, title, preview) == ("pair001", "My bookmark", "preview")
            return bookmark

        def rename_bookmark(self, pairing_id, bookmark_id, title):
            assert (pairing_id, bookmark_id, title) == ("pair001", "bm001", "Renamed")
            return bookmark

        def delete_bookmark(self, pairing_id, bookmark_id):
            assert (pairing_id, bookmark_id) == ("pair001", "bm001")

        def get_navigation(self, pairing_id):
            assert pairing_id == "pair001"
            return navigation

        def record_navigation(self, pairing_id, request_position):
            assert pairing_id == "pair001"
            return navigation

        def navigate_back(self, pairing_id):
            assert pairing_id == "pair001"
            return position, navigation

        def navigate_forward(self, pairing_id):
            raise ValueError("No forward navigation destination")

    monkeypatch.setattr(router_module, "get_pairing_service", lambda: FakePairingService())
    app = fastapi.FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/immersive-reading")
    return TestClient(app), position


def test_reading_position_and_bookmark_http_contract(client):
    test_client, position = client
    base = "/api/v1/immersive-reading/bilingual/pair001"

    assert test_client.get(f"{base}/reading-position").json() == {"position": position}
    assert test_client.put(f"{base}/reading-position", json=position).json() == {
        "position": position
    }
    assert test_client.get(f"{base}/bookmarks").json()["bookmarks"][0]["id"] == "bm001"
    assert (
        test_client.post(
            f"{base}/bookmarks",
            json={"position": position, "title": "My bookmark", "preview": "preview"},
        ).json()["id"]
        == "bm001"
    )
    assert (
        test_client.put(f"{base}/bookmarks/bm001", json={"title": "Renamed"}).json()["id"]
        == "bm001"
    )
    assert test_client.delete(f"{base}/bookmarks/bm001").status_code == 200


def test_navigation_http_contract_and_conflict(client):
    test_client, position = client
    base = "/api/v1/immersive-reading/bilingual/pair001"

    assert test_client.get(f"{base}/navigation").json()["navigation"]["current"] == position
    assert (
        test_client.post(f"{base}/navigation", json=position).json()["navigation"]["current"]
        == position
    )
    assert test_client.post(f"{base}/navigation/back").json()["position"] == position
    response = test_client.post(f"{base}/navigation/forward")
    assert response.status_code == 409
    assert response.json()["detail"] == "No forward navigation destination"
