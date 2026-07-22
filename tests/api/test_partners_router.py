"""API surface tests for /api/v1/partners (create / config / soul / assets)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
import yaml

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


@pytest.fixture
def isolated_root(tmp_path, monkeypatch) -> Path:
    from deeptutor.multi_user import paths

    project_root = tmp_path
    admin_root = (project_root / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)
    return admin_root


@pytest.fixture
def client(isolated_root, monkeypatch) -> TestClient:
    import deeptutor.api.routers.partners as partners_router_mod
    from deeptutor.services.partners.manager import PartnerManager

    # Fresh manager per test so the module-level singleton can't leak
    # tmp-path state across tests.
    mgr = PartnerManager()
    monkeypatch.setattr(partners_router_mod, "get_partner_manager", lambda: mgr)
    partners_router_mod._start_locks.clear()

    app = FastAPI()
    app.include_router(partners_router_mod.router, prefix="/api/v1/partners")
    return TestClient(app)


def _create(client: TestClient, **overrides):
    payload = {
        "name": "Ada",
        "description": "study partner",
        "soul": {"source": "custom", "content": "# Soul\nBe rigorous."},
        "start": False,
        **overrides,
    }
    return client.post("/api/v1/partners", json=payload)


class TestCreate:
    def test_create_returns_masked_config(self, client):
        res = _create(
            client,
            channels={"telegram": {"enabled": True, "token": "123:ABC"}},
            enabled_tools=["web_search"],
            mcp_tools=[],
        )
        assert res.status_code == 200
        body = res.json()
        assert body["partner_id"] == "ada"
        assert body["channels"]["telegram"]["token"] == "***"
        assert body["enabled_tools"] == ["web_search"]
        assert body["mcp_tools"] == []
        assert body["soul_origin"] == {"type": "custom", "id": ""}
        assert body["provisioning"]["errors"] == []

    def test_duplicate_id_conflicts(self, client):
        assert _create(client).status_code == 200
        assert _create(client).status_code == 409

    def test_top_level_delivery_flags_rejected(self, client):
        res = _create(client, channels={"send_progress": False})
        assert res.status_code == 422

    def test_create_from_library_soul(self, client):
        res = _create(
            client,
            partner_id="mathy",
            soul={"source": "library", "id": "math-tutor"},
        )
        assert res.status_code == 200
        soul = client.get("/api/v1/partners/mathy/soul").json()
        assert "math tutor" in soul["content"].lower()

    def test_create_with_unknown_library_soul_404(self, client):
        res = _create(client, soul={"source": "library", "id": "ghost"})
        assert res.status_code == 404


class TestConfigAndSoul:
    def test_get_masks_secrets_by_default(self, client):
        _create(client, channels={"telegram": {"enabled": True, "token": "raw"}})
        body = client.get("/api/v1/partners/ada").json()
        assert body["channels"]["telegram"]["token"] == "***"
        body = client.get("/api/v1/partners/ada?include_secrets=true").json()
        assert body["channels"]["telegram"]["token"] == "raw"

    def test_patch_updates_tools_and_clears(self, client):
        _create(client, enabled_tools=["web_search", "paper_search"])
        res = client.patch(
            "/api/v1/partners/ada",
            json={"enabled_tools": [], "mcp_tools": ["mcp_x_y"]},
        )
        assert res.status_code == 200
        body = client.get("/api/v1/partners/ada").json()
        assert body["enabled_tools"] == []
        assert body["mcp_tools"] == ["mcp_x_y"]

    def test_builtin_tools_create_and_patch(self, client):
        res = _create(client, builtin_tools=["rag", "read_memory"])
        assert res.status_code == 200
        assert res.json()["builtin_tools"] == ["rag", "read_memory"]
        # Default (omitted) stays null = no gating; an explicit deny persists.
        _create(client, partner_id="bob", name="Bob")
        assert client.get("/api/v1/partners/bob").json()["builtin_tools"] is None
        res = client.patch("/api/v1/partners/ada", json={"builtin_tools": []})
        assert res.status_code == 200
        assert client.get("/api/v1/partners/ada").json()["builtin_tools"] == []

    def test_tool_options_exposes_builtin_tools(self, client):
        body = client.get("/api/v1/partners/tool-options").json()
        assert {"tools", "builtin_tools", "mcp_tools"} <= set(body)
        builtin_names = {t["name"] for t in body["builtin_tools"]}
        # rag stays owner-configurable; the chat memory tools are NOT — partners
        # use the mandatory partner_read / partner_memorize / partner_search
        # instead, so they never surface in the partner config UI.
        assert "rag" in builtin_names
        assert "read_memory" not in builtin_names
        assert "write_memory" not in builtin_names

    def test_avatar_roundtrip_and_validation(self, client):
        _create(client)
        avatar = "data:image/png;base64,iVBORw0KGgo="
        res = client.patch("/api/v1/partners/ada", json={"avatar": avatar})
        assert res.status_code == 200
        assert client.get("/api/v1/partners/ada").json()["avatar"] == avatar

        # Clearing works; junk and oversized payloads are rejected.
        assert client.patch("/api/v1/partners/ada", json={"avatar": ""}).status_code == 200
        assert client.get("/api/v1/partners/ada").json()["avatar"] == ""
        res = client.patch("/api/v1/partners/ada", json={"avatar": "https://evil.example/x.png"})
        assert res.status_code == 422
        res = client.patch(
            "/api/v1/partners/ada",
            json={"avatar": "data:image/png;base64," + "A" * 200_001},
        )
        assert res.status_code == 422

    def test_soul_roundtrip(self, client):
        _create(client)
        res = client.put("/api/v1/partners/ada/soul", json={"content": "# Soul\nUpdated."})
        assert res.status_code == 200
        assert client.get("/api/v1/partners/ada/soul").json()["content"] == "# Soul\nUpdated."

    def test_404_for_unknown_partner(self, client):
        assert client.get("/api/v1/partners/ghost").status_code == 404
        assert client.get("/api/v1/partners/ghost/soul").status_code == 404


class TestAssets:
    def _seed_skill(self, admin_root: Path, name="focus"):
        skill = admin_root / "user" / "workspace" / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: d\n---\nBody", encoding="utf-8"
        )

    def test_add_list_remove_assets(self, client, isolated_root):
        self._seed_skill(isolated_root)
        _create(client)

        res = client.post("/api/v1/partners/ada/assets", json={"skills": ["focus"]})
        assert res.status_code == 200
        assert res.json()["copied"]["skills"] == ["focus"]
        assert [s["name"] for s in res.json()["assets"]["skills"]] == ["focus"]

        res = client.delete("/api/v1/partners/ada/assets/skill/focus")
        assert res.status_code == 200
        assert res.json()["assets"]["skills"] == []

    def test_unknown_asset_reported_in_errors(self, client):
        _create(client)
        res = client.post("/api/v1/partners/ada/assets", json={"skills": ["ghost"]})
        assert res.status_code == 200
        assert res.json()["errors"][0]["type"] == "skill"


class TestSoulLibraryEndpoints:
    def test_souls_crud(self, client):
        res = client.get("/api/v1/partners/souls")
        assert res.status_code == 200
        assert any(s["id"] == "math-tutor" for s in res.json())

        res = client.post(
            "/api/v1/partners/souls",
            json={"id": "custom-soul", "name": "Custom", "content": "# Soul"},
        )
        assert res.status_code == 200
        assert client.get("/api/v1/partners/souls/custom-soul").status_code == 200
        assert (
            client.put("/api/v1/partners/souls/custom-soul", json={"name": "Renamed"}).json()[
                "name"
            ]
            == "Renamed"
        )
        assert client.delete("/api/v1/partners/souls/custom-soul").status_code == 200
        assert client.get("/api/v1/partners/souls/custom-soul").status_code == 404

    def test_soul_cjk_id_is_ascii_safe(self, client):
        # A pure-CJK soul name must not become a non-ASCII (unreachable) id: the
        # server slugs it authoritatively and the returned id is URL-safe.
        res = client.post(
            "/api/v1/partners/souls",
            json={"id": "我的灵魂", "name": "我的灵魂", "content": "# Soul"},
        )
        assert res.status_code == 200
        soul_id = res.json()["id"]
        assert soul_id.isascii() and soul_id.startswith("soul-")
        # …and the soul is reachable / deletable by that returned id.
        assert client.get(f"/api/v1/partners/souls/{soul_id}").status_code == 200
        assert client.delete(f"/api/v1/partners/souls/{soul_id}").status_code == 200

    def test_soul_sources_shape(self, client):
        body = client.get("/api/v1/partners/soul-sources").json()
        assert "library" in body and "personas" in body


class TestHistory:
    def test_history_reads_session_store(self, client, isolated_root):
        _create(client)
        sessions = isolated_root / "partners" / "ada" / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / "telegram_42.jsonl").write_text(
            json.dumps({"role": "user", "content": "hi", "timestamp": "2026-01-01T00:00:00"})
            + "\n",
            encoding="utf-8",
        )
        res = client.get("/api/v1/partners/ada/history")
        assert res.status_code == 200
        assert res.json()[0]["content"] == "hi"

    def test_history_scoped_by_web_session_id(self, client, isolated_root):
        _create(client)
        sessions = isolated_root / "partners" / "ada" / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        # Two distinct web sessions; the endpoint must scope to the one asked for.
        (sessions / "web_s1.jsonl").write_text(
            json.dumps({"role": "user", "content": "from s1", "timestamp": "t"}) + "\n",
            encoding="utf-8",
        )
        (sessions / "web_s2.jsonl").write_text(
            json.dumps({"role": "user", "content": "from s2", "timestamp": "t"}) + "\n",
            encoding="utf-8",
        )
        res = client.get("/api/v1/partners/ada/history?session_id=s1")
        assert res.status_code == 200
        contents = [m["content"] for m in res.json()]
        assert contents == ["from s1"]

    def test_sessions_list_carries_title(self, client, isolated_root):
        _create(client)
        sessions = isolated_root / "partners" / "ada" / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / "web_s1.jsonl").write_text(
            json.dumps({"role": "user", "content": "what is recursion?", "timestamp": "t"}) + "\n",
            encoding="utf-8",
        )
        res = client.get("/api/v1/partners/ada/sessions")
        assert res.status_code == 200
        assert res.json()[0]["title"] == "what is recursion?"

    def _seed_session(self, isolated_root: Path, key: str, content: str) -> None:
        sessions = isolated_root / "partners" / "ada" / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{key}.jsonl").write_text(
            json.dumps({"role": "user", "content": content, "timestamp": "t"}) + "\n",
            encoding="utf-8",
        )

    def test_archive_then_resume_roundtrip(self, client, isolated_root):
        _create(client)
        self._seed_session(isolated_root, "web-a", "hi")
        assert (
            client.post("/api/v1/partners/ada/sessions/archive", json={"session_key": "web-a"})
        ).status_code == 200
        archived = {s["session_key"]: s for s in client.get("/api/v1/partners/ada/sessions").json()}
        assert archived["web-a"]["archived"] is True
        assert (
            client.post("/api/v1/partners/ada/sessions/resume", json={"session_key": "web-a"})
        ).status_code == 200
        live = {s["session_key"]: s for s in client.get("/api/v1/partners/ada/sessions").json()}
        assert live["web-a"]["archived"] is False

    def test_branch_copies_and_archives(self, client, isolated_root):
        _create(client)
        self._seed_session(isolated_root, "web-a", "carry me")
        res = client.post(
            "/api/v1/partners/ada/sessions/branch",
            json={"source_key": "web-a", "new_key": "web-b"},
        )
        assert res.status_code == 200
        assert res.json()["session"]["session_key"] == "web-b"
        hist = client.get("/api/v1/partners/ada/history?session_key=web-b").json()
        assert [m["content"] for m in hist] == ["carry me"]
        sessions = {s["session_key"]: s for s in client.get("/api/v1/partners/ada/sessions").json()}
        assert sessions["web-a"]["archived"] is True

    def test_delete_session_endpoint(self, client, isolated_root):
        _create(client)
        self._seed_session(isolated_root, "web-a", "bye")
        assert (
            client.post("/api/v1/partners/ada/sessions/delete", json={"session_key": "web-a"})
        ).status_code == 200
        assert client.get("/api/v1/partners/ada/sessions").json() == []
        # Deleting a missing session is a 404.
        assert (
            client.post("/api/v1/partners/ada/sessions/delete", json={"session_key": "web-a"})
        ).status_code == 404


class TestChatAttachments:
    def test_chat_does_not_auto_start_stopped_partner(self, client):
        # ``start=True`` spawns a real PartnerRunner task; drive every request
        # through one shared event loop (context-managed TestClient) so the
        # runner started by create can be cancelled by stop — otherwise each
        # request runs on its own loop and the cancel raises a cross-loop error.
        with client:
            assert _create(client, start=True).status_code == 200
            assert client.post("/api/v1/partners/ada/stop").status_code == 200

            res = client.post("/api/v1/partners/ada/chat", json={"content": "hello"})

        assert res.status_code == 409
        from deeptutor.core.i18n import t

        assert res.json()["detail"] == t("api.partner_stopped_start_required")

    def test_create_start_false_disables_auto_start(self, client, isolated_root):
        assert _create(client, start=False).status_code == 200

        data = yaml.safe_load(
            (isolated_root / "partners" / "ada" / "config.yaml").read_text(encoding="utf-8")
        )
        assert data["auto_start"] is False

    def test_materialize_partner_attachment_writes_partner_media(self, isolated_root):
        from deeptutor.api.routers.partners import (
            ChatAttachmentRequest,
            _materialize_partner_attachments,
        )

        paths = _materialize_partner_attachments(
            "ada",
            [
                ChatAttachmentRequest(
                    type="file",
                    filename="notes.txt",
                    base64=base64.b64encode(b"hello").decode("ascii"),
                    mime_type="text/plain",
                )
            ],
        )

        assert len(paths) == 1
        path = Path(paths[0])
        assert path.read_bytes() == b"hello"
        assert path.name.endswith("_notes.txt")
        assert path.parent == isolated_root / "partners" / "ada" / "media" / "web"
