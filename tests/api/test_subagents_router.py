"""API tests for the subagents router (detect / connect / list / disconnect).

Built on a standalone app with a fake KB manager and a stubbed detector, so it
exercises the HTTP contract without spawning a real CLI or touching the data
tree (mirrors test_knowledge_router's isolation).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional dependency in lightweight envs
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

if FastAPI is not None and TestClient is not None:
    subagents_module = importlib.import_module("deeptutor.api.routers.subagents")
else:  # pragma: no cover
    subagents_module = None


class _FakeKBManager:
    def __init__(self) -> None:
        self.kbs: dict[str, dict] = {}

    def list_knowledge_bases(self) -> list[str]:
        return sorted(self.kbs)

    def get_metadata(self, name: str | None = None) -> dict:
        return dict(self.kbs.get(name or "", {}))

    def register_subagent_connection(
        self, name, agent_kind, *, cwd="", partner_id="", description=""
    ):
        if name in self.kbs:
            raise ValueError(f"A knowledge base named '{name}' already exists.")
        entry = {
            "path": name,
            "type": "subagent",
            "agent_kind": agent_kind,
            "cwd": cwd,
            "partner_id": partner_id,
            "description": description or f"Connected subagent: {name}",
        }
        self.kbs[name] = entry
        return entry

    def delete_knowledge_base(self, name, confirm=False):
        self.kbs.pop(name, None)
        return True


@pytest.fixture
def client(monkeypatch, tmp_path):
    manager = _FakeKBManager()
    monkeypatch.setattr(subagents_module, "current_kb_manager", lambda: manager)
    monkeypatch.setattr(
        subagents_module, "list_backend_kinds", lambda: ["claude_code", "codex", "partner"]
    )
    monkeypatch.setattr(subagents_module, "assert_path_allowed", lambda p: Path(p))
    # Isolate settings persistence to a temp file — the PUT path otherwise
    # writes the developer's real data/user/settings/subagent.json.
    monkeypatch.setattr(
        "deeptutor.services.subagent.config._settings_path",
        lambda: tmp_path / "subagent.json",
    )

    async def fake_detect():
        from deeptutor.services.subagent.types import DetectResult

        return [
            DetectResult("claude_code", "Claude Code", available=True, version="2.x"),
            DetectResult("codex", "Codex", available=False, detail="not installed"),
        ]

    monkeypatch.setattr(subagents_module, "detect_all", fake_detect)

    app = FastAPI()
    app.include_router(subagents_module.router, prefix="/api/v1/subagents")
    # Settings PUT is admin-gated; bypass the auth dependency for the contract test.
    app.dependency_overrides[subagents_module.require_admin] = lambda: None
    return TestClient(app)


def test_detect_reports_backends(client):
    res = client.get("/api/v1/subagents/detect")
    assert res.status_code == 200
    backends = {b["kind"]: b for b in res.json()["backends"]}
    assert backends["claude_code"]["available"] is True
    assert backends["codex"]["available"] is False


def test_connect_list_and_disconnect_roundtrip(client):
    created = client.post(
        "/api/v1/subagents/connections",
        json={"name": "MyClaude", "agent_kind": "claude_code", "cwd": "/tmp"},
    )
    assert created.status_code == 200
    assert created.json()["agent_kind"] == "claude_code"

    listed = client.get("/api/v1/subagents/connections").json()["connections"]
    assert len(listed) == 1
    assert listed[0]["name"] == "MyClaude"
    assert listed[0]["agent_kind"] == "claude_code"
    assert listed[0]["cwd"] == "/tmp"

    gone = client.delete("/api/v1/subagents/connections/MyClaude")
    assert gone.status_code == 200
    assert client.get("/api/v1/subagents/connections").json()["connections"] == []


def test_connect_rejects_unknown_kind(client):
    res = client.post(
        "/api/v1/subagents/connections",
        json={"name": "X", "agent_kind": "bogus"},
    )
    assert res.status_code == 400


class _FakePartnerManagerForConnect:
    def __init__(self, known: set[str]) -> None:
        self._known = known

    def partner_exists(self, pid: str) -> bool:
        return pid in self._known


def _patch_partner_existence(monkeypatch, known: set[str]) -> None:
    import deeptutor.services.partners as partners_pkg

    monkeypatch.setattr(
        partners_pkg, "get_partner_manager", lambda: _FakePartnerManagerForConnect(known)
    )


def test_connect_partner_binds_partner_id(client, monkeypatch):
    _patch_partner_existence(monkeypatch, {"paul"})
    created = client.post(
        "/api/v1/subagents/connections",
        json={"name": "Paul", "agent_kind": "partner", "partner_id": "paul"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["agent_kind"] == "partner"
    assert body["partner_id"] == "paul"
    assert body["cwd"] == ""

    listed = client.get("/api/v1/subagents/connections").json()["connections"]
    assert listed[0]["agent_kind"] == "partner"
    assert listed[0]["partner_id"] == "paul"


def test_list_visible_partners(client, monkeypatch):
    monkeypatch.setattr(
        subagents_module,
        "visible_partner_cards",
        lambda: [{"partner_id": "p1", "name": "P1", "emoji": "🤖"}],
    )
    res = client.get("/api/v1/subagents/partners")
    assert res.status_code == 200
    partners = res.json()["partners"]
    assert partners == [{"partner_id": "p1", "name": "P1", "emoji": "🤖"}]


def test_connect_partner_denied_when_not_assigned(client, monkeypatch):
    # A non-admin connecting an unassigned partner is rejected by the
    # assignment guard before the connection is created.
    from fastapi import HTTPException

    _patch_partner_existence(monkeypatch, {"paul"})

    def deny(_pid):
        raise HTTPException(status_code=403, detail="Partner is not assigned to you")

    monkeypatch.setattr(subagents_module, "assert_partner_allowed", deny)
    res = client.post(
        "/api/v1/subagents/connections",
        json={"name": "Paul", "agent_kind": "partner", "partner_id": "paul"},
    )
    assert res.status_code == 403
    # Nothing was connected.
    assert client.get("/api/v1/subagents/connections").json()["connections"] == []


def test_connect_partner_requires_partner_id(client, monkeypatch):
    _patch_partner_existence(monkeypatch, {"paul"})
    res = client.post(
        "/api/v1/subagents/connections",
        json={"name": "Paul", "agent_kind": "partner"},
    )
    assert res.status_code == 400


def test_connect_partner_rejects_unknown_partner(client, monkeypatch):
    _patch_partner_existence(monkeypatch, set())
    res = client.post(
        "/api/v1/subagents/connections",
        json={"name": "Ghost", "agent_kind": "partner", "partner_id": "ghost"},
    )
    assert res.status_code == 400


def test_disconnect_unknown_is_404(client):
    res = client.delete("/api/v1/subagents/connections/nope")
    assert res.status_code == 404


def test_backend_options_endpoint_shape(client, monkeypatch):
    from deeptutor.services.subagent import models as models_mod
    from deeptutor.services.subagent.models import BackendOptions, ModelOption

    async def fake_options():
        return [
            BackendOptions(
                kind="codex",
                display_name="Codex",
                available=True,
                version="0.x",
                default_model="gpt-5.5",
                models=[ModelOption("gpt-5.5", "GPT-5.5", "medium", ["low", "medium", "high"])],
                efforts=["low", "medium", "high"],
                allow_custom_model=True,
                synced_at="2026-06-17T00:00:00Z",
            )
        ]

    # The route imports list_backend_options lazily from the models module.
    monkeypatch.setattr(models_mod, "list_backend_options", fake_options)

    res = client.get("/api/v1/subagents/backends/options")
    assert res.status_code == 200
    backends = res.json()["backends"]
    assert backends[0]["kind"] == "codex"
    assert backends[0]["default_model"] == "gpt-5.5"
    assert backends[0]["models"][0]["efforts"] == ["low", "medium", "high"]
    assert backends[0]["synced_at"] == "2026-06-17T00:00:00Z"


def test_message_connection_streams_and_persists(client, monkeypatch, tmp_path):
    # Connect, then message the agent directly: the run streams as NDJSON and the
    # backend session id is remembered (keyed by chat session + connection).
    client.post(
        "/api/v1/subagents/connections",
        json={"name": "MyClaude", "agent_kind": "claude_code"},
    )

    from deeptutor.services.subagent import sessions as sess
    from deeptutor.services.subagent.types import ConsultResult, SubagentEvent

    monkeypatch.setattr(sess, "_path", lambda: tmp_path / "sessions.json")

    class _FakeBackend:
        kind = "claude_code"

        async def consult(
            self, message, *, on_event, cwd, session_id, config, images=None, partner_id=None
        ):
            await on_event(SubagentEvent(kind="text", text="hi", meta={"merge_id": "txt:m:0"}))
            return ConsultResult(final_text="hi", session_id="sess-9", success=True, event_count=1)

    monkeypatch.setattr("deeptutor.services.subagent.get_backend", lambda kind: _FakeBackend())

    res = client.post(
        "/api/v1/subagents/connections/MyClaude/message",
        json={"chat_session_id": "chatA", "message": "hello"},
    )
    assert res.status_code == 200
    lines = [json.loads(line) for line in res.text.splitlines() if line.strip()]

    # The user's own message heads the exchange.
    assert lines[0] == {"channel": "user_question", "text": "hello"}
    # The agent's event carries a sidebar-namespaced merge id.
    assert any(
        line.get("channel") == "text" and line.get("merge_id") == "side:txt:m:0" for line in lines
    )
    # The final line reports the session id, now persisted for the next turn.
    assert lines[-1]["done"] is True and lines[-1]["session_id"] == "sess-9"
    assert sess.get_session(sess.session_key("chatA", "MyClaude")) == "sess-9"


def test_message_connection_unknown_is_404(client):
    res = client.post(
        "/api/v1/subagents/connections/nope/message",
        json={"chat_session_id": "x", "message": "hi"},
    )
    assert res.status_code == 404


def test_backend_sync_endpoint(client, monkeypatch):
    from deeptutor.services.subagent import models as models_mod
    from deeptutor.services.subagent.models import BackendOptions, ModelOption

    async def fake_sync(kind):
        return BackendOptions(
            kind=kind,
            display_name="Claude Code",
            available=True,
            models=[ModelOption("opus", "Opus 4.8 · 1M context", efforts=["high"])],
            efforts=["high"],
            allow_custom_model=True,
            synced_at="2026-06-17T00:00:00Z",
        )

    monkeypatch.setattr(models_mod, "sync_backend_options", fake_sync)

    res = client.post("/api/v1/subagents/backends/claude_code/sync")
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "claude_code"
    assert body["models"][0]["slug"] == "opus"
    assert body["synced_at"] == "2026-06-17T00:00:00Z"

    # Unknown backend is rejected.
    assert client.post("/api/v1/subagents/backends/bogus/sync").status_code == 400


def test_settings_put_merges_per_field_and_backend(client):
    # Save one field for claude_code …
    r1 = client.put(
        "/api/v1/subagents/settings",
        json={"backends": {"claude_code": {"model": "opus"}}},
    )
    assert r1.status_code == 200
    # … then another field — the first must survive the merge.
    r2 = client.put(
        "/api/v1/subagents/settings",
        json={"backends": {"claude_code": {"effort": "high"}}},
    )
    cc = r2.json()["backends"]["claude_code"]
    assert cc["model"] == "opus" and cc["effort"] == "high"

    # Saving the OTHER backend must not clobber claude_code.
    r3 = client.put(
        "/api/v1/subagents/settings",
        json={"backends": {"codex": {"sandbox": "read-only"}}},
    )
    body = r3.json()
    assert body["backends"]["claude_code"]["model"] == "opus"
    assert body["backends"]["codex"]["sandbox"] == "read-only"

    # Updating only the budget must leave the backends intact.
    r4 = client.put("/api/v1/subagents/settings", json={"consult_budget": 7})
    body = r4.json()
    assert body["consult_budget"] == 7
    assert body["backends"]["claude_code"]["model"] == "opus"
