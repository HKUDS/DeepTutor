"""Unit tests for TutorBotManager config persistence & merging."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from deeptutor.services.tutorbot.manager import BotConfig, TutorBotInstance, TutorBotManager
from deeptutor.services.tutorbot.model_runtime import resolve_tutorbot_llm_config


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TutorBotManager:
    """Return a TutorBotManager whose data dir is a fresh temp directory.

    ``TutorBotManager._path_service`` is a read-only property that returns the
    global singleton, so reads/writes are sandboxed by patching the factory it
    reads from (mirrors tests/services/tutorbot/test_shell_exec_security.py).
    """
    path_service = SimpleNamespace(
        project_root=tmp_path,
        workspace_root=tmp_path,
        get_memory_dir=lambda: tmp_path / "memory",
    )
    monkeypatch.setattr(
        "deeptutor.services.tutorbot.manager.get_path_service",
        lambda: path_service,
    )
    return TutorBotManager()


def _append_session_line(manager: TutorBotManager, bot_id: str, payload: dict) -> None:
    sessions_dir = manager._bot_workspace(bot_id) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    with open(sessions_dir / "chat.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_session_file(
    manager: TutorBotManager,
    bot_id: str,
    filename: str,
    payloads: list[dict],
) -> Path:
    sessions_dir = manager._bot_workspace(bot_id) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / filename
    with open(path, "w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
# load_bot_config / save_bot_config
# ---------------------------------------------------------------------------


class TestLoadAndSave:
    def test_load_returns_none_when_no_config(self, manager: TutorBotManager):
        assert manager.load_bot_config("nonexistent") is None

    def test_save_then_load_roundtrip(self, manager: TutorBotManager):
        cfg = BotConfig(
            name="My Bot",
            description="d",
            persona="p",
            channels={"telegram": {"enabled": True, "token": "tok"}},
            model="gpt-4o",
            llm_selection={"profile_id": "p1", "model_id": "m1"},
        )
        manager.save_bot_config("bot-a", cfg)

        loaded = manager.load_bot_config("bot-a")
        assert loaded == cfg

    def test_load_corrupt_yaml_returns_none(self, manager: TutorBotManager):
        bot_dir = manager._bot_dir("bad-bot")
        bot_dir.mkdir(parents=True, exist_ok=True)
        (bot_dir / "config.yaml").write_text(": not :: valid : yaml ::", encoding="utf-8")

        assert manager.load_bot_config("bad-bot") is None


class TestMessageHistory:
    def test_history_normalizes_part_content_and_strips_reasoning(self, manager: TutorBotManager):
        _append_session_line(
            manager,
            "bot-history",
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Here is the image"},
                    {"type": "image", "alt": "diagram"},
                ],
                "reasoning_content": "internal scratchpad",
            },
        )

        history = manager.get_bot_history("bot-history")

        assert history == [{"role": "assistant", "content": "Here is the image diagram"}]

    def test_history_is_chronological_across_legacy_and_canonical_sessions(
        self, manager: TutorBotManager
    ):
        _write_session_file(
            manager,
            "bot-history",
            "web_legacy.jsonl",
            [
                {
                    "role": "user",
                    "content": "old user",
                    "timestamp": "2026-03-20T20:12:59.665712",
                },
                {
                    "role": "assistant",
                    "content": "old assistant",
                    "timestamp": "2026-03-20T20:13:00.665712",
                },
            ],
        )
        _write_session_file(
            manager,
            "bot-history",
            "bot_history.jsonl",
            [
                {
                    "role": "user",
                    "content": "new user",
                    "timestamp": "2026-05-03T15:25:53.085811",
                },
                {
                    "role": "assistant",
                    "content": "new assistant",
                    "timestamp": "2026-05-03T15:25:54.085811",
                },
            ],
        )

        history = manager.get_bot_history("bot-history")

        assert [m["content"] for m in history] == [
            "old user",
            "old assistant",
            "new user",
            "new assistant",
        ]

    def test_recent_active_bots_normalizes_last_message(self, manager: TutorBotManager):
        manager.save_bot_config("bot-recent", BotConfig(name="Recent Bot"))
        _append_session_line(
            manager,
            "bot-recent",
            {
                "role": "user",
                "content": [{"type": "text", "text": "look"}, {"type": "image"}],
            },
        )

        recent = manager.get_recent_active_bots(limit=1)

        assert recent[0]["bot_id"] == "bot-recent"
        assert recent[0]["last_message"] == "look [image]"


def test_web_session_key_preserves_default_and_supports_explicit_sessions() -> None:
    manager = TutorBotManager()

    assert manager.web_session_key("math-bot") == "bot:math-bot"
    assert manager.web_session_key("math-bot", chat_id="thread-1") == "web:thread-1"
    assert (
        manager.web_session_key("math-bot", chat_id="thread-1", session_id="lesson-1")
        == "web:lesson-1"
    )


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_save_uses_temp_file_and_replace(self, manager: TutorBotManager, monkeypatch):
        """save_bot_config must write to a temp file then atomically replace.

        We assert that:
          1. A ``.tmp`` file is created during the write.
          2. After the call, only the final ``config.yaml`` exists (the temp
             file has been moved into place via Path.replace).
        """
        cfg = BotConfig(name="atomic", channels={"telegram": {"enabled": True}})

        observed: dict[str, list[Path]] = {"tmp_writes": [], "replaces": []}
        original_write_text = Path.write_text
        original_replace = Path.replace

        def tracked_write_text(self_path: Path, *args, **kwargs):
            if self_path.suffix == ".tmp":
                observed["tmp_writes"].append(Path(self_path))
            return original_write_text(self_path, *args, **kwargs)

        def tracked_replace(self_path: Path, target: Path):
            observed["replaces"].append((Path(self_path), Path(target)))
            return original_replace(self_path, target)

        monkeypatch.setattr(Path, "write_text", tracked_write_text)
        monkeypatch.setattr(Path, "replace", tracked_replace)

        manager.save_bot_config("atomic-bot", cfg)

        bot_dir = manager._bot_dir("atomic-bot")
        final = bot_dir / "config.yaml"
        tmp = bot_dir / "config.yaml.tmp"

        assert final.exists()
        assert not tmp.exists(), "Temp file must be moved away after save"
        assert observed["tmp_writes"], "Expected a write to a .tmp file"
        assert observed["replaces"], "Expected Path.replace to be called"

    def test_save_does_not_corrupt_existing_on_failed_write(
        self, manager: TutorBotManager, monkeypatch
    ):
        """If the write fails midway, the previous on-disk config must survive."""
        good_cfg = BotConfig(name="orig", channels={"telegram": {"enabled": True}})
        manager.save_bot_config("safe-bot", good_cfg)

        original_write_text = Path.write_text

        def boom(self_path: Path, *args, **kwargs):
            if self_path.suffix == ".tmp":
                raise OSError("disk full")
            return original_write_text(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", boom)

        with pytest.raises(OSError):
            manager.save_bot_config("safe-bot", BotConfig(name="new", channels={}))

        # Original config must still be intact.
        loaded = manager.load_bot_config("safe-bot")
        assert loaded == good_cfg


# ---------------------------------------------------------------------------
# merge_bot_config
# ---------------------------------------------------------------------------


class TestMergeBotConfig:
    def test_merge_with_no_existing_uses_defaults(self, manager: TutorBotManager):
        merged = manager.merge_bot_config("brand-new", {"name": "X"})
        assert merged.name == "X"
        assert merged.description == ""
        assert merged.channels == {}

    def test_merge_keeps_existing_when_overrides_omit_field(self, manager: TutorBotManager):
        manager.save_bot_config(
            "bot-1",
            BotConfig(name="Disk", description="dd", channels={"telegram": {}}),
        )

        merged = manager.merge_bot_config("bot-1", {"persona": "p"})
        assert merged.name == "Disk"
        assert merged.description == "dd"
        assert merged.persona == "p"
        assert merged.channels == {"telegram": {}}

    def test_merge_treats_none_as_not_provided(self, manager: TutorBotManager):
        manager.save_bot_config(
            "bot-2",
            BotConfig(name="Disk", description="dd"),
        )

        merged = manager.merge_bot_config("bot-2", {"description": None, "name": "New"})
        assert merged.name == "New"
        assert merged.description == "dd"

    def test_merge_treats_empty_string_and_dict_as_explicit_clear(self, manager: TutorBotManager):
        manager.save_bot_config(
            "bot-3",
            BotConfig(
                name="Disk",
                description="dd",
                channels={"telegram": {"enabled": True}},
            ),
        )

        merged = manager.merge_bot_config("bot-3", {"description": "", "channels": {}})
        assert merged.description == ""
        assert merged.channels == {}

    def test_merge_ignores_unknown_keys(self, manager: TutorBotManager):
        merged = manager.merge_bot_config("bot-4", {"name": "X", "unknown_field": "boom"})
        assert merged.name == "X"
        assert not hasattr(merged, "unknown_field")


class TestTutorBotModelRuntime:
    def test_selection_is_resolved_through_model_selection_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict[str, str] | None] = []

        def fake_resolve(selection):
            captured.append(selection)
            return SimpleNamespace(model="selected-model")

        monkeypatch.setattr(
            "deeptutor.services.tutorbot.model_runtime.resolve_llm_config_for_selection",
            fake_resolve,
        )

        cfg = BotConfig(
            name="bot",
            llm_selection={"profile_id": "p-alt", "model_id": "m-alt"},
            model="legacy-model",
        )

        resolved = resolve_tutorbot_llm_config(cfg)

        assert resolved.model == "selected-model"
        assert captured == [{"profile_id": "p-alt", "model_id": "m-alt"}]

    def test_legacy_model_overrides_system_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeConfig:
            model = "system-model"

            def model_copy(self, update):
                return SimpleNamespace(model=update["model"])

        monkeypatch.setattr(
            "deeptutor.services.tutorbot.model_runtime.resolve_llm_config_for_selection",
            lambda selection: FakeConfig(),
        )

        resolved = resolve_tutorbot_llm_config(BotConfig(name="bot", model="legacy-model"))

        assert resolved.model == "legacy-model"


# ---------------------------------------------------------------------------
# auto_start persistence during lifecycle stops
# ---------------------------------------------------------------------------


class TestAutoStartPersistence:
    def _config_data(self, manager: TutorBotManager, bot_id: str) -> dict:
        return yaml.safe_load(
            (manager._bot_dir(bot_id) / "config.yaml").read_text(encoding="utf-8")
        )

    def _register_instance(
        self,
        manager: TutorBotManager,
        bot_id: str,
        cfg: BotConfig | None = None,
    ) -> BotConfig:
        cfg = cfg or BotConfig(name=bot_id)
        manager._bots[bot_id] = TutorBotInstance(bot_id=bot_id, config=cfg)
        return cfg

    def test_manual_stop_disables_future_auto_start(self, manager: TutorBotManager):
        cfg = BotConfig(name="manual")
        manager.save_bot_config("manual-bot", cfg, auto_start=True)
        self._register_instance(manager, "manual-bot", cfg)

        assert asyncio.run(manager.stop_bot("manual-bot")) is True

        assert self._config_data(manager, "manual-bot")["auto_start"] is False
        assert manager.get_bot("manual-bot") is None

    def test_shutdown_stop_all_preserves_auto_start_true(self, manager: TutorBotManager):
        cfg = BotConfig(name="restartable")
        manager.save_bot_config("restartable-bot", cfg, auto_start=True)
        self._register_instance(manager, "restartable-bot", cfg)

        asyncio.run(manager.stop_all())

        assert self._config_data(manager, "restartable-bot")["auto_start"] is True
        assert manager.get_bot("restartable-bot") is None

    def test_shutdown_stop_all_preserves_existing_auto_start_false(self, manager: TutorBotManager):
        cfg = BotConfig(name="manual-only")
        manager.save_bot_config("manual-only-bot", cfg, auto_start=False)
        self._register_instance(manager, "manual-only-bot", cfg)

        asyncio.run(manager.stop_all())

        assert self._config_data(manager, "manual-only-bot")["auto_start"] is False

    def test_auto_start_preserves_shell_exec_opt_in(
        self,
        manager: TutorBotManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = BotConfig(name="shell-auto", allow_shell_exec=True)
        manager.save_bot_config("shell-auto-bot", cfg, auto_start=True)
        started: list[tuple[str, BotConfig | None]] = []

        async def fake_start_bot(bot_id: str, config: BotConfig | None = None):
            started.append((bot_id, config))
            return TutorBotInstance(
                bot_id=bot_id,
                config=config or BotConfig(name=bot_id),
            )

        monkeypatch.setattr(manager, "start_bot", fake_start_bot)

        asyncio.run(manager.auto_start_bots())

        assert started == [("shell-auto-bot", cfg)]
        assert started[0][1].allow_shell_exec is True


def test_start_bot_passes_shared_memory_dir(
    manager: TutorBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Path | None] = {}

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            captured["shared_memory_dir"] = kwargs.get("shared_memory_dir")
            captured["model"] = kwargs.get("model")
            captured["context_window_tokens"] = kwargs.get("context_window_tokens")
            self.model = kwargs.get("model") or "fake-model"
            self.context_window_tokens = kwargs.get("context_window_tokens") or 65_536

        async def run(self) -> None:
            return None

        async def process_direct(self, *_args, **_kwargs) -> str:
            return "ok"

    class FakeHeartbeat:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def start(self) -> None:
            return None

    monkeypatch.setattr("deeptutor.tutorbot.agent.loop.AgentLoop", FakeAgentLoop)
    monkeypatch.setattr(
        "deeptutor.tutorbot.providers.deeptutor_adapter.create_deeptutor_provider",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "deeptutor.services.tutorbot.model_runtime.resolve_tutorbot_llm_config",
        lambda _cfg: SimpleNamespace(model="selected-model", context_window=123456),
    )
    monkeypatch.setattr(
        "deeptutor.services.tutorbot.manager.TutorBotManager._build_channel_manager",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "deeptutor.services.tutorbot.manager.TutorBotManager._outbound_router",
        lambda *_args, **_kwargs: _done(),
    )
    monkeypatch.setattr("deeptutor.tutorbot.heartbeat.HeartbeatService", FakeHeartbeat)

    async def run_start() -> None:
        instance = await manager.start_bot("shared-memory-bot", BotConfig(name="bot"))
        for task in instance.tasks:
            task.cancel()

    async def _done() -> None:
        return None

    asyncio.run(run_start())

    assert captured["shared_memory_dir"] == tmp_path / "memory"
    assert captured["model"] == "selected-model"
    assert captured["context_window_tokens"] == 123456


def test_reload_llm_updates_running_agent_loop(
    manager: TutorBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeAgentLoop:
        context_window_tokens = 65_536

        def update_llm(self, **kwargs) -> None:
            calls.append(kwargs)
            self.model = kwargs["model"]

    class FakeHeartbeat:
        provider = None
        model = None

    cfg = BotConfig(
        name="bot",
        llm_selection={"profile_id": "p-alt", "model_id": "m-alt"},
    )
    instance = TutorBotInstance(bot_id="reload-bot", config=cfg)
    instance.agent_loop = FakeAgentLoop()
    instance.heartbeat = FakeHeartbeat()

    selected_provider = object()
    monkeypatch.setattr(
        "deeptutor.services.tutorbot.model_runtime.resolve_tutorbot_llm_config",
        lambda _cfg: SimpleNamespace(model="alt-model", context_window=999),
    )
    monkeypatch.setattr(
        "deeptutor.tutorbot.providers.deeptutor_adapter.create_deeptutor_provider",
        lambda _cfg: selected_provider,
    )

    async def run_reload() -> None:
        task = asyncio.create_task(asyncio.sleep(3600))
        instance.tasks = [task]
        manager._bots["reload-bot"] = instance
        try:
            await manager.reload_llm("reload-bot")
        finally:
            task.cancel()

    asyncio.run(run_reload())

    assert calls == [
        {
            "provider": selected_provider,
            "model": "alt-model",
            "context_window_tokens": 999,
        }
    ]
    assert instance.heartbeat.provider is selected_provider
    assert instance.heartbeat.model == "alt-model"
