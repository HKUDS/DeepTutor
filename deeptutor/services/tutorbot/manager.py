"""
TutorBot Manager — spawn / stop / manage in-process TutorBot instances.

Each TutorBot instance runs as a set of asyncio tasks within the DeepTutor
server process.  Every bot gets its own isolated workspace under
``data/tutorbot/{bot_id}/`` containing workspace, cron, logs, and media.
Memory is shared across all bots via ``data/memory/``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
import json
import logging
from pathlib import Path
import shutil
import sys
from typing import Any

import yaml

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_PACKAGE_TUTORBOT = Path(__file__).resolve().parent.parent.parent / "tutorbot"
_BUILTIN_SKILLS_DIR = _PACKAGE_TUTORBOT / "skills"
_BUILTIN_TEMPLATES_DIR = _PACKAGE_TUTORBOT / "templates"

_RESERVED_NAMES = {"workspace", "media", "cron", "logs", "sessions", "_souls"}

# Substrings (case-insensitive) on channel field names that flag a value as a
# secret which must be masked before being serialised in non-edit responses.
# Matches existing channel configs: telegram.token, slack.bot_token /
# slack.app_token, discord.token, matrix.access_token, whatsapp.bridge_token,
# mochat.claw_token, feishu.app_secret / encrypt_key / verification_token,
# wecom.secret, qq.secret, dingtalk.client_secret, email.imap_password /
# smtp_password, etc.
_SECRET_FIELD_HINTS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "encrypt_key",
)
_SECRET_MASK = "***"


def _is_secret_field(name: str) -> bool:
    n = name.lower()
    return any(hint in n for hint in _SECRET_FIELD_HINTS)


def mask_channel_secrets(channels: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy ``channels`` and replace any secret-looking string field with ``***``.

    Lists/tuples are walked element-wise; non-string secret values are passed
    through unchanged so we don't accidentally hide non-credential booleans
    (e.g. a ``token_required`` flag, hypothetical).
    """

    def _walk(value: Any, key_hint: str | None = None) -> Any:
        if isinstance(value, dict):
            return {k: _walk(v, key_hint=k) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v, key_hint=key_hint) for v in value]
        if isinstance(value, tuple):
            return tuple(_walk(v, key_hint=key_hint) for v in value)
        if key_hint is not None and _is_secret_field(key_hint) and isinstance(value, str) and value:
            return _SECRET_MASK
        return value

    walked = _walk(channels)
    if not isinstance(walked, dict):  # defensive — should not happen
        return {}
    return walked


def normalize_message_content(content: Any) -> str:
    """Return a display-safe string for text or multimodal message content."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part for part in (normalize_message_content(item) for item in content) if part
        )
    if isinstance(content, dict):
        for key in ("text", "content", "message", "alt"):
            value = content.get(key)
            if isinstance(value, str) and value:
                return value
        if content.get("type") in {"image", "image_url"}:
            return "[image]"
        try:
            return json.dumps(content, ensure_ascii=False)
        except TypeError:
            return str(content)
    return str(content)


def _strict_config_bool(value: Any, *, default: bool = False) -> bool:
    """Parse security-sensitive config booleans without truthy string surprises."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        return default
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return default


def _history_sort_timestamp(message: dict[str, Any], fallback: float) -> float:
    """Return a numeric timestamp for stable cross-session history ordering."""
    raw = message.get("timestamp")
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


@dataclass
class BotConfig:
    """Configuration for a single TutorBot instance."""

    name: str
    description: str = ""
    persona: str = ""
    channels: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    llm_selection: dict[str, str] | None = None
    allow_shell_exec: bool = False


@dataclass
class TutorBotInstance:
    """A running TutorBot and its metadata."""

    bot_id: str
    config: BotConfig
    started_at: datetime = field(default_factory=datetime.now)
    tasks: list[asyncio.Task] = field(default_factory=list, repr=False)
    agent_loop: Any = None
    channel_manager: Any = None
    heartbeat: Any = None
    notify_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    channel_bindings: dict[str, str] = field(default_factory=dict)
    # Serialise concurrent reload_channels invocations on the same bot.
    reload_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # Last error from reload_channels (clears on success); surfaced via API
    # so the UI can warn that on-disk config and live listeners diverged.
    last_reload_error: str | None = None

    @property
    def running(self) -> bool:
        return any(not t.done() for t in self.tasks)

    def to_dict(
        self,
        *,
        include_secrets: bool = False,
        mask_secrets: bool = False,
    ) -> dict[str, Any]:
        """Serialise instance to a JSON-friendly dict.

        Channel field shape:
        - default (``include_secrets=False, mask_secrets=False``): list of channel
          names — safe for list / index endpoints.
        - ``mask_secrets=True``: full nested dict, but secret-looking strings
          replaced with ``***`` — safe for read-only detail views.
        - ``include_secrets=True``: full nested dict including raw secrets —
          ONLY use for the admin edit form (and only on the explicitly-opt-in
          single-bot GET).
        """
        if include_secrets:
            channels: Any = self.config.channels
        elif mask_secrets:
            channels = mask_channel_secrets(self.config.channels)
        else:
            channels = list(self.config.channels.keys())

        return {
            "bot_id": self.bot_id,
            "name": self.config.name,
            "description": self.config.description,
            "persona": self.config.persona,
            "channels": channels,
            "model": self.config.model,
            "llm_selection": self.config.llm_selection,
            "allow_shell_exec": self.config.allow_shell_exec,
            "running": self.running,
            "started_at": self.started_at.isoformat(),
            "last_reload_error": self.last_reload_error,
        }


class TutorBotManager:
    """Manage TutorBot instances running in-process."""

    def __init__(self) -> None:
        self._bots: dict[str, TutorBotInstance] = {}

    @property
    def _path_service(self):
        return get_path_service()

    # ── Path helpers ──────────────────────────────────────────────

    @property
    def _tutorbot_dir(self) -> Path:
        return self._path_service.workspace_root / "tutorbot"

    @property
    def _shared_memory_dir(self) -> Path:
        return self._path_service.get_memory_dir()

    def _bot_dir(self, bot_id: str) -> Path:
        return self._tutorbot_dir / bot_id

    def _bot_workspace(self, bot_id: str) -> Path:
        return self._bot_dir(bot_id) / "workspace"

    # ── Per-bot directory setup ───────────────────────────────────

    def _ensure_bot_dirs(self, bot_id: str) -> None:
        """Create the per-bot directory tree and seed skills/templates."""
        self._maybe_migrate_legacy(bot_id)

        for sub in ("workspace/skills", "workspace/memory", "cron", "logs", "media"):
            (self._bot_dir(bot_id) / sub).mkdir(parents=True, exist_ok=True)

        self._seed_skills(bot_id)
        self._seed_templates(bot_id)

    def _seed_skills(self, bot_id: str) -> None:
        """Copy built-in skill templates into the bot's workspace if absent."""
        if not _BUILTIN_SKILLS_DIR.exists():
            logger.warning("Builtin skills dir not found: %s", _BUILTIN_SKILLS_DIR)
            return
        dst = self._bot_workspace(bot_id) / "skills"
        dst.mkdir(parents=True, exist_ok=True)
        copied = 0
        for skill_dir in _BUILTIN_SKILLS_DIR.iterdir():
            if not skill_dir.is_dir():
                continue
            target = dst / skill_dir.name
            if not target.exists():
                try:
                    shutil.copytree(skill_dir, target)
                    copied += 1
                except Exception:
                    logger.exception(
                        "Failed to copy skill '%s' for bot '%s'", skill_dir.name, bot_id
                    )
        if copied:
            logger.info(
                "Seeded %d skills for bot '%s' from %s", copied, bot_id, _BUILTIN_SKILLS_DIR
            )

    def _seed_templates(self, bot_id: str) -> None:
        """Copy per-bot template files into the bot's workspace if absent."""
        if not _BUILTIN_TEMPLATES_DIR.exists():
            return
        ws = self._bot_workspace(bot_id)
        for tpl in ("SOUL.md", "TOOLS.md", "USER.md", "HEARTBEAT.md", "AGENTS.md"):
            src = _BUILTIN_TEMPLATES_DIR / tpl
            dst = ws / tpl
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

    # ── Legacy data migration ─────────────────────────────────────

    def _maybe_migrate_legacy(self, bot_id: str) -> None:
        """Migrate from the old bots/ sub-directory layout.

        Old layout:
          data/tutorbot/bots/{bot_id}/config.yaml
          data/tutorbot/bots/{bot_id}/workspace/
          data/tutorbot/bots/{bot_id}/memory/

        New layout:
          data/tutorbot/{bot_id}/config.yaml
          data/tutorbot/{bot_id}/workspace/
          data/memory/   (shared)
        """
        new_config = self._bot_dir(bot_id) / "config.yaml"
        if new_config.exists():
            return

        legacy_bots = self._tutorbot_dir / "bots"

        # Migrate from bots/{id}/ to {id}/
        legacy_bot_dir = legacy_bots / bot_id
        if legacy_bot_dir.is_dir() and (legacy_bot_dir / "config.yaml").exists():
            target = self._bot_dir(bot_id)
            target.mkdir(parents=True, exist_ok=True)
            for item in legacy_bot_dir.iterdir():
                if item.name == "memory":
                    continue
                dest = target / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))
            logger.info("Migrated bot '%s' from bots/ sub-directory", bot_id)

        # Migrate legacy bots/{id}.yaml
        legacy_yaml = legacy_bots / f"{bot_id}.yaml"
        if legacy_yaml.is_file() and not new_config.exists():
            self._bot_dir(bot_id).mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_yaml), str(new_config))
            logger.info("Migrated bot config %s.yaml", bot_id)

    # ── Config persistence ────────────────────────────────────────

    # Field names from BotConfig that are persisted via merge.
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
        """Read the on-disk ``config.yaml`` for a bot, or ``None`` if missing."""
        path = self._bot_dir(bot_id) / "config.yaml"
        if not path.exists():
            return None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return BotConfig(
                name=data.get("name", bot_id),
                description=data.get("description", ""),
                persona=data.get("persona", ""),
                channels=data.get("channels", {}),
                model=data.get("model"),
                llm_selection=data.get("llm_selection"),
                allow_shell_exec=_strict_config_bool(data.get("allow_shell_exec", False)),
            )
        except Exception:
            logger.exception("Failed to load bot config %s", bot_id)
            return None

    def save_bot_config(self, bot_id: str, config: BotConfig, *, auto_start: bool = True) -> None:
        """Persist ``config`` to ``config.yaml`` atomically (write-temp + replace).

        Atomic write ensures we never leave a half-written/corrupt yaml on disk
        if the process is killed mid-write.
        """
        bot_dir = self._bot_dir(bot_id)
        bot_dir.mkdir(parents=True, exist_ok=True)
        path = bot_dir / "config.yaml"
        data: dict[str, Any] = {
            "name": config.name,
            "description": config.description,
            "persona": config.persona,
            "channels": config.channels,
            "allow_shell_exec": config.allow_shell_exec,
            "auto_start": auto_start,
        }
        if config.model:
            data["model"] = config.model
        if config.llm_selection:
            data["llm_selection"] = config.llm_selection

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        tmp_path.replace(path)

    def _load_auto_start(self, bot_id: str, *, default: bool = False) -> bool:
        """Read the persisted auto-start intent without loading the full bot config."""
        path = self._bot_dir(bot_id) / "config.yaml"
        if not path.exists():
            return default
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return bool(data.get("auto_start", default))
        except Exception:
            logger.exception("Failed to load auto_start flag for bot '%s'", bot_id)
            return default

    def merge_bot_config(self, bot_id: str, overrides: dict[str, Any]) -> BotConfig:
        """Build a ``BotConfig`` by overlaying ``overrides`` onto the on-disk config.

        Keys in ``overrides`` whose value is ``None`` are treated as "not provided"
        and fall through to the existing on-disk value (or to the dataclass default
        for a brand-new bot). Empty strings / empty dicts are intentional clears
        and DO override — callers must use ``None`` to mean "leave as-is".

        Unknown keys are silently ignored.
        """
        existing = self.load_bot_config(bot_id)
        base = existing or BotConfig(name=bot_id)
        for key in self._MERGEABLE_FIELDS:
            if key in overrides and overrides[key] is not None:
                setattr(base, key, overrides[key])
        return base

    # ── Bot lifecycle ─────────────────────────────────────────────

    async def start_bot(self, bot_id: str, config: BotConfig | None = None) -> TutorBotInstance:
        """Start a TutorBot instance with its own isolated workspace."""
        if bot_id in self._bots and self._bots[bot_id].running:
            return self._bots[bot_id]

        self._ensure_bot_dirs(bot_id)

        if config is None:
            config = self.load_bot_config(bot_id)
        if config is None:
            config = BotConfig(name=bot_id)
            self.save_bot_config(bot_id, config)

        from deeptutor.services.tutorbot.model_runtime import (
            resolve_tutorbot_llm_config,
        )
        from deeptutor.tutorbot.agent.loop import AgentLoop
        from deeptutor.tutorbot.bus.queue import MessageBus
        from deeptutor.tutorbot.config.schema import ExecToolConfig
        from deeptutor.tutorbot.providers.deeptutor_adapter import create_deeptutor_provider
        from deeptutor.tutorbot.session.manager import SessionManager

        llm_config = resolve_tutorbot_llm_config(config)
        provider = create_deeptutor_provider(llm_config)
        bus = MessageBus()

        workspace = self._bot_workspace(bot_id)
        session_adapter = SessionManager(workspace)

        if config.persona:
            soul_path = workspace / "SOUL.md"
            soul_path.write_text(config.persona, encoding="utf-8")

        venv_bin = str(Path(sys.executable).parent)
        exec_config = ExecToolConfig(
            enabled=config.allow_shell_exec,
            timeout=300,
            path_append=venv_bin,
        )

        canonical_key = f"bot:{bot_id}"

        agent_loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=workspace,
            model=llm_config.model,
            context_window_tokens=llm_config.context_window or 65_536,
            exec_config=exec_config,
            session_manager=session_adapter,
            shared_memory_dir=self._shared_memory_dir,
            restrict_to_workspace=True,
            default_session_key=canonical_key,
        )

        # -- Channel setup ---------------------------------------------------
        try:
            channel_manager = self._build_channel_manager(config, bus, bot_id=bot_id)
        except Exception:
            logger.exception("Failed to initialise channels for bot '%s'", bot_id)
            channel_manager = None

        instance = TutorBotInstance(
            bot_id=bot_id,
            config=config,
            agent_loop=agent_loop,
            channel_manager=channel_manager,
        )

        # -- Core tasks -------------------------------------------------------
        loop_task = asyncio.create_task(
            agent_loop.run(),
            name=f"tutorbot:{bot_id}:loop",
        )
        router_task = asyncio.create_task(
            self._outbound_router(bot_id, bus, instance),
            name=f"tutorbot:{bot_id}:router",
        )
        instance.tasks.extend([loop_task, router_task])

        # -- Start channel listeners (without ChannelManager's own dispatcher)
        if channel_manager:
            for ch_name, ch in channel_manager.channels.items():
                ch_task = asyncio.create_task(
                    ch.start(),
                    name=f"tutorbot:{bot_id}:ch:{ch_name}",
                )
                instance.tasks.append(ch_task)

        # -- Heartbeat --------------------------------------------------------
        from deeptutor.tutorbot.heartbeat import HeartbeatService

        async def _hb_execute(tasks_summary: str) -> str:
            return await agent_loop.process_direct(
                tasks_summary,
                session_key=canonical_key,
                channel="web",
                chat_id="web",
            )

        async def _hb_notify(response: str) -> None:
            await instance.notify_queue.put(response)

        heartbeat = HeartbeatService(
            workspace=workspace,
            provider=provider,
            model=agent_loop.model,
            on_execute=_hb_execute,
            on_notify=_hb_notify,
            interval_s=30 * 60,
        )
        instance.heartbeat = heartbeat
        await heartbeat.start()

        self._bots[bot_id] = instance
        self.save_bot_config(bot_id, config)
        logger.info("TutorBot '%s' started (workspace=%s)", bot_id, workspace)
        return instance

    async def reload_llm(self, bot_id: str) -> None:
        """Apply the bot's current LLM config to an already-running instance."""
        instance = self._bots.get(bot_id)
        if not instance or not instance.running or not instance.agent_loop:
            return

        from deeptutor.services.tutorbot.model_runtime import (
            resolve_tutorbot_llm_config,
        )
        from deeptutor.tutorbot.providers.deeptutor_adapter import create_deeptutor_provider

        llm_config = resolve_tutorbot_llm_config(instance.config)
        provider = create_deeptutor_provider(llm_config)
        context_window_tokens = (
            llm_config.context_window or instance.agent_loop.context_window_tokens
        )
        instance.agent_loop.update_llm(
            provider=provider,
            model=llm_config.model,
            context_window_tokens=context_window_tokens,
        )
        if instance.heartbeat:
            instance.heartbeat.provider = provider
            instance.heartbeat.model = instance.agent_loop.model
        logger.info("Reloaded LLM for TutorBot '%s' (model=%s)", bot_id, llm_config.model)

    async def _outbound_router(self, bot_id: str, bus: Any, instance: TutorBotInstance) -> None:
        """Route outbound messages to channels, web notify_queue, and EventBus.

        This is the sole consumer of the outbound queue, replacing both the
        old ``_bridge_events`` and ``ChannelManager._dispatch_outbound`` to
        avoid queue contention.
        """
        try:
            from deeptutor.events.event_bus import Event, EventType, get_event_bus
            from deeptutor.tutorbot.bus.events import OutboundMessage as _OMsg

            event_bus = get_event_bus()
            while True:
                msg: _OMsg = await bus.consume_outbound()
                is_progress = bool(msg.metadata and msg.metadata.get("_progress"))

                # 1. Route to originating channel (if it exists)
                if instance.channel_manager:
                    channel = instance.channel_manager.get_channel(msg.channel)
                    if channel:
                        try:
                            await channel.send(msg)
                        except Exception:
                            logger.exception(
                                "Failed to send to channel %s for bot %s", msg.channel, bot_id
                            )
                        if not is_progress and msg.chat_id:
                            instance.channel_bindings[msg.channel] = msg.chat_id

                # 2. Notify web clients (non-progress only)
                if not is_progress:
                    await instance.notify_queue.put(msg.content or "")

                # 3. Publish to EventBus
                if not is_progress:
                    await event_bus.publish(
                        Event(
                            type=EventType.CAPABILITY_COMPLETE,
                            task_id=f"tutorbot:{bot_id}:{msg.channel}:{msg.chat_id}",
                            user_input="",
                            agent_output=msg.content or "",
                            metadata={
                                "source": "tutorbot",
                                "bot_id": bot_id,
                                "channel": msg.channel,
                                "chat_id": msg.chat_id,
                            },
                        )
                    )
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Outbound router failed for bot %s", bot_id)

    async def stop_bot(self, bot_id: str, *, preserve_auto_start: bool = False) -> bool:
        """Stop a running TutorBot instance.

        Manual stops should disable future auto-starts, but process shutdown
        must preserve the persisted auto-start intent so Docker/host restarts
        bring the same bots back online.
        """
        instance = self._bots.get(bot_id)
        if not instance:
            return False
        auto_start = self._load_auto_start(bot_id, default=True) if preserve_auto_start else False

        for task in instance.tasks:
            if not task.done():
                task.cancel()
        for task in instance.tasks:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        if instance.channel_manager:
            try:
                await instance.channel_manager.stop_all()
            except Exception:
                logger.exception("Error stopping channels for bot '%s'", bot_id)

        if instance.heartbeat:
            instance.heartbeat.stop()

        if instance.agent_loop:
            try:
                await instance.agent_loop.stop()
            except Exception:
                pass

        self.save_bot_config(bot_id, instance.config, auto_start=auto_start)
        del self._bots[bot_id]
        logger.info(
            "TutorBot '%s' stopped (auto_start=%s, preserve_auto_start=%s)",
            bot_id,
            auto_start,
            preserve_auto_start,
        )
        return True

    def _build_channel_manager(
        self,
        config: BotConfig,
        bus: Any,
        *,
        bot_id: str,
    ) -> Any | None:
        """Construct a ``ChannelManager`` from ``config.channels`` or return ``None``.

        Centralised so ``start_bot`` and ``reload_channels`` produce identical
        behaviour. Raises ``pydantic.ValidationError`` if the channels dict is
        malformed; callers decide whether to swallow or propagate.
        """
        if not config.channels:
            return None
        from deeptutor.tutorbot.channels.manager import ChannelManager
        from deeptutor.tutorbot.config.schema import ChannelsConfig

        channels_config = ChannelsConfig(**config.channels)
        manager = ChannelManager(channels_config, bus)
        if not manager.channels:
            logger.info("No channels matched config for bot '%s'", bot_id)
            return None
        logger.info(
            "Channels enabled for bot '%s': %s",
            bot_id,
            list(manager.channels.keys()),
        )
        return manager

    async def reload_channels(self, bot_id: str) -> None:
        """Restart channel listeners from ``instance.config.channels`` (same MessageBus).

        Cancels only ``tutorbot:{bot_id}:ch:*`` tasks; agent loop and outbound
        router keep running. Concurrent invocations on the same bot are
        serialised via ``instance.reload_lock`` to avoid duplicate listeners.

        On success, ``instance.last_reload_error`` is cleared. On failure, the
        listeners are torn down (bot is left running with no channels) and the
        error is recorded; callers should surface it to the user.
        """
        instance = self._bots.get(bot_id)
        if not instance or not instance.running:
            return

        async with instance.reload_lock:
            await self._teardown_channel_listeners(instance, bot_id)

            try:
                channel_manager = self._build_channel_manager(
                    instance.config,
                    instance.agent_loop.bus,
                    bot_id=bot_id,
                )
            except Exception as exc:
                logger.exception("Failed to reload channels for bot '%s'", bot_id)
                instance.channel_manager = None
                instance.last_reload_error = f"{type(exc).__name__}: {exc}"
                raise

            instance.channel_manager = channel_manager
            instance.last_reload_error = None
            if channel_manager:
                for ch_name, ch in channel_manager.channels.items():
                    ch_task = asyncio.create_task(
                        ch.start(),
                        name=f"tutorbot:{bot_id}:ch:{ch_name}",
                    )
                    instance.tasks.append(ch_task)
                logger.info(
                    "Reloaded channels for bot '%s': %s",
                    bot_id,
                    list(channel_manager.channels.keys()),
                )

    async def _teardown_channel_listeners(
        self,
        instance: TutorBotInstance,
        bot_id: str,
    ) -> None:
        """Cancel ``tutorbot:{bot_id}:ch:*`` tasks and stop the existing manager.

        Note: ``channel_bindings`` are intentionally cleared — they map
        channel→last-seen chat_id and will be rebuilt as the rebooted listeners
        receive new traffic. Pending heartbeat replies bound to a stale chat_id
        will be dropped (acceptable: same behaviour as Stop/Start).
        """
        ch_prefix = f"tutorbot:{bot_id}:ch:"
        to_remove = [t for t in instance.tasks if (t.get_name() or "").startswith(ch_prefix)]
        for t in to_remove:
            if not t.done():
                t.cancel()
        for t in to_remove:
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        instance.tasks = [t for t in instance.tasks if t not in to_remove]

        if instance.channel_manager:
            try:
                await instance.channel_manager.stop_all()
            except Exception:
                logger.exception("Error stopping channels before reload for bot '%s'", bot_id)

        instance.channel_manager = None
        instance.channel_bindings.clear()

    # ── Listing & discovery ───────────────────────────────────────

    def _discover_bot_ids(self) -> set[str]:
        """Return all bot IDs found on disk."""
        ids: set[str] = set()
        if not self._tutorbot_dir.exists():
            return ids

        for entry in self._tutorbot_dir.iterdir():
            if entry.name in _RESERVED_NAMES:
                continue
            if entry.is_dir() and (entry / "config.yaml").exists():
                ids.add(entry.name)
        return ids

    def list_bots(self) -> list[dict[str, Any]]:
        """List all known bots (running + configured on disk).

        Channel field is keys-only — never expose secrets via the list endpoint.
        """
        result: dict[str, dict[str, Any]] = {}

        for inst in self._bots.values():
            result[inst.bot_id] = inst.to_dict()

        for bid in self._discover_bot_ids():
            if bid in result:
                continue
            self._maybe_migrate_legacy(bid)
            cfg = self.load_bot_config(bid)
            result[bid] = {
                "bot_id": bid,
                "name": cfg.name if cfg else bid,
                "description": cfg.description if cfg else "",
                "persona": cfg.persona if cfg else "",
                "channels": list(cfg.channels.keys()) if cfg else [],
                "model": cfg.model if cfg else None,
                "llm_selection": cfg.llm_selection if cfg else None,
                "running": False,
                "started_at": None,
            }

        return list(result.values())

    def get_bot(self, bot_id: str) -> TutorBotInstance | None:
        return self._bots.get(bot_id)

    def get_bot_history(self, bot_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Read chat messages from a bot's JSONL session files."""
        sessions_dir = self._bot_workspace(bot_id) / "sessions"
        if not sessions_dir.exists():
            return []

        indexed_messages: list[tuple[float, int, dict[str, Any]]] = []
        sequence = 0
        for path in sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
            file_mtime = path.stat().st_mtime
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("_type") == "metadata":
                            continue
                        if data.get("role") in ("user", "assistant") and data.get("content"):
                            data["content"] = normalize_message_content(data["content"])
                            data.pop("reasoning_content", None)
                            indexed_messages.append(
                                (
                                    _history_sort_timestamp(data, file_mtime),
                                    sequence,
                                    data,
                                )
                            )
                            sequence += 1
            except Exception:
                continue

        indexed_messages.sort(key=lambda item: (item[0], item[1]))
        messages = [item[2] for item in indexed_messages]
        return messages[-limit:]

    @staticmethod
    def web_session_key(bot_id: str, *, chat_id: str = "web", session_id: str | None = None) -> str:
        """Return the TutorBot session key used for web/API conversations."""
        normalized_session = str(session_id or "").strip()
        if normalized_session:
            return f"web:{normalized_session}"
        normalized_chat = str(chat_id or "web").strip() or "web"
        if normalized_chat != "web":
            return f"web:{normalized_chat}"
        return f"bot:{bot_id}"

    def get_recent_active_bots(self, limit: int = 3) -> list[dict[str, Any]]:
        """Return the most recently active bots with their last message preview."""
        bot_activity: list[tuple[float, str, dict[str, Any]]] = []

        for bid in self._discover_bot_ids():
            sessions_dir = self._bot_workspace(bid) / "sessions"
            if not sessions_dir.is_dir():
                continue

            jsonl_files = list(sessions_dir.glob("*.jsonl"))
            if not jsonl_files:
                continue

            newest = max(jsonl_files, key=lambda p: p.stat().st_mtime)
            mtime = newest.stat().st_mtime

            last_msg = ""
            try:
                with open(newest, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("_type") == "metadata":
                            continue
                        if data.get("role") in ("user", "assistant") and data.get("content"):
                            last_msg = normalize_message_content(data["content"])
            except Exception:
                pass

            cfg = self.load_bot_config(bid)
            instance = self._bots.get(bid)
            bot_activity.append(
                (
                    mtime,
                    bid,
                    {
                        "bot_id": bid,
                        "name": cfg.name if cfg else bid,
                        "running": instance.running if instance else False,
                        "last_message": last_msg[:200] if last_msg else "",
                        "updated_at": datetime.fromtimestamp(mtime).isoformat(),
                    },
                )
            )

        bot_activity.sort(key=lambda x: x[0], reverse=True)
        return [item[2] for item in bot_activity[:limit]]

    async def send_message(
        self,
        bot_id: str,
        content: str,
        chat_id: str = "web",
        session_id: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Send a message to a running bot and return the response."""
        instance = self._bots.get(bot_id)
        if not instance or not instance.running:
            raise RuntimeError(f"Bot '{bot_id}' is not running")

        session_key = self.web_session_key(bot_id, chat_id=chat_id, session_id=session_id)

        async def _progress(text: str, *, tool_hint: bool = False) -> None:
            if on_progress:
                await on_progress(text)

        response = await instance.agent_loop.process_direct(
            content,
            session_key=session_key,
            channel="web",
            chat_id=session_id or chat_id,
            on_progress=_progress,
        )

        # Forward the reply to any bound external channels so mobile users
        # see the web-originated conversation in their chat app.
        if instance.channel_manager and response:
            from deeptutor.tutorbot.bus.events import OutboundMessage

            for ch_name, ch_chat_id in instance.channel_bindings.items():
                ch = instance.channel_manager.get_channel(ch_name)
                if ch:
                    try:
                        await ch.send(
                            OutboundMessage(
                                channel=ch_name,
                                chat_id=ch_chat_id,
                                content=response,
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Failed to forward web reply to channel %s for bot %s",
                            ch_name,
                            bot_id,
                        )

        return response

    async def auto_start_bots(self) -> None:
        """Scan persisted configs and start bots marked with auto_start: true.

        在多用户模式下（auth.enabled=true），也会遍历所有普通用户，在其各自的
        workspace 下启动 auto_start: true 的 Bot。
        """
        await self._auto_start_bots_for_workspace()
        await self._for_each_user_manager(
            TutorBotManager._auto_start_bots_for_workspace,
            "auto-start bots",
        )

    async def _auto_start_bots_for_workspace(self) -> None:
        """扫描当前 workspace 下的 config.yaml，启动 auto_start: true 的 Bot。"""
        for bid in self._discover_bot_ids():
            if bid in self._bots and self._bots[bid].running:
                continue
            try:
                self._maybe_migrate_legacy(bid)
                path = self._bot_dir(bid) / "config.yaml"
                if not path.exists():
                    continue
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not data.get("auto_start", False):
                    continue
                config = BotConfig(
                    name=data.get("name", bid),
                    description=data.get("description", ""),
                    persona=data.get("persona", ""),
                    channels=data.get("channels", {}),
                    model=data.get("model"),
                    llm_selection=data.get("llm_selection"),
                )
                await self.start_bot(bid, config)
                logger.info("Auto-started bot '%s'", bid)
            except Exception:
                logger.exception("Failed to auto-start bot '%s'", bid)

    async def destroy_bot(self, bot_id: str) -> bool:
        """Stop a bot (if running) and permanently delete its data from disk."""
        await self.stop_bot(bot_id, preserve_auto_start=False)
        bot_dir = self._bot_dir(bot_id)
        if not bot_dir.exists():
            return False
        shutil.rmtree(bot_dir)
        logger.info("TutorBot '%s' destroyed (data deleted)", bot_id)
        return True

    # ── Workspace file helpers ────────────────────────────────────

    _EDITABLE_FILES = {"SOUL.md", "USER.md", "TOOLS.md", "AGENTS.md", "HEARTBEAT.md"}

    def read_bot_file(self, bot_id: str, filename: str) -> str | None:
        if filename not in self._EDITABLE_FILES:
            return None
        path = self._bot_workspace(bot_id) / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_bot_file(self, bot_id: str, filename: str, content: str) -> bool:
        if filename not in self._EDITABLE_FILES:
            return False
        path = self._bot_workspace(bot_id) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True

    def read_all_bot_files(self, bot_id: str) -> dict[str, str]:
        result: dict[str, str] = {}
        ws = self._bot_workspace(bot_id)
        for fn in self._EDITABLE_FILES:
            path = ws / fn
            result[fn] = path.read_text(encoding="utf-8") if path.exists() else ""
        return result

    async def stop_all(self, *, preserve_auto_start: bool = True) -> None:
        """Stop all running bots while preserving restart intent by default.

        在多用户模式下（auth.enabled=true），也会遍历所有普通用户并停止其 Bot。
        """
        await self._stop_all_in_workspace(preserve_auto_start=preserve_auto_start)
        await self._for_each_user_manager(
            partial(
                TutorBotManager._stop_all_in_workspace,
                preserve_auto_start=preserve_auto_start,
            ),
            "stop bots",
        )

    async def _stop_all_in_workspace(
        self, *, preserve_auto_start: bool = True
    ) -> None:
        """停止当前 workspace 下所有正在运行的 Bot。"""
        for bot_id in list(self._bots.keys()):
            await self.stop_bot(bot_id, preserve_auto_start=preserve_auto_start)

    async def _for_each_user_manager(
        self,
        action: Callable[["TutorBotManager"], Awaitable[None]],
        action_name: str,
    ) -> None:
        """多用户模式下遍历所有普通用户，为每个用户执行指定操作。

        在单用户模式（auth.enabled=false）下直接返回，不做任何操作。
        """
        try:
            from deeptutor.services.auth import AUTH_ENABLED
        except ImportError:
            logger.warning(
                "Cannot import AUTH_ENABLED; skipping multi-user %s", action_name
            )
            return

        if not AUTH_ENABLED:
            return

        try:
            from deeptutor.multi_user.identity import list_user_info
            from deeptutor.multi_user.models import CurrentUser
            from deeptutor.multi_user.paths import scope_for_user, user_context
        except ImportError:
            logger.warning(
                "Cannot import multi_user modules; skipping multi-user %s", action_name
            )
            return

        for user_info in list_user_info():
            if user_info.get("role") == "admin" or user_info.get("disabled"):
                continue
            user = CurrentUser(
                id=user_info["id"],
                username=user_info["username"],
                role="user",
                scope=scope_for_user(user_info["id"], is_admin=False),
            )
            with user_context(user):
                mgr = get_tutorbot_manager()
                try:
                    await action(mgr)
                except Exception:
                    logger.exception(
                        "Failed to %s for user '%s'", action_name, user_info["username"]
                    )

    # ── Soul template library ─────────────────────────────────────

    @property
    def _souls_file(self) -> Path:
        return self._tutorbot_dir / "_souls.yaml"

    def _load_souls(self) -> list[dict[str, str]]:
        path = self._souls_file
        if not path.exists():
            self._seed_default_souls()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_souls(self, souls: list[dict[str, str]]) -> None:
        self._tutorbot_dir.mkdir(parents=True, exist_ok=True)
        self._souls_file.write_text(
            yaml.dump(souls, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

    def _seed_default_souls(self) -> None:
        defaults = [
            {
                "id": "default-tutorbot",
                "name": "Default TutorBot",
                "content": (
                    "# Soul\n\nI am TutorBot, a personal learning companion.\n\n"
                    "## Personality\n\n- Helpful and friendly\n- Clear, encouraging, and patient\n"
                    "- Adapts explanations to the user's level\n\n"
                    "## Values\n\n- Accuracy over speed\n- User privacy and safety\n- Transparency in actions"
                ),
            },
            {
                "id": "math-tutor",
                "name": "Math Tutor",
                "content": (
                    "# Soul\n\nI am a math tutor specializing in clear, step-by-step problem solving.\n\n"
                    "## Personality\n\n- Patient and methodical\n- Encourages showing work\n"
                    "- Celebrates progress on hard problems\n\n"
                    "## Teaching Style\n\n- Break complex problems into small steps\n"
                    "- Use visual representations when possible\n- Always verify final answers"
                ),
            },
            {
                "id": "coding-assistant",
                "name": "Coding Assistant",
                "content": (
                    "# Soul\n\nI am a coding assistant focused on helping developers write better software.\n\n"
                    "## Personality\n\n- Precise and detail-oriented\n"
                    "- Pragmatic — working code over perfect code\n- Explains trade-offs clearly\n\n"
                    "## Approach\n\n- Read before writing; understand context first\n"
                    "- Suggest tests alongside implementations\n- Prefer standard patterns over clever tricks"
                ),
            },
            {
                "id": "research-helper",
                "name": "Research Helper",
                "content": (
                    "# Soul\n\nI am a research assistant helping users explore academic topics in depth.\n\n"
                    "## Personality\n\n- Curious and thorough\n"
                    "- Balanced — presents multiple perspectives\n- Cites sources when possible\n\n"
                    "## Approach\n\n- Decompose broad questions into focused sub-questions\n"
                    "- Distinguish established facts from open questions\n- Suggest further reading"
                ),
            },
            {
                "id": "language-tutor",
                "name": "Language Tutor",
                "content": (
                    "# Soul\n\nI am a language learning companion helping users practice and improve.\n\n"
                    "## Personality\n\n- Encouraging and patient\n"
                    "- Adapts difficulty to learner level\n- Makes learning fun with examples\n\n"
                    "## Teaching Style\n\n- Correct mistakes gently with explanations\n"
                    "- Use contextual examples over abstract rules\n- Encourage speaking/writing practice"
                ),
            },
        ]
        self._save_souls(defaults)

    def list_souls(self) -> list[dict[str, str]]:
        return self._load_souls()

    def get_soul(self, soul_id: str) -> dict[str, str] | None:
        for s in self._load_souls():
            if s.get("id") == soul_id:
                return s
        return None

    def create_soul(self, soul_id: str, name: str, content: str) -> dict[str, str]:
        souls = self._load_souls()
        entry = {"id": soul_id, "name": name, "content": content}
        souls.append(entry)
        self._save_souls(souls)
        return entry

    def update_soul(
        self, soul_id: str, name: str | None, content: str | None
    ) -> dict[str, str] | None:
        souls = self._load_souls()
        for s in souls:
            if s.get("id") == soul_id:
                if name is not None:
                    s["name"] = name
                if content is not None:
                    s["content"] = content
                self._save_souls(souls)
                return s
        return None

    def delete_soul(self, soul_id: str) -> bool:
        souls = self._load_souls()
        new = [s for s in souls if s.get("id") != soul_id]
        if len(new) == len(souls):
            return False
        self._save_souls(new)
        return True


_managers: dict[str, TutorBotManager] = {}


def get_tutorbot_manager() -> TutorBotManager:
    key = str(get_path_service().workspace_root.resolve())
    if key not in _managers:
        _managers[key] = TutorBotManager()
    return _managers[key]
