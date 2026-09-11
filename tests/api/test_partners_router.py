"""API surface tests for /api/partners (create / config / soul / assets)."""

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
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.services.partners.manager import PartnerManager

    token = set_current_user(
        CurrentUser(
            id="test-admin",
            username="test-admin",
            role="admin",
            scope=UserScope(
                kind="admin",
                user_id="test-admin",
                root=isolated_root,
            ),
        )
    )
    # Fresh manager per test so the module-level singleton can't leak
    # tmp-path state across tests.
    mgr = PartnerManager()
    monkeypatch.setattr(partners_router_mod, "get_partner_manager", lambda: mgr)
    partners_router_mod._start_locks.clear()

    app = FastAPI()
    app.include_router(partners_router_mod.router, prefix="/api/partners")
    try:
        yield TestClient(app)
    finally:
        reset_current_user(token)


def _create(client: TestClient, **overrides):
    payload = {
        "name": "Ada",
        "description": "study partner",
        "soul": {"source": "custom", "content": "# Soul\nBe rigorous."},
        "start": False,
        **overrides,
    }
    return client.post("/api/partners", json=payload)


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

    def test_omitted_mcp_tools_defaults_to_deny(self, client):
        # A create that says nothing about MCP must not inherit the deployment's
        # configured MCP tools; ``null`` stays the deliberate opt-in to all.
        assert _create(client).status_code == 200
        assert client.get("/api/partners/ada").json()["mcp_tools"] == []
        assert _create(client, partner_id="bob", name="Bob", mcp_tools=None).status_code == 200
        assert client.get("/api/partners/bob").json()["mcp_tools"] is None

    def test_chat_draft_confirmation_uses_the_same_creation_transaction(self, client):
        from deeptutor.services.partners.drafts import PartnerDraftStore

        draft = PartnerDraftStore().create(
            {
                "name": "Draft Ada",
                "description": "draft description",
                "soul": "# Soul\nDraft soul",
                "language": "en",
                "emoji": "📐",
                "color": "#3366aa",
            }
        )
        response = client.post(
            f"/api/partners/drafts/{draft.draft_id}/confirm",
            json={"name": "Confirmed Ada", "start": False},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Confirmed Ada"
        partner_id = response.json()["partner_id"]
        assert client.get(f"/api/partners/{partner_id}/soul").json()["content"] == (
            "# Soul\nDraft soul"
        )

        repeated = client.post(
            f"/api/partners/drafts/{draft.draft_id}/confirm",
            json={"start": False},
        )
        assert repeated.status_code == 200
        assert repeated.json()["partner_id"] == partner_id
        assert repeated.json()["already_created"] is True


class TestChannelOnboarding:
    def _install_feishu_manager(self, monkeypatch) -> None:
        from urllib.parse import parse_qs

        from deeptutor.api.routers import partners as router_mod
        from deeptutor.services.partners.channel_onboarding import (
            ChannelOnboardingManager,
        )

        polls = [
            {"error": "authorization_pending"},
            {
                "client_id": "cli_app",
                "client_secret": "app_secret",
                "user_info": {"open_id": "ou_scanner"},
            },
        ]

        def handler(request):
            if request.url.path != "/oauth/v1/app/registration":
                raise AssertionError(request.url)
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            if form["action"] == "init":
                return __import__("httpx").Response(
                    200, json={"supported_auth_methods": ["client_secret"]}
                )
            if form["action"] == "begin":
                return __import__("httpx").Response(
                    200,
                    json={
                        "device_code": "device-code",
                        "verification_uri_complete": "https://accounts.feishu.cn/scan",
                        "interval": 1,
                        "expire_in": 60,
                    },
                )
            return __import__("httpx").Response(400, json=polls.pop(0))

        transport = __import__("httpx").MockTransport(handler)
        manager = ChannelOnboardingManager(
            client_factory=lambda: __import__("httpx").AsyncClient(transport=transport)
        )
        monkeypatch.setattr(router_mod, "get_channel_onboarding_manager", lambda: manager)

    def test_start_status_apply_and_terminal_apply(self, client, monkeypatch, isolated_root):
        self._install_feishu_manager(monkeypatch)
        assert _create(client).status_code == 200

        started = client.post(
            "/api/partners/ada/channel-onboarding/start",
            json={"channel": "feishu"},
        )
        assert started.status_code == 200
        body = started.json()
        assert body["status"] == "pending_scan"
        assert "device-code" not in json.dumps(body)

        session_id = body["session_id"]
        assert (
            client.get(f"/api/partners/ada/channel-onboarding/{session_id}").json()["status"]
            == "pending_scan"
        )
        ready = client.get(f"/api/partners/ada/channel-onboarding/{session_id}").json()
        assert ready["status"] == "ready"

        applied = client.post(f"/api/partners/ada/channel-onboarding/{session_id}/apply")
        assert applied.status_code == 200
        assert applied.json()["channels"]["feishu"]["app_secret"] == "***"

        config = yaml.safe_load((isolated_root / "partners" / "ada" / "config.yaml").read_text())
        assert config["channels"]["feishu"]["app_secret"] == "app_secret"
        assert config["channels"]["feishu"]["allow_from"] == ["ou_scanner"]

        repeat = client.post(f"/api/partners/ada/channel-onboarding/{session_id}/apply")
        assert repeat.status_code == 409

    def test_channel_runtime_qr_output_is_available_to_the_webui(self, client):
        from types import SimpleNamespace

        from deeptutor.api.routers import partners as router_mod

        assert _create(client).status_code == 200
        manager = router_mod.get_partner_manager()
        manager._partners["ada"] = SimpleNamespace(
            running=True,
            config=SimpleNamespace(channels={"whatsapp": {"enabled": True}}),
            channel_manager=SimpleNamespace(
                get_status=lambda: {
                    "whatsapp": {
                        "enabled": True,
                        "running": True,
                        "setup": {
                            "status": "waiting_for_scan",
                            "qr_payload": "scan-me",
                        },
                    }
                }
            ),
        )

        response = client.get("/api/partners/ada/channels/status")

        assert response.status_code == 200
        setup = response.json()["channels"]["whatsapp"]["setup"]
        assert setup["status"] == "waiting_for_scan"
        assert setup["qr_payload"] == "scan-me"
        assert setup["qr_data_url"].startswith("data:image/png;base64,")

    def test_onboarding_errors_and_scope(self, client, monkeypatch):
        self._install_feishu_manager(monkeypatch)
        assert _create(client).status_code == 200

        missing = client.post(
            "/api/partners/ghost/channel-onboarding/start",
            json={"channel": "feishu"},
        )
        assert missing.status_code == 404

        invalid = client.post(
            "/api/partners/ada/channel-onboarding/start",
            json={"channel": "telegram"},
        )
        assert invalid.status_code == 422

        started = client.post(
            "/api/partners/ada/channel-onboarding/start",
            json={"channel": "feishu"},
        ).json()
        assert (
            client.get(f"/api/partners/bob/channel-onboarding/{started['session_id']}").status_code
            == 404
        )
        assert client.get("/api/partners/ada/channel-onboarding/not-a-session").status_code == 404
        not_ready = client.post(
            f"/api/partners/ada/channel-onboarding/{started['session_id']}/apply"
        )
        assert not_ready.status_code == 409

        cancelled = client.delete(f"/api/partners/ada/channel-onboarding/{started['session_id']}")
        assert cancelled.json()["status"] == "cancelled"

    def test_onboarding_routes_carry_the_partner_manage_gate(self, monkeypatch):
        """The real app must gate the onboarding routes on *manage*, not just auth.

        These routes write a channel bot token into the partner's config, so
        they belong to whoever may configure the partner — its owner or an
        admin — never to any signed-in account that knows the id. Partners
        stopped being a blanket admin resource in v1.5.17: ``main.py`` mounts
        the router under ``_auth`` and each route declares ``_USABLE`` or
        ``_MANAGEABLE`` for the partner it names. That per-route declaration is
        easy to forget on a new route, and this is what notices.

        The ``client`` fixture above mounts the partners router *without* those
        dependencies so the endpoint tests can drive it directly, so nothing
        else in this file would notice if the gate went missing.

        Asserted by sending a valid **non-admin** token, rather than by
        inspecting ``app.routes``: FastAPI 0.141 stopped flattening
        ``include_router`` into the parent app (it keeps the sub-router nested
        behind ``include_context``), so every structural assertion available
        here holds on only one side of this project's own ``fastapi>=0.100.0``
        range. A response code does not care how the router is represented.

        The body is deliberately invalid, which is what makes the assertion
        sharp. A gated route rejects the caller in a dependency, before the
        body is ever validated — 404 when the partner is unknown *or* invisible
        (``usable_partner`` answers both alike so ids cannot be enumerated),
        403 when it is visible but not theirs. An **ungated** route would reach
        body validation and answer 422, and an unauthenticated request would
        not discriminate at all: ``require_auth`` alone answers 401, so a route
        that had lost its partner gate would still look protected.
        """
        from deeptutor.api import main as api_main
        from deeptutor.api.routers import auth as auth_module
        from deeptutor.api.routers import partners as partners_module
        from deeptutor.services import auth as auth_service

        assert any(
            route.path == "/{partner_id}/channel-onboarding/start"
            for route in partners_module.router.routes
        )

        # The gates wave everything through when auth is disabled, which is the
        # default in tests — turn it on so they are observable.
        monkeypatch.setattr(auth_module, "AUTH_ENABLED", True)
        # ``decode_token`` refuses every token when no secret is configured,
        # which is the state of a bare test environment — without this the
        # request would 401 and the assertion below could not tell a gated
        # route from a merely authenticated one.
        monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-secret")
        monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
        token = auth_service.create_token("not-an-admin", role="user", user_id="u-1")
        # No context manager: this must not run the app's lifespan.
        client = TestClient(api_main.app)
        response = client.post(
            "/api/partners/no-such-partner/channel-onboarding/start",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (403, 404), (
            "onboarding start is not manage-gated (a role=user token got "
            f"{response.status_code}; 422 means the request reached body validation, "
            "so the route is mounted without _MANAGEABLE)"
        )

    def test_every_route_naming_a_partner_declares_its_rights(self):
        """No ``{partner_id}`` route may be left to the router's bare ``_auth``.

        The test above cannot tell ``_USABLE`` from ``_MANAGEABLE``: both
        answer an outsider with 404. This one can, and it sweeps the whole
        router rather than the routes someone remembered to test — which is
        the shape the mistake actually takes. When partners stopped being
        admin-only, six credential routes kept the ``_auth``-only mount they
        had inherited from the blanket gate, and any signed-in account could
        write a channel bot token into anyone's partner.

        Introspection is safe here because it reads the router's *own*
        ``routes``, not the mounted app's: the FastAPI 0.141 nesting change
        that rules out asserting against ``api_main.app`` does not touch this.
        """
        from deeptutor.api.routers import partners as partners_module

        # Writing or reading channel credentials is configuration, so these
        # must be manage-gated specifically; use rights are not enough.
        manage_only = ("/channel-onboarding", "/channels/weixin/qr", "/soul", "/assets")

        ungated: list[str] = []
        under_gated: list[str] = []
        for route in partners_module.router.routes:
            path = getattr(route, "path", "")
            if "{partner_id}" not in path:
                continue
            # The socket cannot run HTTP dependencies; it checks by hand.
            if not getattr(route, "methods", None):
                continue
            names = {
                getattr(dep.dependency, "__name__", "")
                for dep in getattr(route, "dependencies", [])
            }
            if not names & {"usable_partner", "manageable_partner"}:
                ungated.append(path)
            elif any(part in path for part in manage_only) and "manageable_partner" not in names:
                under_gated.append(path)

        assert not ungated, f"partner routes with no use/manage gate: {ungated}"
        assert not under_gated, f"configuration routes gated on use, not manage: {under_gated}"

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
        soul = client.get("/api/partners/mathy/soul").json()
        assert "math tutor" in soul["content"].lower()

    def test_create_with_unknown_library_soul_404(self, client):
        res = _create(client, soul={"source": "library", "id": "ghost"})
        assert res.status_code == 404


class TestConfigAndSoul:
    def test_get_masks_secrets_by_default(self, client):
        _create(client, channels={"telegram": {"enabled": True, "token": "raw"}})
        body = client.get("/api/partners/ada").json()
        assert body["channels"]["telegram"]["token"] == "***"
        body = client.get("/api/partners/ada?include_secrets=true").json()
        assert body["channels"]["telegram"]["token"] == "raw"

    def test_patch_updates_tools_and_clears(self, client):
        _create(client, enabled_tools=["web_search", "paper_search"])
        res = client.patch(
            "/api/partners/ada",
            json={"enabled_tools": [], "mcp_tools": ["mcp_x_y"]},
        )
        assert res.status_code == 200
        body = client.get("/api/partners/ada").json()
        assert body["enabled_tools"] == []
        assert body["mcp_tools"] == ["mcp_x_y"]

    def test_builtin_tools_create_and_patch(self, client):
        res = _create(client, builtin_tools=["rag", "read_memory"])
        assert res.status_code == 200
        assert res.json()["builtin_tools"] == ["rag", "read_memory"]
        # Default (omitted) stays null = no gating; an explicit deny persists.
        _create(client, partner_id="bob", name="Bob")
        assert client.get("/api/partners/bob").json()["builtin_tools"] is None
        res = client.patch("/api/partners/ada", json={"builtin_tools": []})
        assert res.status_code == 200
        assert client.get("/api/partners/ada").json()["builtin_tools"] == []

    def test_tool_options_exposes_builtin_tools(self, client):
        body = client.get("/api/partners/tool-options").json()
        assert {"tools", "builtin_tools", "mcp_tools"} <= set(body)
        builtin_names = {t["name"] for t in body["builtin_tools"]}
        # rag stays owner-configurable; the chat memory tools are NOT — partners
        # use the mandatory partner_read / partner_memorize / partner_search
        # instead, so they never surface in the partner config UI.
        assert "rag" in builtin_names
        assert "read_memory" not in builtin_names
        assert "write_memory" not in builtin_names

    def test_tool_options_honors_global_chat_toggles(self, client):
        # A tool the admin turned off in Settings → Chat → Tools must not
        # appear in the partner Mind picker — the two surfaces share one pool.
        # (``client`` already activates the ``isolated_root`` path isolation.)
        from deeptutor.multi_user.paths import get_admin_path_service

        path = get_admin_path_service().get_settings_file("interface")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"enabled_optional_tools": ["reason"]}), encoding="utf-8")

        body = client.get("/api/partners/tool-options").json()
        tool_names = {t["name"] for t in body["tools"]}
        assert tool_names == {"reason"}
        assert "web_search" not in tool_names
        # The auto-mounted built-ins are a separate axis, unaffected by the
        # user-toggleable chat toggles.
        assert "rag" in {t["name"] for t in body["builtin_tools"]}

    def test_avatar_roundtrip_and_validation(self, client):
        _create(client)
        avatar = "data:image/png;base64,iVBORw0KGgo="
        res = client.patch("/api/partners/ada", json={"avatar": avatar})
        assert res.status_code == 200
        assert client.get("/api/partners/ada").json()["avatar"] == avatar

        # Clearing works; junk and oversized payloads are rejected.
        assert client.patch("/api/partners/ada", json={"avatar": ""}).status_code == 200
        assert client.get("/api/partners/ada").json()["avatar"] == ""
        res = client.patch("/api/partners/ada", json={"avatar": "https://evil.example/x.png"})
        assert res.status_code == 422
        res = client.patch(
            "/api/partners/ada",
            json={"avatar": "data:image/png;base64," + "A" * 200_001},
        )
        assert res.status_code == 422

    def test_soul_roundtrip(self, client):
        _create(client)
        res = client.put("/api/partners/ada/soul", json={"content": "# Soul\nUpdated."})
        assert res.status_code == 200
        assert client.get("/api/partners/ada/soul").json()["content"] == "# Soul\nUpdated."

    def test_404_for_unknown_partner(self, client):
        assert client.get("/api/partners/ghost").status_code == 404
        assert client.get("/api/partners/ghost/soul").status_code == 404


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

        res = client.post("/api/partners/ada/assets", json={"skills": ["focus"]})
        assert res.status_code == 200
        assert res.json()["copied"]["skills"] == ["focus"]
        assert [s["name"] for s in res.json()["assets"]["skills"]] == ["focus"]

        res = client.delete("/api/partners/ada/assets/skill/focus")
        assert res.status_code == 200
        assert res.json()["assets"]["skills"] == []

    def test_unknown_asset_reported_in_errors(self, client):
        _create(client)
        res = client.post("/api/partners/ada/assets", json={"skills": ["ghost"]})
        assert res.status_code == 200
        assert res.json()["errors"][0]["type"] == "skill"


class TestSoulLibraryEndpoints:
    def test_souls_crud(self, client):
        res = client.get("/api/partners/souls")
        assert res.status_code == 200
        assert any(s["id"] == "math-tutor" for s in res.json())

        res = client.post(
            "/api/partners/souls",
            json={"id": "custom-soul", "name": "Custom", "content": "# Soul"},
        )
        assert res.status_code == 200
        assert client.get("/api/partners/souls/custom-soul").status_code == 200
        assert (
            client.put("/api/partners/souls/custom-soul", json={"name": "Renamed"}).json()["name"]
            == "Renamed"
        )
        assert client.delete("/api/partners/souls/custom-soul").status_code == 200
        assert client.get("/api/partners/souls/custom-soul").status_code == 404

    def test_soul_cjk_id_is_ascii_safe(self, client):
        # A pure-CJK soul name must not become a non-ASCII (unreachable) id: the
        # server slugs it authoritatively and the returned id is URL-safe.
        res = client.post(
            "/api/partners/souls",
            json={"id": "我的灵魂", "name": "我的灵魂", "content": "# Soul"},
        )
        assert res.status_code == 200
        soul_id = res.json()["id"]
        assert soul_id.isascii() and soul_id.startswith("soul-")
        # …and the soul is reachable / deletable by that returned id.
        assert client.get(f"/api/partners/souls/{soul_id}").status_code == 200
        assert client.delete(f"/api/partners/souls/{soul_id}").status_code == 200

    def test_soul_sources_shape(self, client):
        body = client.get("/api/partners/soul-sources").json()
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
        res = client.get("/api/partners/ada/history")
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
        res = client.get("/api/partners/ada/history?session_id=s1")
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
        res = client.get("/api/partners/ada/sessions")
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
            client.post("/api/partners/ada/sessions/archive", json={"session_key": "web-a"})
        ).status_code == 200
        archived = {s["session_key"]: s for s in client.get("/api/partners/ada/sessions").json()}
        assert archived["web-a"]["archived"] is True
        assert (
            client.post("/api/partners/ada/sessions/resume", json={"session_key": "web-a"})
        ).status_code == 200
        live = {s["session_key"]: s for s in client.get("/api/partners/ada/sessions").json()}
        assert live["web-a"]["archived"] is False

    def test_archiving_missing_session_is_not_silently_successful(self, client):
        _create(client)

        response = client.post(
            "/api/partners/ada/sessions/archive",
            json={"session_key": "missing"},
        )

        assert response.status_code == 404

    def test_branch_copies_and_archives(self, client, isolated_root):
        _create(client)
        self._seed_session(isolated_root, "web-a", "carry me")
        res = client.post(
            "/api/partners/ada/sessions/branch",
            json={"source_key": "web-a", "new_key": "web-b"},
        )
        assert res.status_code == 200
        assert res.json()["session"]["session_key"] == "web-b"
        hist = client.get("/api/partners/ada/history?session_key=web-b").json()
        assert [m["content"] for m in hist] == ["carry me"]
        sessions = {s["session_key"]: s for s in client.get("/api/partners/ada/sessions").json()}
        assert sessions["web-a"]["archived"] is True

    def test_delete_session_endpoint(self, client, isolated_root):
        _create(client)
        self._seed_session(isolated_root, "web-a", "bye")
        assert (
            client.post("/api/partners/ada/sessions/delete", json={"session_key": "web-a"})
        ).status_code == 200
        assert client.get("/api/partners/ada/sessions").json() == []
        # Deleting a missing session is a 404.
        assert (
            client.post("/api/partners/ada/sessions/delete", json={"session_key": "web-a"})
        ).status_code == 404


class TestChatAttachments:
    def test_web_chat_lazily_starts_partner_without_enabling_boot_start(
        self, client, monkeypatch, isolated_root
    ):
        from deeptutor.api.routers import partners as router_mod

        with client:
            assert _create(client, start=False).status_code == 200
            manager = router_mod.get_partner_manager()

            async def reply(*args, **kwargs):
                return "hello back"

            monkeypatch.setattr(manager, "send_message", reply)

            res = client.post("/api/partners/ada/chat", json={"content": "hello"})

        assert res.status_code == 200
        assert res.json()["content"] == "hello back"
        assert manager.get_partner("ada") is not None
        data = yaml.safe_load(
            (isolated_root / "partners" / "ada" / "config.yaml").read_text(encoding="utf-8")
        )
        assert data["auto_start"] is False

    def test_code_redeem_list_and_unlink_roundtrip(self, client):
        from deeptutor.services.partners.links import redeem_link_code

        assert _create(client).status_code == 200
        issued = client.post("/api/partners/ada/links/code")

        assert issued.status_code == 200
        payload = issued.json()
        assert payload["command"] == f"/link {payload['code']}"
        assert (
            redeem_link_code(
                "ada",
                payload["code"],
                channel="qq",
                sender_id="90210",
            )
            == "test-admin"
        )

        listed = client.get("/api/partners/ada/links").json()["links"]
        assert [(item["channel"], item["sender_id"]) for item in listed] == [("qq", "90210")]

        assert client.delete("/api/partners/ada/links/qq%3A90210").status_code == 200
        assert client.get("/api/partners/ada/links").json()["links"] == []

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
