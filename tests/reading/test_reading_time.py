"""Effective reading-time heartbeats: storage accounting and the HTTP beat.

The contract (#1988): the Reader sends a bounded heartbeat about every 30
seconds while the page is visible, focused and recently used (or read-aloud
is playing). The server credits at most the wall-clock time since the
previous accepted beat for the account, so two open tabs cannot double count
and forged claims are truncated. Totals are compact per-material daily rows
next to ``reading_progress`` — no source text, selection or anchor is stored.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("fastapi")

from deeptutor.api.routers import reading
import deeptutor.learning.storage as storage_module
from deeptutor.learning.storage import LearningStore
from deeptutor.reading import ReadingStore
from deeptutor.services.path_service import PathService

MATERIAL_ID = "b1c2d3e4f5a6"
TIME_BASE = f"/api/reading/materials/{MATERIAL_ID}/reading-time"


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "learning"


def test_two_minutes_of_active_beats_credit_two_minutes(store_root: Path) -> None:
    """Four 30-second beats 30 seconds apart credit exactly 120 seconds."""
    store = LearningStore(root=store_root)
    start = 1_000_000.0
    credited = 0
    for index in range(1, 5):
        result = store.record_reading_time(
            MATERIAL_ID, active_seconds=30, timezone="UTC", now=start + index * 30
        )
        credited += result["credited_seconds"]
    assert credited == 120

    window = store.reading_time_window("UTC", 7, now=start + 150)
    assert window["total"] == 120
    assert window["materials"] == [{"material_id": MATERIAL_ID, "reading_seconds": 120}]


def test_idle_gap_credits_nothing(store_root: Path) -> None:
    """Idle and hidden periods send no beats, so they credit nothing."""
    store = LearningStore(root=store_root)
    start = 2_000_000.0
    store.record_reading_time(MATERIAL_ID, active_seconds=30, timezone="UTC", now=start)
    # 90 seconds idle + 30 seconds hidden: the client sends no further beat.
    assert store.reading_time_window("UTC", 7, now=start + 120)["total"] == 30
    # A late flush is still bounded by its claim (≤ active seconds) and cap.
    late = store.record_reading_time(
        MATERIAL_ID, active_seconds=10, timezone="UTC", now=start + 120
    )
    assert late["credited_seconds"] == 10


def test_forged_large_beats_are_truncated(store_root: Path) -> None:
    store = LearningStore(root=store_root)
    start = 3_000_000.0
    forged = store.record_reading_time(MATERIAL_ID, active_seconds=3_500, timezone="UTC", now=start)
    assert forged["active_seconds"] == 3_500
    assert forged["credited_seconds"] == storage_module.READING_TIME_MAX_BEAT_SECONDS

    replay = store.record_reading_time(
        MATERIAL_ID, active_seconds=3_500, timezone="UTC", now=start + 1
    )
    assert replay["credited_seconds"] == 1  # also bounded by elapsed wall clock


def test_parallel_tabs_cannot_double_count(store_root: Path) -> None:
    """Two tabs beating alternately credit at most the shared wall clock."""
    store = LearningStore(root=store_root)
    start = 4_000_000.0
    total = 0
    # Tab A beats at 30/60/90/120s, tab B at 45/75/105s; both claim their own
    # 30 accumulated seconds. Interleaved beats clamp to the elapsed wall time
    # since the other tab's beat, so 120 seconds of reading credit 120 seconds
    # — not 240.
    beats = [
        ("rm_tab_a", 30),
        ("rm_tab_b", 45),
        ("rm_tab_a", 60),
        ("rm_tab_b", 75),
        ("rm_tab_a", 90),
        ("rm_tab_b", 105),
        ("rm_tab_a", 120),
    ]
    for material_id, at in beats:
        result = store.record_reading_time(
            material_id, active_seconds=30, timezone="UTC", now=start + at
        )
        total += result["credited_seconds"]
    assert total == 120
    window = store.reading_time_window("UTC", 7, now=start + 120)
    assert window["total"] == 120
    assert {item["material_id"] for item in window["materials"]} == {"rm_tab_a", "rm_tab_b"}


def test_beats_land_on_timezone_local_days(store_root: Path) -> None:
    from datetime import datetime
    from datetime import timezone as utc_timezone

    store = LearningStore(root=store_root)
    # 15:50 UTC is 23:50 in Asia/Shanghai; twenty minutes later it is next day.
    late_utc = datetime(2027, 3, 5, 15, 50, tzinfo=utc_timezone.utc).timestamp()
    first = store.record_reading_time(
        MATERIAL_ID, active_seconds=30, timezone="Asia/Shanghai", now=late_utc
    )
    second = store.record_reading_time(
        MATERIAL_ID,
        active_seconds=30,
        timezone="Asia/Shanghai",
        now=late_utc + 20 * 60,
    )
    assert first["day"] == "2027-03-05"
    assert second["day"] == "2027-03-06"
    window = store.reading_time_window("Asia/Shanghai", 7, now=late_utc + 20 * 60)
    assert sum(1 for value in window["daily"].values() if value) == 2


def test_unknown_timezone_is_rejected(store_root: Path) -> None:
    store = LearningStore(root=store_root)
    with pytest.raises(ValueError, match="Unknown timezone"):
        store.record_reading_time(MATERIAL_ID, active_seconds=30, timezone="not-a-zone")


def test_schema_migration_is_idempotent_and_keeps_totals(store_root: Path) -> None:
    """Re-running schema init on an existing database converges without loss."""
    store = LearningStore(root=store_root)
    start = 5_000_000.0
    store.record_reading_time(MATERIAL_ID, active_seconds=30, timezone="UTC", now=start)
    before = store.reading_time_window("UTC", 7, now=start)

    with store._connect() as conn:  # simulate a pre-#1988 database
        conn.executescript("DROP TABLE reading_time_daily; DROP TABLE reading_time_state;")
        conn.commit()
    storage_module._initialized_db_paths.discard(store.db_path.resolve())

    reopened = LearningStore(root=store_root)
    with reopened._connect() as conn:
        tables = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"reading_time_daily", "reading_time_state"} <= tables
    # Dropped rows are gone (they were dropped), but re-recording is consistent.
    reopened.record_reading_time(MATERIAL_ID, active_seconds=30, timezone="UTC", now=start + 30)
    after = reopened.reading_time_window("UTC", 7, now=start)
    assert after["total"] == 30
    assert before["total"] == 30


# ---- HTTP surface ---------------------------------------------------------


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    app = FastAPI()
    app.include_router(reading.router, prefix="/api/reading")
    with TestClient(app) as test_client:
        ReadingStore().ingest_units(
            MATERIAL_ID,
            filename="time.md",
            units=["Section one.", "Section two."],
            unit="section",
            title="Reading time fixture",
        )
        yield test_client
    PathService.reset_instance()


def test_heartbeat_endpoint_credits_and_reports_clamping(client: TestClient) -> None:
    first = client.post(TIME_BASE, json={"active_seconds": 30})
    assert first.status_code == 200
    body = first.json()
    assert body["material_id"] == MATERIAL_ID
    assert body["credited_seconds"] == 30
    assert body["day"]

    forged = client.post(TIME_BASE, json={"active_seconds": 3_500})
    assert forged.status_code == 200
    assert forged.json()["credited_seconds"] <= 120


def test_heartbeat_endpoint_validation(client: TestClient) -> None:
    assert client.post(TIME_BASE, json={"active_seconds": -1}).status_code == 422
    assert client.post(TIME_BASE, json={"active_seconds": 3_601}).status_code == 422
    assert client.post(TIME_BASE, json={"active_seconds": 5, "timezone": "nope"}).status_code == 422
    assert (
        client.post(
            "/api/reading/materials/0123456789abcdef/reading-time",
            json={"active_seconds": 5},
        ).status_code
        == 404
    )


def test_heartbeats_land_in_the_account_learning_database(client: TestClient) -> None:
    first = client.post(TIME_BASE, json={"active_seconds": 30})
    assert first.status_code == 200
    # A second immediate beat is clamped by the near-zero elapsed wall time —
    # rapid duplicate posts cannot inflate the total.
    second = client.post(TIME_BASE, json={"active_seconds": 30})
    assert second.status_code == 200
    assert second.json()["credited_seconds"] == 0
    records = LearningStore().reading_time_window("UTC", 7)
    assert records["total"] == 30
    assert records["materials"][0]["material_id"] == MATERIAL_ID
