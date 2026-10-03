"""Memory workbench router contract tests (deeptutor/api/routers/memory.py).

Covers the three contract groups the workbench UI relies on:

1. GET shapes — overview / doc / lines / settings / trace / snapshot / backup.
2. Edit + delete round-trips — PUT /doc, DELETE entry, apply ops, PUT settings,
   trace clearing all read back consistently through the same API.
3. 4xx surfaces — bad layer, unknown surface/slot, missing entries, invalid
   run requests, bad trace days.

Everything is isolated per test: ``paths.memory_root`` is redirected to
``tmp_path``, the settings ``ConfigManager`` is replaced with an in-memory
fake (a real PUT would otherwise write the developer's ``main.yaml``), the
snapshot workspace adapters are stubbed, and the run-manager singleton is
reset on both sides of every test so no consolidator run can leak in or out.
Consolidator runs are never driven for real — the LLM runner is stubbed.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

memory_router = importlib.import_module("deeptutor.api.routers.memory").router
memory_router_mod = importlib.import_module("deeptutor.api.routers.memory")
paths_mod = importlib.import_module("deeptutor.services.memory.paths")
document_mod = importlib.import_module("deeptutor.services.memory.document")
settings_mod = importlib.import_module("deeptutor.services.memory.settings")
snap_adapters_mod = importlib.import_module("deeptutor.services.memory.snapshot.adapters")
snapshot_store = importlib.import_module("deeptutor.services.memory.snapshot.store")
runs_mod = importlib.import_module("deeptutor.services.memory.consolidator.runs")

ENTRY_ID = "m_01HZK1ABCDEFGHJKMNPQRSTVWX"
OTHER_ENTRY_ID = "m_01HZK1BCDEFGHJKMNPQRSTVWXY"


def _make_doc(surface: str, *entries: tuple[str, str]) -> str:
    """Serialize an L2 doc with the given (id, text) entries under 'Themes'."""
    doc = document_mod.Document(
        title=f"{surface} memory",
        sections=[
            (
                "Themes",
                [
                    document_mod.Entry(
                        id=entry_id,
                        section="Themes",
                        text=text,
                        refs=[f"{surface}:r{index}"],
                    )
                    for index, (entry_id, text) in enumerate(entries)
                ],
            ),
        ],
    )
    return document_mod.serialize(doc)


def _seed_l2(tmp_path: Path, surface: str, *entries: tuple[str, str]) -> Path:
    path = tmp_path / "L2" / f"{surface}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_make_doc(surface, *entries), encoding="utf-8")
    return path


def _write_trace(root: Path, surface: str, day: str, events: list[dict]) -> Path:
    trace_dir = root / "trace" / surface
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{day}.jsonl"
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )
    return path


def _trace_event(day: str, index: int) -> dict[str, Any]:
    return {
        "id": f"chat:{day}-{index}",
        "ts": f"{day}T0{index}:00:00+00:00",
        "surface": "chat",
        "kind": "note",
        "payload": {"text": f"event-{index}"},
    }


class _FakeConfigManager:
    """In-memory stand-in for ConfigManager — instances share class state."""

    _state: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._config = _FakeConfigManager._state

    def load_config(self, force_reload: bool = False) -> dict[str, Any]:
        return json.loads(json.dumps(self._config))

    def save_config(self, config: dict[str, Any]) -> bool:
        for key, value in config.items():
            if isinstance(value, dict) and isinstance(self._config.get(key), dict):
                self._config[key].update(json.loads(json.dumps(value)))
            else:
                self._config[key] = json.loads(json.dumps(value))
        return True


@pytest.fixture
def mem_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir()
    (tmp_path / "L3").mkdir()
    return tmp_path


@pytest.fixture
def client(mem_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    runs_mod.reset_run_manager_for_tests()
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")
    try:
        yield TestClient(app)
    finally:
        runs_mod.reset_run_manager_for_tests()


@pytest.fixture
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> type[_FakeConfigManager]:
    _FakeConfigManager._state = {}
    monkeypatch.setattr(settings_mod, "ConfigManager", _FakeConfigManager)
    return _FakeConfigManager


@pytest.fixture
def snapshot_adapters(monkeypatch: pytest.MonkeyPatch):
    stamps = [
        snap_adapters_mod.EntityStamp(
            id="e1", label="Notebook entry", fingerprint="fp2", ts="2026-10-02T00:00:00Z"
        )
    ]
    entities = [
        snap_adapters_mod.Entity(
            id="e1",
            label="Notebook entry",
            ts="2026-10-02T00:00:00Z",
            content="body",
            fingerprint="fp2",
        )
    ]
    monkeypatch.setattr(snap_adapters_mod, "read_entities", lambda surface: list(entities))
    monkeypatch.setattr(snap_adapters_mod, "read_stamps", lambda surface: list(stamps))
    return snap_adapters_mod


# ── ① GET return shapes ──────────────────────────────────────────────────


def test_overview_returns_all_docs_and_backups(client: TestClient, mem_root: Path) -> None:
    _seed_l2(mem_root, "chat", (ENTRY_ID, "some fact"))
    backup = mem_root / "backup" / "20260101T000000Z"
    backup.mkdir(parents=True)
    (backup / "L2").mkdir()

    res = client.get("/api/memory/overview")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"docs", "backups"}
    assert body["backups"] == ["20260101T000000Z"]

    docs = body["docs"]
    assert len(docs) == len(paths_mod.SURFACES) + len(paths_mod.L3_SLOTS)
    l2_rows = [row for row in docs if row["layer"] == "L2"]
    l3_rows = [row for row in docs if row["layer"] == "L3"]
    assert {row["key"] for row in l2_rows} == set(paths_mod.SURFACES)
    assert {row["key"] for row in l3_rows} == set(paths_mod.L3_SLOTS)
    for row in docs:
        assert set(row) == {"layer", "key", "exists", "updated_at", "entry_count", "backlog"}

    chat_row = next(row for row in l2_rows if row["key"] == "chat")
    assert chat_row["exists"] is True
    assert chat_row["entry_count"] == 1
    assert chat_row["updated_at"] is not None
    missing_row = next(row for row in l2_rows if row["key"] == "quiz")
    assert missing_row["exists"] is False
    assert missing_row["updated_at"] is None
    assert missing_row["entry_count"] == 0


def test_get_doc_returns_raw_content_or_empty(client: TestClient, mem_root: Path) -> None:
    _seed_l2(mem_root, "chat", (ENTRY_ID, "seeded fact"))

    res = client.get("/api/memory/doc/L2/chat")
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "layer": "L2",
        "key": "chat",
        "content": _make_doc("chat", (ENTRY_ID, "seeded fact")),
    }

    missing = client.get("/api/memory/doc/L3/profile")
    assert missing.status_code == 200
    assert missing.json() == {"layer": "L3", "key": "profile", "content": ""}


def test_get_doc_lines_returns_numbered_view(client: TestClient, mem_root: Path) -> None:
    _seed_l2(mem_root, "chat", (ENTRY_ID, "line view fact"))

    res = client.get("/api/memory/doc/L2/chat/lines")
    assert res.status_code == 200
    body = res.json()
    assert body["layer"] == "L2"
    assert body["key"] == "chat"
    assert isinstance(body["lines"], list) and body["lines"]
    for line in body["lines"]:
        assert set(line) == {"number", "kind", "text", "entry_id", "section"}
    assert any(line["entry_id"] == ENTRY_ID for line in body["lines"])


def test_get_settings_returns_full_schema(
    client: TestClient, isolated_settings: type[_FakeConfigManager]
) -> None:
    res = client.get("/api/memory/settings")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"update", "audit", "dedup", "merge", "chunking", "reference"}
    assert body["update"] == {"l2_budget": 20, "l3_budget": 10}
    assert body["dedup"] == {"iterations": 3, "auto_after_update": True}


def test_trace_returns_events_with_pagination(client: TestClient, mem_root: Path) -> None:
    _write_trace(
        mem_root,
        "chat",
        "2026-10-02",
        [_trace_event("2026-10-02", 1), _trace_event("2026-10-02", 2)],
    )

    res = client.get("/api/memory/trace/chat", params={"limit": 1, "offset": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["surface"] == "chat"
    assert body["offset"] == 1
    assert body["limit"] == 1
    assert [event["payload"]["text"] for event in body["events"]] == ["event-2"]
    for event in body["events"]:
        assert set(event) == {"id", "ts", "surface", "kind", "payload", "session_id", "turn_id"}


def test_snapshot_get_returns_entities_and_pending(
    client: TestClient, mem_root: Path, snapshot_adapters
) -> None:
    snapshot_store.save_state(
        "chat",
        fingerprints={"e1": "fp1"},
        labels={"e1": "Notebook entry"},
        last_refresh="2026-10-01T00:00:00Z",
    )

    res = client.get("/api/memory/snapshot/chat")
    assert res.status_code == 200
    body = res.json()
    assert body["surface"] == "chat"
    assert [entity["id"] for entity in body["entities"]] == ["e1"]
    assert body["last_refresh"] == "2026-10-01T00:00:00Z"
    assert len(body["pending_changes"]) == 1
    change = body["pending_changes"][0]
    assert change["entity_id"] == "e1"
    assert change["kind"] == "modified"


def test_backup_listing_shape(client: TestClient, mem_root: Path) -> None:
    empty = client.get("/api/memory/backup")
    assert empty.status_code == 200
    assert empty.json() == {"backups": []}

    backup = mem_root / "backup" / "20260101T000000Z"
    backup.mkdir(parents=True)
    (backup / "PROFILE.md").write_text("archived", encoding="utf-8")

    res = client.get("/api/memory/backup")
    assert res.status_code == 200
    assert res.json() == {"backups": [{"name": "20260101T000000Z", "files": ["PROFILE.md"]}]}


# ── ② Edit / delete then read consistency ────────────────────────────────


def test_put_doc_then_get_roundtrip(client: TestClient) -> None:
    content = "---\ntitle: chat memory\n---\n\n# Themes\n\n- hand edited fact\n"
    res = client.put("/api/memory/doc/L2/chat", json={"content": content})
    assert res.status_code == 200
    assert res.json() == {"layer": "L2", "key": "chat", "saved": True}

    follow_up = client.get("/api/memory/doc/L2/chat")
    assert follow_up.status_code == 200
    assert follow_up.json()["content"] == content


def test_delete_entry_then_read_consistent(client: TestClient, mem_root: Path) -> None:
    _seed_l2(
        mem_root,
        "chat",
        (ENTRY_ID, "doomed fact"),
        (OTHER_ENTRY_ID, "surviving fact"),
    )

    res = client.delete(f"/api/memory/doc/L2/chat/entry/{ENTRY_ID}")
    assert res.status_code == 200
    assert res.json() == {"layer": "L2", "key": "chat", "deleted": ENTRY_ID}

    content = client.get("/api/memory/doc/L2/chat").json()["content"]
    assert "doomed fact" not in content
    assert "surviving fact" in content

    again = client.delete(f"/api/memory/doc/L2/chat/entry/{ENTRY_ID}")
    assert again.status_code == 404
    assert again.json()["detail"] == "entry not found"


def test_apply_ops_adds_entry_to_doc(client: TestClient) -> None:
    res = client.post(
        "/api/memory/doc/L2/chat/apply",
        json={
            "ops": [
                {
                    "op": "add",
                    "section": "Themes",
                    "text": "applied fact",
                    "refs": ["chat:r0"],
                }
            ]
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] is True
    assert body["reason"] == ""
    assert len(body["results"]) == 1
    assert body["results"][0]["status"] == "applied"
    assert body["results"][0]["entry_id"].startswith("m_")

    content = client.get("/api/memory/doc/L2/chat").json()["content"]
    assert "applied fact" in content

    empty = client.post("/api/memory/doc/L2/chat/apply", json={"ops": []})
    assert empty.status_code == 200
    assert empty.json() == {"accepted": True, "reason": "no ops to apply", "results": []}


def test_apply_ops_preferences_is_rejected(client: TestClient) -> None:
    res = client.post(
        "/api/memory/doc/L3/preferences/apply",
        json={"ops": [{"op": "add", "section": "Preferences", "text": "x", "refs": []}]},
    )
    assert res.status_code == 405


def test_put_settings_roundtrip(
    client: TestClient, isolated_settings: type[_FakeConfigManager]
) -> None:
    res = client.put("/api/memory/settings", json={"update": {"l2_budget": 55}})
    assert res.status_code == 200
    body = res.json()
    assert body["update"]["l2_budget"] == 55
    # Unspecified fields keep their defaults after the merge.
    assert body["dedup"]["iterations"] == 3
    assert isolated_settings._state["memory"]["update"]["l2_budget"] == 55

    follow_up = client.get("/api/memory/settings")
    assert follow_up.status_code == 200
    assert follow_up.json()["update"]["l2_budget"] == 55


def test_clear_trace_and_clear_day_consistent(client: TestClient, mem_root: Path) -> None:
    _write_trace(mem_root, "chat", "2026-10-01", [_trace_event("2026-10-01", 1)])
    _write_trace(mem_root, "chat", "2026-10-02", [_trace_event("2026-10-02", 1)])

    res = client.delete("/api/memory/trace/chat/day/2026-10-01")
    assert res.status_code == 200
    assert res.json() == {"surface": "chat", "day": "2026-10-01", "deleted": True}
    assert not (mem_root / "trace" / "chat" / "2026-10-01.jsonl").exists()
    assert (mem_root / "trace" / "chat" / "2026-10-02.jsonl").exists()

    clear_all = client.delete("/api/memory/trace/chat")
    assert clear_all.status_code == 200
    assert clear_all.json() == {"surface": "chat", "removed_files": 1}
    assert client.get("/api/memory/trace/chat").json()["events"] == []


def test_snapshot_refresh_and_changes_roundtrip(
    client: TestClient, mem_root: Path, snapshot_adapters
) -> None:
    refresh = client.post("/api/memory/snapshot/chat/refresh")
    assert refresh.status_code == 200
    body = refresh.json()
    assert body["surface"] == "chat"
    assert [change["entity_id"] for change in body["changes"]] == ["e1"]
    assert body["last_refresh"] is not None

    listed = client.get("/api/memory/snapshot/chat/changes", params={"limit": 10, "offset": 0})
    assert listed.status_code == 200
    listed_body = listed.json()
    assert listed_body["surface"] == "chat"
    assert listed_body["limit"] == 10
    assert [change["entity_id"] for change in listed_body["changes"]] == ["e1"]

    cleared = client.delete("/api/memory/snapshot/chat/changes")
    assert cleared.status_code == 200
    assert cleared.json() == {"surface": "chat", "cleared": True}
    assert client.get("/api/memory/snapshot/chat/changes").json()["changes"] == []


# ── ③ Invalid params / nonexistent items → 4xx ───────────────────────────


def test_doc_invalid_layer_returns_400(client: TestClient) -> None:
    for method, path in (
        ("get", "/api/memory/doc/L9/chat"),
        ("put", "/api/memory/doc/L9/chat"),
        ("delete", "/api/memory/doc/L9/chat/entry/x"),
        ("get", "/api/memory/doc/L9/chat/lines"),
    ):
        res = getattr(client, method)(
            path, **({"json": {"content": "x"}} if method == "put" else {})
        )
        assert res.status_code == 400, (method, path)
        assert res.json()["detail"] == "layer must be L2 or L3"


def test_doc_unknown_surface_or_slot_returns_404(client: TestClient) -> None:
    assert client.get("/api/memory/doc/L2/nope").status_code == 404
    assert client.get("/api/memory/doc/L3/nope").status_code == 404
    assert client.put("/api/memory/doc/L2/nope", json={"content": "x"}).status_code == 404
    assert client.delete("/api/memory/doc/L2/nope/entry/x").status_code == 404
    assert client.get("/api/memory/doc/L2/nope/lines").status_code == 404


def test_put_doc_missing_body_returns_422(client: TestClient) -> None:
    res = client.put("/api/memory/doc/L2/chat", json={})
    assert res.status_code == 422


def test_run_start_invalid_combos(client: TestClient) -> None:
    bad_layer = client.post(
        "/api/memory/runs/start",
        json={"layer": "L1", "key": "chat", "mode": "update"},
    )
    assert bad_layer.status_code == 400

    bad_key = client.post(
        "/api/memory/runs/start",
        json={"layer": "L2", "key": "nope", "mode": "update"},
    )
    assert bad_key.status_code == 404

    preferences = client.post(
        "/api/memory/runs/start",
        json={"layer": "L3", "key": "preferences", "mode": "update"},
    )
    assert preferences.status_code == 405

    bad_mode = client.post(
        "/api/memory/runs/start",
        json={"layer": "L2", "key": "chat", "mode": "explode"},
    )
    assert bad_mode.status_code == 422


def test_run_unknown_ids(client: TestClient) -> None:
    assert client.get("/api/memory/runs/unknown").status_code == 404
    assert client.get("/api/memory/runs/unknown/events").status_code == 404
    assert client.post("/api/memory/runs/unknown/undo").status_code == 404
    cancel = client.post("/api/memory/runs/unknown/cancel")
    assert cancel.status_code == 409
    assert cancel.json()["detail"] == "not active"


def test_list_runs_validation(client: TestClient) -> None:
    empty = client.get("/api/memory/runs")
    assert empty.status_code == 200
    assert empty.json() == {"runs": []}

    assert client.get("/api/memory/runs", params={"layer": "L9"}).status_code == 400
    assert client.get("/api/memory/runs", params={"layer": "L2", "key": "nope"}).status_code == 404


def test_trace_day_invalid_and_missing(client: TestClient) -> None:
    bad = client.delete("/api/memory/trace/chat/day/not-a-date")
    assert bad.status_code == 400
    assert bad.json()["detail"] == "day must be YYYY-MM-DD"

    missing = client.delete("/api/memory/trace/chat/day/2026-10-02")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "no trace for that day"


def test_snapshot_unknown_surface_returns_404(client: TestClient, snapshot_adapters) -> None:
    assert client.get("/api/memory/snapshot/nope").status_code == 404
    assert client.post("/api/memory/snapshot/nope/refresh").status_code == 404
    assert client.get("/api/memory/snapshot/nope/changes").status_code == 404
    assert client.delete("/api/memory/snapshot/nope/changes").status_code == 404


def test_legacy_mode_endpoint_validation(client: TestClient) -> None:
    """Legacy streams validate layer/key before any run starts."""
    assert client.post("/api/memory/doc/L9/chat/update").status_code == 400
    assert client.post("/api/memory/doc/L2/nope/update").status_code == 404
    assert client.post("/api/memory/doc/L1/x/audit").status_code == 400
    assert client.post("/api/memory/doc/L2/nope/dedup").status_code == 404


# ── Run lifecycle contract (runner stubbed — no LLM) ─────────────────────


def test_run_start_and_completion_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_runner(on_event) -> None:  # noqa: ANN001 — matches runner signature
        await __import__("asyncio").sleep(0)

    monkeypatch.setattr(memory_router_mod, "_runner_for", lambda req: fake_runner)

    res = client.post(
        "/api/memory/runs/start",
        json={"layer": "L2", "key": "chat", "mode": "update", "language": "en"},
    )
    assert res.status_code == 200
    started = res.json()
    assert set(started) == {
        "id",
        "layer",
        "key",
        "mode",
        "params",
        "language",
        "status",
        "started_at",
        "ended_at",
        "error",
        "event_count",
        "undo_count",
    }
    assert started["layer"] == "L2"
    assert started["key"] == "chat"
    assert started["mode"] == "update"
    run_id = started["id"]

    fetched = client.get(f"/api/memory/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "done"
    assert fetched.json()["event_count"] >= 2

    listed = client.get("/api/memory/runs", params={"layer": "L2", "key": "chat"})
    assert [run["id"] for run in listed.json()["runs"]] == [run_id]

    cancel = client.post(f"/api/memory/runs/{run_id}/cancel")
    assert cancel.status_code == 409
    assert cancel.json()["detail"] == "not active"

    undo = client.post(f"/api/memory/runs/{run_id}/undo")
    assert undo.status_code == 409
    assert undo.json()["detail"] == "nothing to undo"
