"""Tests for the TutorBot API router."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
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
            "llm_selection": None,
            "allow_shell_exec": False,
        }
        defaults.update(existing)
        return BotConfig(**defaults)

    class FakeManager:
        _MERGEABLE_FIELDS = (
            "name",
            "description",
            "persona",
            "channels",
            "model",
            "llm_selection",
            "allow_shell_exec",
        )

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
                "llm_selection": config.llm_selection,
                "allow_shell_exec": config.allow_shell_exec,
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


class TestBotChatHttpApi:
    def test_http_chat_uses_specified_bot_and_session(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        class FakeInstance:
            running = True

        class FakeMgr:
            def __init__(self):
                self.calls: list[dict[str, Any]] = []

            def get_bot(self, bot_id: str):
                return FakeInstance()

            def load_bot_config(self, bot_id: str):
                return BotConfig(name=bot_id)

            async def start_bot(self, bot_id: str, config: BotConfig):
                return FakeInstance()

            async def send_message(self, bot_id: str, content: str, **kwargs):
                self.calls.append({"bot_id": bot_id, "content": content, **kwargs})
                return "answer"

        mgr = FakeMgr()
        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: mgr)
        tutorbot_router_mod._start_locks.clear()

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        response = client.post(
            "/api/v1/tutorbot/math-bot/chat",
            json={"content": "hi", "session_id": "lesson-1"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "bot_id": "math-bot",
            "session_id": "lesson-1",
            "content": "answer",
        }
        assert mgr.calls == [
            {
                "bot_id": "math-bot",
                "content": "hi",
                "chat_id": "lesson-1",
                "session_id": "lesson-1",
            }
        ]

    def test_http_chat_creates_session_when_omitted(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        class FakeInstance:
            running = True

        class FakeMgr:
            def __init__(self):
                self.calls: list[dict[str, Any]] = []

            def get_bot(self, bot_id: str):
                return FakeInstance()

            def load_bot_config(self, bot_id: str):
                return BotConfig(name=bot_id)

            async def start_bot(self, bot_id: str, config: BotConfig):
                return FakeInstance()

            async def send_message(self, bot_id: str, content: str, **kwargs):
                self.calls.append({"bot_id": bot_id, "content": content, **kwargs})
                return "answer"

        mgr = FakeMgr()
        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: mgr)
        tutorbot_router_mod._start_locks.clear()

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        response = client.post("/api/v1/tutorbot/math-bot/chat", json={"content": "hi"})

        assert response.status_code == 200
        body = response.json()
        assert body["bot_id"] == "math-bot"
        assert body["content"] == "answer"
        assert body["session_id"]
        assert body["session_id"] != "web"
        assert mgr.calls == [
            {
                "bot_id": "math-bot",
                "content": "hi",
                "chat_id": body["session_id"],
                "session_id": body["session_id"],
            }
        ]

    def test_http_chat_stream_emits_sse_events(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        class FakeInstance:
            running = True

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return FakeInstance()

            def load_bot_config(self, bot_id: str):
                return BotConfig(name=bot_id)

            async def start_bot(self, bot_id: str, config: BotConfig):
                return FakeInstance()

            async def send_message(self, bot_id: str, content: str, **kwargs):
                on_progress = kwargs.get("on_progress")
                if on_progress:
                    await on_progress("thinking")
                return "streamed answer"

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())
        tutorbot_router_mod._start_locks.clear()

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        response = client.post(
            "/api/v1/tutorbot/math-bot/chat/execute-stream",
            json={"content": "hi", "session_id": "lesson-1"},
        )

        assert response.status_code == 200
        body = response.text
        assert "event: session" in body
        assert '"session_id": "lesson-1"' in body
        assert "event: thinking" in body
        assert "event: content" in body
        assert "streamed answer" in body
        assert "event: done" in body


def _catalog_with_llm_options() -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "p-default",
                "active_model_id": "m-default",
                "profiles": [
                    {
                        "id": "p-default",
                        "name": "OpenAI",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-test",
                        "models": [
                            {
                                "id": "m-default",
                                "name": "GPT Mini",
                                "model": "gpt-4o-mini",
                            }
                        ],
                    },
                    {
                        "id": "p-alt",
                        "name": "OpenRouter",
                        "binding": "openrouter",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-or-test",
                        "models": [
                            {
                                "id": "m-alt",
                                "name": "Claude",
                                "model": "anthropic/claude-sonnet-4",
                            }
                        ],
                    },
                ],
            }
        },
    }


def _patch_llm_catalog(monkeypatch) -> None:
    config_mod = importlib.import_module("deeptutor.services.config")
    monkeypatch.setattr(
        config_mod,
        "get_model_catalog_service",
        lambda: SimpleNamespace(load=_catalog_with_llm_options),
    )


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
        client, saved = _make_client(monkeypatch, existing={"channels": existing_channels})

        resp = client.post("/api/v1/tutorbot", json={"bot_id": "my-bot"})

        assert resp.status_code == 200
        assert saved["config"].channels == existing_channels, (
            "Channels were wiped even though none were provided in the payload"
        )

    def test_payload_channels_override_existing(self, monkeypatch):
        """Explicitly provided channels in payload must take precedence over disk."""
        existing_channels = {"telegram": {"enabled": True, "token": "old"}}
        new_channels = {"slack": {"enabled": True, "token": "new-slack-token"}}

        client, saved = _make_client(monkeypatch, existing={"channels": existing_channels})

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
                "llm_selection": {"profile_id": "p-default", "model_id": "m-default"},
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
        assert cfg.llm_selection == {"profile_id": "p-default", "model_id": "m-default"}

    def test_shell_exec_setting_is_preserved_when_omitted(self, monkeypatch):
        client, saved = _make_client(
            monkeypatch,
            existing={"allow_shell_exec": True},
        )

        resp = client.post("/api/v1/tutorbot", json={"bot_id": "my-bot", "name": "New"})

        assert resp.status_code == 200
        assert saved["config"].allow_shell_exec is True

    def test_shell_exec_cannot_be_enabled_from_router_payload(self, monkeypatch):
        client, saved = _make_client(monkeypatch, existing=None)

        resp = client.post(
            "/api/v1/tutorbot",
            json={"bot_id": "my-bot", "allow_shell_exec": True},
        )

        assert resp.status_code == 200
        assert saved["config"].allow_shell_exec is False

    def test_null_field_in_payload_falls_back_to_existing(self, monkeypatch):
        """Explicit ``null`` for an optional field is treated as 'not provided'.

        This guarantees a frontend that sends ``{description: null}`` (e.g.
        because a form input was unset) does NOT clobber the existing value —
        only an explicit empty string does that.
        """
        client, saved = _make_client(monkeypatch, existing={"description": "Disk Desc"})

        resp = client.post(
            "/api/v1/tutorbot",
            json={"bot_id": "my-bot", "description": None},
        )

        assert resp.status_code == 200
        assert saved["config"].description == "Disk Desc"

    def test_create_bot_saves_valid_llm_selection(self, monkeypatch):
        """A new UI-managed bot should persist the selected catalog model."""
        _patch_llm_catalog(monkeypatch)
        client, saved = _make_client(monkeypatch, existing=None)

        selection = {"profile_id": "p-alt", "model_id": "m-alt"}
        resp = client.post(
            "/api/v1/tutorbot",
            json={"bot_id": "my-bot", "name": "My Bot", "llm_selection": selection},
        )

        assert resp.status_code == 200
        assert saved["config"].llm_selection == selection

    def test_create_bot_rejects_invalid_llm_selection(self, monkeypatch):
        """Unknown catalog references fail at the API boundary."""
        _patch_llm_catalog(monkeypatch)
        client, _saved = _make_client(monkeypatch, existing=None)

        resp = client.post(
            "/api/v1/tutorbot",
            json={
                "bot_id": "my-bot",
                "name": "My Bot",
                "llm_selection": {"profile_id": "missing", "model_id": "m-alt"},
            },
        )

        assert resp.status_code == 422
        assert "Invalid LLM selection" in resp.json()["detail"]


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
                return BotConfig(
                    name="b",
                    channels=TestGetBotStoppedSecretHandling._CHANNELS,
                    llm_selection={"profile_id": "p-default", "model_id": "m-default"},
                )

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
        assert body["llm_selection"] == {"profile_id": "p-default", "model_id": "m-default"}

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

            def save_bot_config(
                self, bot_id: str, config: BotConfig, *, auto_start: bool = True
            ) -> None:
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

    def test_patch_stopped_can_clear_llm_selection(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        saved_cfg: list[BotConfig | None] = []

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return None

            def load_bot_config(self, bot_id: str) -> BotConfig | None:
                return BotConfig(
                    name="b",
                    llm_selection={"profile_id": "p-alt", "model_id": "m-alt"},
                )

            def save_bot_config(
                self, bot_id: str, config: BotConfig, *, auto_start: bool = True
            ) -> None:
                saved_cfg.append(config)

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        resp = client.patch("/api/v1/tutorbot/b", json={"llm_selection": None})

        assert resp.status_code == 200
        assert saved_cfg[0].llm_selection is None
        assert resp.json()["llm_selection"] is None

    def test_patch_stopped_can_update_shell_exec_flag(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        saved_cfg: list[BotConfig | None] = []

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return None

            def load_bot_config(self, bot_id: str) -> BotConfig | None:
                return BotConfig(name="b", allow_shell_exec=False)

            def save_bot_config(
                self, bot_id: str, config: BotConfig, *, auto_start: bool = True
            ) -> None:
                saved_cfg.append(config)

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        resp = client.patch("/api/v1/tutorbot/b", json={"allow_shell_exec": True})

        assert resp.status_code == 200
        assert saved_cfg[0].allow_shell_exec is True
        assert resp.json()["allow_shell_exec"] is True

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
                    "channels": []
                    if not (include_secrets or mask_secrets)
                    else self.config.channels,
                    "running": True,
                    "last_reload_error": self.last_reload_error,
                }

        inst = FakeInst()

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return inst if bot_id == "b" else None

            def save_bot_config(
                self, bot_id: str, config: BotConfig, *, auto_start: bool = True
            ) -> None:
                pass

            async def reload_channels(self, bot_id: str) -> None:
                reloaded.append(True)

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        resp = client.patch(
            "/api/v1/tutorbot/b", json={"channels": {"telegram": {"enabled": False}}}
        )
        assert resp.status_code == 200
        assert reloaded == [True]

    def test_patch_running_llm_selection_calls_reload_llm(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        _patch_llm_catalog(monkeypatch)
        reloaded: list[str] = []
        saved_cfg: list[BotConfig] = []
        selection = {"profile_id": "p-alt", "model_id": "m-alt"}

        class FakeInst:
            def __init__(self):
                self.config = BotConfig(name="b")

            @property
            def running(self) -> bool:
                return True

            def to_dict(self, *, include_secrets: bool = False, mask_secrets: bool = False):
                return {
                    "bot_id": "b",
                    "name": self.config.name,
                    "channels": [],
                    "running": True,
                    "llm_selection": self.config.llm_selection,
                }

        inst = FakeInst()

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return inst if bot_id == "b" else None

            def save_bot_config(
                self, bot_id: str, config: BotConfig, *, auto_start: bool = True
            ) -> None:
                saved_cfg.append(config)

            async def reload_llm(self, bot_id: str) -> None:
                reloaded.append(bot_id)

        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: FakeMgr())

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        resp = client.patch("/api/v1/tutorbot/b", json={"llm_selection": selection})

        assert resp.status_code == 200
        assert saved_cfg[0].llm_selection == selection
        assert reloaded == ["b"]
        assert resp.json()["llm_selection"] == selection

    def test_patch_invalid_channels_rejected_422(self, monkeypatch):
        """Malformed channels must be rejected at the boundary, not after disk write."""
        from deeptutor.services.tutorbot.manager import BotConfig

        saved_cfg: list[BotConfig] = []

        class FakeMgr:
            def get_bot(self, bot_id: str):
                return None

            def load_bot_config(self, bot_id: str) -> BotConfig | None:
                return BotConfig(name="b")

            def save_bot_config(
                self, bot_id: str, config: BotConfig, *, auto_start: bool = True
            ) -> None:
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

            def save_bot_config(
                self, bot_id: str, config: BotConfig, *, auto_start: bool = True
            ) -> None:
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

    def test_ws_reuses_running_bot_on_reconnect(self, monkeypatch):
        """A second WS connect must not re-trigger start_bot if bot is running."""
        from deeptutor.services.tutorbot.manager import BotConfig

        class FakeInstance:
            running = True

            def __init__(self):
                self.notify_queue = asyncio.Queue()

        class FakeMgr:
            def __init__(self):
                self.start_calls = 0
                self._instance: FakeInstance | None = None

            def get_bot(self, bot_id: str):
                return self._instance

            def load_bot_config(self, bot_id: str):
                return BotConfig(name=bot_id)

            async def start_bot(self, bot_id: str, config: BotConfig):
                self.start_calls += 1
                self._instance = FakeInstance()
                return self._instance

        mgr = FakeMgr()
        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: mgr)
        # Ensure no leftover lock from a prior test affects this one.
        tutorbot_router_mod._start_locks.clear()

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        with client.websocket_connect("/api/v1/tutorbot/dedup-bot/ws") as ws:
            ws.close()
        with client.websocket_connect("/api/v1/tutorbot/dedup-bot/ws") as ws:
            ws.close()

        assert mgr.start_calls == 1


class TestStartLockDedup:
    """Direct test that the per-bot start lock serializes concurrent starts."""

    def test_get_start_lock_serializes_concurrent_blocks(self):
        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        tutorbot_router_mod._start_locks.clear()

        async def runner():
            in_critical = 0
            max_in_critical = 0
            start_calls = 0

            async def fake_start():
                nonlocal in_critical, max_in_critical, start_calls
                lock = await tutorbot_router_mod._get_start_lock("concurrent-bot")
                async with lock:
                    in_critical += 1
                    max_in_critical = max(max_in_critical, in_critical)
                    await asyncio.sleep(0.02)
                    start_calls += 1
                    in_critical -= 1

            await asyncio.gather(fake_start(), fake_start(), fake_start())
            return start_calls, max_in_critical

        start_calls, max_in_critical = asyncio.run(runner())
        assert start_calls == 3
        assert max_in_critical == 1


class TestBotChatWebSocketResilience:
    """The WS handler must tolerate client disconnects during a turn."""

    def test_ws_loop_breaks_on_client_disconnect_before_message(self, monkeypatch):
        from deeptutor.services.tutorbot.manager import BotConfig

        class FakeInstance:
            running = True

            def __init__(self):
                self.notify_queue = asyncio.Queue()

        class FakeMgr:
            def __init__(self):
                self.send_calls = 0

            def get_bot(self, bot_id: str):
                return FakeInstance()

            def load_bot_config(self, bot_id: str):
                return BotConfig(name=bot_id)

            async def start_bot(self, bot_id: str, config: BotConfig):
                return FakeInstance()

            async def send_message(self, *args, **kwargs):
                self.send_calls += 1
                return "should not be reached"

        mgr = FakeMgr()
        tutorbot_router_mod = importlib.import_module("deeptutor.api.routers.tutorbot")
        monkeypatch.setattr(tutorbot_router_mod, "get_tutorbot_manager", lambda: mgr)
        tutorbot_router_mod._start_locks.clear()

        app = FastAPI()
        app.include_router(tutorbot_router_mod.router, prefix="/api/v1/tutorbot")
        client = TestClient(app)

        # Open and immediately close without sending any payload. Both task
        # loops should observe the disconnect and exit cleanly without a
        # background task error.
        with client.websocket_connect("/api/v1/tutorbot/d-bot/ws") as ws:
            ws.close()

        assert mgr.send_calls == 0
