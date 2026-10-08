"""Contract tests for the Immersive Reading progress API.

These pin the durability contract of the position and bookmark endpoints —
the two routes a reader trusts to survive a reload. A lost or corrupted
progress write is invisible until a user opens the book on another device,
so the suite drives a real :class:`~deeptutor.reading.store.ReadingStore`
through the real ASGI routes and asserts on persisted state, not just on
response bodies:

1. save → retrieve round-trip returns exactly what was saved;
2. saving the same position or bookmark twice converges (idempotent);
3. malformed payloads are rejected with 4xx and persist nothing;
4. a failed save (out-of-range locator) leaves the previous state intact.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("fastapi")

from deeptutor.api.routers import reading
from deeptutor.learning.storage import LearningStore
from deeptutor.reading import ReadingStore
from deeptutor.services.path_service import PathService

MATERIAL_ID = "a1b2c3d4e5f6"
UNIT_COUNT = 3

SAVED_POSITION = {"locator": 2, "source_anchor": "epubcfi(/6/4)", "percentage": 0.75}
POSITION_BASE = f"/api/reading/materials/{MATERIAL_ID}/position"
BOOKMARK_BASE = f"/api/reading/materials/{MATERIAL_ID}/bookmarks"


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    app = FastAPI()
    app.include_router(reading.router, prefix="/api/reading")
    with TestClient(app) as test_client:
        yield test_client
    PathService.reset_instance()


@pytest.fixture
def material(client: TestClient) -> str:
    """A real three-unit material in the store the router will resolve."""
    ReadingStore().ingest_units(
        MATERIAL_ID,
        filename="progress.md",
        units=[f"Section {index} body text." for index in range(1, UNIT_COUNT + 1)],
        unit="section",
        title="Progress fixture",
    )
    return MATERIAL_ID


def _positions_dir() -> Path:
    return ReadingStore().root / MATERIAL_ID / "positions"


def test_position_defaults_to_first_locator_before_any_save(
    client: TestClient, material: str
) -> None:
    response = client.get(POSITION_BASE)

    assert response.status_code == 200
    body = response.json()
    assert body["locator"] == 1
    assert body["source_anchor"] == ""
    assert body["percentage"] == 0.0
    assert body["updated_at"] > 0


def test_saved_position_roundtrips_through_get(client: TestClient, material: str) -> None:
    saved = client.put(POSITION_BASE, json=SAVED_POSITION)
    assert saved.status_code == 200
    saved_body = saved.json()
    assert saved_body["updated_at"] > 0

    fetched = client.get(POSITION_BASE)

    assert fetched.status_code == 200
    body = fetched.json()
    for key, value in SAVED_POSITION.items():
        assert body[key] == value, f"round-trip lost {key}"


def test_duplicate_save_of_the_same_position_is_idempotent(
    client: TestClient, material: str
) -> None:
    first = client.put(POSITION_BASE, json=SAVED_POSITION)
    second = client.put(POSITION_BASE, json=SAVED_POSITION)

    assert first.status_code == second.status_code == 200
    assert second.json()["updated_at"] >= first.json()["updated_at"]

    body = client.get(POSITION_BASE).json()
    for key, value in SAVED_POSITION.items():
        assert body[key] == value

    state_files = sorted(_positions_dir().glob("*.json"))
    assert len(state_files) == 1, f"expected one position file, found {state_files}"
    on_disk = json.loads(state_files[0].read_text())
    for key, value in SAVED_POSITION.items():
        assert on_disk[key] == value

    records = LearningStore().list_reading_records()
    assert len(records.progress) == 1
    assert records.progress[0].material_id == material
    assert records.progress[0].latest_locator == SAVED_POSITION["locator"]


def test_re_save_with_a_new_locator_overwrites_the_previous_state(
    client: TestClient, material: str
) -> None:
    assert client.put(POSITION_BASE, json={"locator": 2, "percentage": 0.5}).status_code == 200

    moved = client.put(POSITION_BASE, json={"locator": 3, "percentage": 0.9})
    assert moved.status_code == 200

    body = client.get(POSITION_BASE).json()
    assert body["locator"] == 3
    assert body["percentage"] == 0.9
    assert len(list(_positions_dir().glob("*.json"))) == 1


def test_failed_save_out_of_range_locator_keeps_previous_state(
    client: TestClient, material: str
) -> None:
    assert client.put(POSITION_BASE, json={"locator": 2, "percentage": 0.5}).status_code == 200

    response = client.put(POSITION_BASE, json={"locator": UNIT_COUNT + 1, "percentage": 0.9})

    assert response.status_code == 400
    body = client.get(POSITION_BASE).json()
    assert body["locator"] == 2
    assert body["percentage"] == 0.5


def test_position_routes_404_for_an_unknown_material(client: TestClient) -> None:
    missing = "/api/reading/materials/0123456789abcdef/position"

    assert client.get(missing).status_code == 404
    assert client.put(missing, json={"locator": 1}).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"locator": 0},
        {"locator": 2, "percentage": 1.5},
        {"locator": 2, "percentage": -0.25},
        {"locator": 2, "source_anchor": "x" * 4097},
        {"locator": "second"},
        {},
    ],
)
def test_invalid_position_payloads_are_rejected_with_4xx(
    client: TestClient, material: str, payload: dict
) -> None:
    response = client.put(POSITION_BASE, json=payload)

    assert 400 <= response.status_code < 500
    body = client.get(POSITION_BASE).json()
    assert body["locator"] == 1, "a rejected save must persist nothing"


def test_bookmark_roundtrip_lists_in_reading_order(client: TestClient, material: str) -> None:
    kept = client.post(BOOKMARK_BASE, json={"locator": 3, "label": "Ending"})
    assert kept.status_code == 200
    assert kept.json()["bookmark_id"].startswith("bm_")

    first_page = client.post(
        BOOKMARK_BASE,
        json={"locator": 1, "label": "Opening", "source_anchor": "anchor-1"},
    )
    assert first_page.status_code == 200

    rows = client.get(BOOKMARK_BASE).json()["bookmarks"]

    assert [row["locator"] for row in rows] == [1, 3]
    assert rows[0]["label"] == "Opening"
    assert rows[0]["source_anchor"] == "anchor-1"
    assert rows[1]["label"] == "Ending"


def test_duplicate_bookmark_of_the_same_locator_is_idempotent(
    client: TestClient, material: str
) -> None:
    first = client.post(BOOKMARK_BASE, json={"locator": 2, "label": "Kept"})
    second = client.post(BOOKMARK_BASE, json={"locator": 2, "label": "Kept again"})

    assert first.status_code == second.status_code == 200
    assert second.json()["bookmark_id"] == first.json()["bookmark_id"]

    rows = client.get(BOOKMARK_BASE).json()["bookmarks"]
    assert len(rows) == 1
    assert rows[0]["label"] == "Kept", "the second save must not overwrite the first"


def test_delete_bookmark_removes_exactly_one_place(client: TestClient, material: str) -> None:
    created = client.post(BOOKMARK_BASE, json={"locator": 2}).json()

    removed = client.delete(f"{BOOKMARK_BASE}/{created['bookmark_id']}")
    assert removed.status_code == 200
    assert client.get(BOOKMARK_BASE).json()["bookmarks"] == []

    again = client.delete(f"{BOOKMARK_BASE}/{created['bookmark_id']}")
    assert again.status_code == 404


def test_bookmark_routes_404_for_an_unknown_material(client: TestClient) -> None:
    missing = "/api/reading/materials/0123456789abcdef/bookmarks"

    assert client.get(missing).status_code == 404
    assert client.post(missing, json={"locator": 1}).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"locator": 0},
        {"locator": UNIT_COUNT + 1},
        {"locator": 2, "label": "x" * 201},
        {"locator": 2, "source_anchor": "x" * 4097},
    ],
)
def test_invalid_bookmark_payloads_are_rejected_with_4xx(
    client: TestClient, material: str, payload: dict
) -> None:
    response = client.post(BOOKMARK_BASE, json=payload)

    assert 400 <= response.status_code < 500
    assert client.get(BOOKMARK_BASE).json()["bookmarks"] == []
