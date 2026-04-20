"""Tests for the TutorBot API router."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any
from unittest.mock import MagicMock

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_manager(existing: dict | None = None):
    """Return a (manager, saved) pair.

    Parameters
    ----------
    existing
        If ``None``, simulates "no on-disk config". Otherwise, treated as a
        partial override on top of sensible defaults to construct an existing
        ``BotConfig``.
    """
    from deeptutor.services.tutorbot.manager import BotConfig

    saved: dict = {}

    def _build_existing() -> BotConfig | None:
        if existing is None:
            return None
        defaults: dict[str, Any] = {
            "name": "existing-name",
            "description": "existing description",
            "persona": "existing persona",
            "channels": {},
            "model": None,
        }
        defaults.update(existing)
        return BotConfig(**defaults)

    class FakeManager:
        _MERGEABLE_FIELDS = ("name", "description", "persona", "channels", "model")

        def load_bot_config(self, bot_id: str) -> BotConfig | None:
            return _build_existing()

        def merge_bot_config(self, bot_id: str, overrides: dict[str, Any]) -> BotConfig:
            base = self.load_bot_config(bot_id) or BotConfig(name=bot_id)
            for key in self._MERGEABLE_FIELDS:
                if key in overrides and overrides[key] is not None:
                    setattr(base, key, overrides[key])
            return base

        async def start_bot(self, bot_id: str, config: BotConfig):
            saved["config"] = config
            instance = MagicMock()
            instance.to_dict.return_value = {
                "bot_id": bot_id,
                "name": config.name,
                "channels": config.channels,
                "running": True,
            }
            return instance

    return FakeManager(), saved


def _make_client(monkeypatch, existing: dict | None = None):
    """Build a TestClient with the tutorbot router and a patched manager."""
    manager, saved = _make_fake_manager(existing)

    tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
    monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: manager)

    app = FastAPI()
    app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
    return TestClient(app), saved


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateBotPreservesExistingConfig:
    """Regression tests for the config-wipe bug (issue #331 / PR #332).

    When the web UI starts a bot via POST /api/v1/tutorbot without supplying
    channel config, the previously saved channels must be kept — not wiped.
    """

    def test_channels_preserved_when_payload_has_no_channels(self, monkeypatch):
        """Existing channels on disk must not be wiped when payload omits channels."""
        existing_channels = {
            "telegram": {
                "enabled": True,
                "token": "123:ABC",
                "allow_from": ["999"],
            }
        }
        client, saved = _make_client(
            monkeypatch, existing={"channels": existing_channels}
        )

        resp = client.post("/api/v1/tutorbot", json={"bot_id": "my-bot"})

        assert resp.status_code == 200
        assert saved["config"].channels == existing_channels, (
            "Channels were wiped even though none were provided in the payload"
        )

    def test_payload_channels_override_existing(self, monkeypatch):
        """Explicitly provided channels in payload must take precedence over disk."""
        existing_channels = {"telegram": {"enabled": True, "token": "old"}}
        new_channels = {"slack": {"enabled": True, "token": "new-slack-token"}}

        client, saved = _make_client(
            monkeypatch, existing={"channels": existing_channels}
        )

        resp = client.post(
            "/api/v1/tutorbot",
            json={"bot_id": "my-bot", "channels": new_channels},
        )

        assert resp.status_code == 200
        assert saved["config"].channels == new_channels, (
            "Explicitly provided channels should override existing disk config"
        )

    def test_fresh_bot_with_no_existing_config(self, monkeypatch):
        """A brand-new bot with no existing config should start without error."""
        client, saved = _make_client(monkeypatch, existing=None)

        resp = client.post(
            "/api/v1/tutorbot",
            json={"bot_id": "new-bot", "name": "New Bot"},
        )

        assert resp.status_code == 200
        assert saved["config"].channels == {}
        assert saved["config"].name == "New Bot"

    def test_existing_name_and_persona_preserved(self, monkeypatch):
        """Other fields (description, persona) from disk must also survive when not in payload."""
        client, saved = _make_client(
            monkeypatch, existing={"channels": {"telegram": {"enabled": True}}}
        )

        resp = client.post("/api/v1/tutorbot", json={"bot_id": "my-bot"})

        assert resp.status_code == 200
        assert saved["config"].description == "existing description"
        assert saved["config"].persona == "existing persona"


class TestCreateBotExplicitClearSemantics:
    """Verify the new "explicit empty value clears the field" semantics.

    The original PR #332 fix used ``payload.x or existing.x`` which silently
    swallowed empty strings / empty dicts. Following the upgrade to
    ``model_dump(exclude_unset=True)`` + ``is not None`` merging, clients
    can now intentionally clear fields by sending an explicit empty value.
    """

    def test_explicit_empty_channels_clears_existing(self, monkeypatch):
        """Sending ``channels: {}`` explicitly must clear the disk channels."""
        client, saved = _make_client(
            monkeypatch, existing={"channels": {"telegram": {"enabled": True}}}
        )

        resp = client.post(
            "/api/v1/tutorbot",
            json={"bot_id": "my-bot", "channels": {}},
        )

        assert resp.status_code == 200
        assert saved["config"].channels == {}, (
            "Explicit empty channels dict should clear existing channels, "
            "not silently fall back to the disk value"
        )

    def test_explicit_empty_description_clears_existing(self, monkeypatch):
        """Sending ``description: ''`` explicitly must clear the existing description."""
        client, saved = _make_client(
            monkeypatch,
            existing={"description": "old long description"},
        )

        resp = client.post(
            "/api/v1/tutorbot",
            json={"bot_id": "my-bot", "description": ""},
        )

        assert resp.status_code == 200
        assert saved["config"].description == ""

    def test_omitted_fields_fall_back_to_existing(self, monkeypatch):
        """Fields entirely missing from the payload must inherit from disk."""
        client, saved = _make_client(
            monkeypatch,
            existing={
                "name": "Disk Name",
                "description": "Disk Desc",
                "persona": "Disk Persona",
                "channels": {"telegram": {"enabled": True}},
                "model": "gpt-4o",
            },
        )

        resp = client.post(
            "/api/v1/tutorbot",
            json={"bot_id": "my-bot", "persona": "New Persona"},
        )

        assert resp.status_code == 200
        cfg = saved["config"]
        assert cfg.name == "Disk Name"
        assert cfg.description == "Disk Desc"
        assert cfg.persona == "New Persona"
        assert cfg.channels == {"telegram": {"enabled": True}}
        assert cfg.model == "gpt-4o"

    def test_null_field_in_payload_falls_back_to_existing(self, monkeypatch):
        """Explicit ``null`` for an optional field is treated as 'not provided'.

        This guarantees a frontend that sends ``{description: null}`` (e.g.
        because a form input was unset) does NOT clobber the existing value —
        only an explicit empty string does that.
        """
        client, saved = _make_client(
            monkeypatch, existing={"description": "Disk Desc"}
        )

        resp = client.post(
            "/api/v1/tutorbot",
            json={"bot_id": "my-bot", "description": None},
        )

        assert resp.status_code == 200
        assert saved["config"].description == "Disk Desc"


class TestGetBotStoppedSecretHandling:
    """GET /{bot_id} masks channel secrets by default; ?include_secrets=true reveals them."""

    _CHANNELS = {
        "telegram": {"enabled": True, "token": "123:ABC", "allow_from": ["1"]},
        "send_progress": True,
        "send_tool_hints": False,
    }

    def _client(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return None

            def load_bot_config(self, bot_id: str) -> BotConfig | None:
                return BotConfig(name="b", channels=TestGetBotStoppedSecretHandling._CHANNELS)

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        return TestClient(app)

    def test_default_get_masks_token(self, monkeypatch):
        client = self._client(monkeypatch)
        resp = client.get("/api/v1/tutorbot/b")
        assert resp.status_code == 200
        body = resp.json()
        # Structure preserved, but token replaced with mask
        assert body["channels"]["telegram"]["enabled"] is True
        assert body["channels"]["telegram"]["allow_from"] == ["1"]
        assert body["channels"]["telegram"]["token"] == "***"
        assert body["channels"]["send_progress"] is True
        assert body["running"] is False
        assert body["last_reload_error"] is None

    def test_explicit_include_secrets_reveals_token(self, monkeypatch):
        client = self._client(monkeypatch)
        resp = client.get("/api/v1/tutorbot/b?include_secrets=true")
        assert resp.status_code == 200
        body = resp.json()
        assert body["channels"]["telegram"]["token"] == "123:ABC"


class TestPatchBotStoppedAndRunning:
    """PATCH must work when the bot is stopped; running + channels triggers reload."""

    def test_patch_stopped_saves_and_masks_response(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        saved_cfg: list[BotConfig | None] = []

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return None

            def load_bot_config(self, bot_id: str) -> BotConfig | None:
                return BotConfig(
                    name="b",
                    channels={"telegram": {"enabled": False, "token": ""}},
                )

            def save_bot_config(self, bot_id: str, config: BotConfig, *, auto_start: bool = True) -> None:
                saved_cfg.append(config)

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        new_ch = {"telegram": {"enabled": True, "token": "1:2"}}
        resp = client.patch("/api/v1/tutorbot/b", json={"channels": new_ch})
        assert resp.status_code == 200
        body = resp.json()
        # Disk write keeps the real value
        assert len(saved_cfg) == 1
        assert saved_cfg[0].channels == new_ch
        # Response masks the token
        assert body["channels"]["telegram"]["token"] == "***"
        assert body["channels"]["telegram"]["enabled"] is True

    def test_patch_running_channels_calls_reload(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        reloaded: list[bool] = []

        class FakeInst:
            def __init__(self):
                self.config = BotConfig(name="b", channels={"telegram": {"enabled": True}})
                self._running = True
                self.last_reload_error = None

            @property
            def running(self) -> bool:
                return self._running

            def to_dict(self, *, include_secrets: bool = False, mask_secrets: bool = False):
                return {
                    "bot_id": "b",
                    "name": self.config.name,
                    "channels": [] if not (include_secrets or mask_secrets) else self.config.channels,
                    "running": True,
                    "last_reload_error": self.last_reload_error,
                }

        inst = FakeInst()

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return inst if bot_id == "b" else None

            def save_bot_config(self, bot_id: str, config: BotConfig, *, auto_start: bool = True) -> None:
                pass

            async def reload_channels(self, bot_id: str) -> None:
                reloaded.append(True)

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        resp = client.patch("/api/v1/tutorbot/b", json={"channels": {"telegram": {"enabled": False}}})
        assert resp.status_code == 200
        assert reloaded == [True]

    def test_patch_invalid_channels_rejected_422(self, monkeypatch):
        """Malformed channels must be rejected at the boundary, not after disk write."""
        from deeptutor.services.tutorbot.manager import BotConfig

        saved_cfg: list[BotConfig] = []

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return None

            def load_bot_config(self, bot_id: str) -> BotConfig | None:
                return BotConfig(name="b")

            def save_bot_config(self, bot_id: str, config: BotConfig, *, auto_start: bool = True) -> None:
                saved_cfg.append(config)

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        # send_progress should be a bool, not an int-string-list garbage value;
        # unknown extras are allowed (extra="allow" on ChannelsConfig), so we
        # use a clearly typed-wrong primitive for a known field.
        resp = client.patch(
            "/api/v1/tutorbot/b",
            json={"channels": {"send_progress": ["nope"]}},
        )
        assert resp.status_code == 422
        # IMPORTANT: nothing should have been written to disk
        assert saved_cfg == []

    def test_patch_running_reload_failure_returns_500(self, monkeypatch):
        """If reload_channels raises, PATCH responds with 500 and a hint."""
        from deeptutor.services.tutorbot.manager import BotConfig

        class FakeInst:
            def __init__(self):
                self.config = BotConfig(name="b", channels={"telegram": {"enabled": True}})
                self.last_reload_error = None

            @property
            def running(self) -> bool:
                return True

            def to_dict(self, *, include_secrets: bool = False, mask_secrets: bool = False):
                return {"bot_id": "b", "channels": [], "running": True}

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return FakeInst()

            def save_bot_config(self, bot_id: str, config: BotConfig, *, auto_start: bool = True) -> None:
                pass

            async def reload_channels(self, bot_id: str) -> None:
                raise RuntimeError("telegram bind failed")

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        resp = client.patch(
            "/api/v1/tutorbot/b",
            json={"channels": {"telegram": {"enabled": True, "token": "1:2"}}},
        )
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "RuntimeError" in detail
        assert "stopping and starting" in detail.lower()


class TestBotChatWebSocketStartup:
    """WebSocket endpoint should auto-start stopped configured bots."""

    def test_ws_autostarts_stopped_bot(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        class FakeInstance:
            running = True

            def __init__(self):
                self.notify_queue = asyncio.Queue()

        class FakeMgr:
            def __init__(self):
                self.started: list[str] = []

            def get_bot(self, bot_id: str):
                return None

            def load_bot_config(self, bot_id: str):
                return BotConfig(name=bot_id)

            async def start_bot(self, bot_id: str, config: BotConfig):
                self.started.append(bot_id)
                return FakeInstance()

        mgr = FakeMgr()
        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: mgr)

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        with client.websocket_connect("/api/v1/tutorbot/ielts-tutor/ws") as ws:
            ws.close()

        assert mgr.started == ["ielts-tutor"]

    def test_ws_unknown_bot_returns_error_payload(self, monkeypatch):
        class FakeMgr:
            def get_bot(self, bot_id: str):
                return None

            def load_bot_config(self, bot_id: str):
                return None

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        with client.websocket_connect("/api/v1/tutorbot/missing/ws") as ws:
            payload = ws.receive_json()
            assert payload["type"] == "error"
            assert "not found" in payload["content"].lower()
