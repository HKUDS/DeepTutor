"""
TutorBot Manager — spawn / stop / manage in-process TutorBot instances.

Each TutorBot instance runs as a set of asyncio tasks within the DeepTutor
server process.  Every bot gets its own isolated workspace under
``data/tutorbot/{bot_id}/`` containing workspace, cron, logs, and media.
Memory is shared across all bots via ``data/memory/``.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_PACKAGE_TUTORBOT = Path(__file__).resolve().parent.parent.parent / "tutorbot"
_BUILTIN_SKILLS_DIR = _PACKAGE_TUTORBOT / "skills"
_BUILTIN_TEMPLATES_DIR = _PACKAGE_TUTORBOT / "templates"

_RESERVED_NAMES = {"workspace", "media", "cron", "logs", "sessions", "_souls"}


@dataclass
class BotConfig:
    """Configuration for a single TutorBot instance."""

    name: str
    description: str = ""
    persona: str = ""
    channels: dict[str, Any] = field(default_factory=dict)
    model: str | None = None


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

    @property
    def running(self) -> bool:
        return any(not t.done() for t in self.tasks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "name": self.config.name,
            "description": self.config.description,
            "persona": self.config.persona,
            "channels": self.config.channels,
            "model": self.config.model,
            "running": self.running,
            "started_at": self.started_at.isoformat(),
        }


class TutorBotManager:
    """Manage TutorBot instances running in-process."""

    def __init__(self) -> None:
        self._bots: dict[str, TutorBotInstance] = {}
        self._path_service = get_path_service()

    # ── Path helpers ──────────────────────────────────────────────

    @property
    def _tutorbot_dir(self) -> Path:
        return self._path_service.project_root / "data" / "tutorbot"

    @property
    def _shared_memory_dir(self) -> Path:
        """Public memory shared by DeepTutor and all bots."""
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
                    logger.exception("Failed to copy skill '%s' for bot '%s'", skill_dir.name, bot_id)
        if copied:
            logger.info("Seeded %d skills for bot '%s' from %s", copied, bot_id, _BUILTIN_SKILLS_DIR)

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
    _MERGEABLE_FIELDS = ("name", "description", "persona", "channels", "model")

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
            "auto_start": auto_start,
        }
        if config.model:
            data["model"] = config.model

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        tmp_path.replace(path)

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

        from deeptutor.tutorbot.providers.deeptutor_adapter import create_deeptutor_provider
        from deeptutor.tutorbot.bus.queue import MessageBus
        from deeptutor.tutorbot.agent.loop import AgentLoop
        from deeptutor.tutorbot.config.schema import ExecToolConfig
        from deeptutor.tutorbot.session.manager import SessionManager

        provider = create_deeptutor_provider()
        bus = MessageBus()

        workspace = self._bot_workspace(bot_id)
        session_adapter = SessionManager(workspace)

        if config.persona:
            soul_path = workspace / "SOUL.md"
            soul_path.write_text(config.persona, encoding="utf-8")

        venv_bin = str(Path(sys.executable).parent)
        exec_config = ExecToolConfig(timeout=300, path_append=venv_bin)

        canonical_key = f"bot:{bot_id}"

        agent_loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=workspace,
            model=config.model,
            exec_config=exec_config,
            session_manager=session_adapter,
            shared_memory_dir=None,
            restrict_to_workspace=False,
            default_session_key=canonical_key,
        )

        # -- Channel setup ---------------------------------------------------
        channel_manager = None
        if config.channels:
            try:
                from deeptutor.tutorbot.channels.manager import ChannelManager
                from deeptutor.tutorbot.config.schema import ChannelsConfig

                channels_config = ChannelsConfig(**config.channels)
                channel_manager = ChannelManager(channels_config, bus)
                if channel_manager.channels:
                    logger.info(
                        "Channels enabled for bot '%s': %s",
                        bot_id, list(channel_manager.channels.keys()),
                    )
                else:
                    logger.info("No channels matched config for bot '%s'", bot_id)
                    channel_manager = None
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
            agent_loop.run(), name=f"tutorbot:{bot_id}:loop",
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
                    ch.start(), name=f"tutorbot:{bot_id}:ch:{ch_name}",
                )
                instance.tasks.append(ch_task)

        # -- Heartbeat --------------------------------------------------------
        from deeptutor.tutorbot.heartbeat import HeartbeatService

        async def _hb_execute(tasks_summary: str) -> str:
            return await agent_loop.process_direct(
                tasks_summary, session_key=canonical_key,
                channel="web", chat_id="web",
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
                            logger.exception("Failed to send to channel %s for bot %s", msg.channel, bot_id)
                        if not is_progress and msg.chat_id:
                            instance.channel_bindings[msg.channel] = msg.chat_id

                # 2. Notify web clients (non-progress only)
                if not is_progress:
                    await instance.notify_queue.put(msg.content or "")

                # 3. Publish to EventBus
                if not is_progress:
                    await event_bus.publish(Event(
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
                    ))
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Outbound router failed for bot %s", bot_id)

    async def stop_bot(self, bot_id: str) -> bool:
        """Stop a running TutorBot instance."""
        instance = self._bots.get(bot_id)
        if not instance:
            return False

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

        self.save_bot_config(bot_id, instance.config, auto_start=False)
        del self._bots[bot_id]
        logger.info("TutorBot '%s' stopped", bot_id)
        return True

    async def reload_channels(self, bot_id: str) -> None:
        """Restart channel listeners from ``instance.config.channels`` (same MessageBus).

        Cancels only ``tutorbot:{bot_id}:ch:*`` tasks; agent loop and outbound router keep running.
        """
        instance = self._bots.get(bot_id)
        if not instance or not instance.running:
            return

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

        bus = instance.agent_loop.bus
        config = instance.config
        channel_manager = None
        if config.channels:
            try:
                from deeptutor.tutorbot.channels.manager import ChannelManager
                from deeptutor.tutorbot.config.schema import ChannelsConfig

                channels_config = ChannelsConfig(**config.channels)
                channel_manager = ChannelManager(channels_config, bus)
                if not channel_manager.channels:
                    channel_manager = None
            except Exception:
                logger.exception("Failed to reload channels for bot '%s'", bot_id)
                raise

        instance.channel_manager = channel_manager
        if channel_manager:
            for ch_name, ch in channel_manager.channels.items():
                ch_task = asyncio.create_task(
                    ch.start(), name=f"tutorbot:{bot_id}:ch:{ch_name}",
                )
                instance.tasks.append(ch_task)
            logger.info(
                "Reloaded channels for bot '%s': %s",
                bot_id, list(channel_manager.channels.keys()),
            )

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
        """List all known bots (running + configured on disk)."""
        result: dict[str, dict[str, Any]] = {}

        for inst in self._bots.values():
            row = inst.to_dict()
            row["channels"] = list(inst.config.channels.keys())
            result[inst.bot_id] = row

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
                "running": False,
                "started_at": None,
            }

        return list(result.values())

    def get_bot(self, bot_id: str) -> TutorBotInstance | None:
        return self._bots.get(bot_id)

    def get_bot_history(self, bot_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Read chat messages from a bot's JSONL session files."""
        import json as _json

        sessions_dir = self._bot_workspace(bot_id) / "sessions"
        if not sessions_dir.exists():
            return []

        all_messages: list[dict[str, Any]] = []
        for path in sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = _json.loads(line)
                        if data.get("_type") == "metadata":
                            continue
                        if data.get("role") in ("user", "assistant") and data.get("content"):
                            all_messages.append(data)
            except Exception:
                continue
            if len(all_messages) >= limit:
                break

        return all_messages[-limit:]

    def get_recent_active_bots(self, limit: int = 3) -> list[dict[str, Any]]:
        """Return the most recently active bots with their last message preview."""
        import json as _json

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
                        data = _json.loads(line)
                        if data.get("_type") == "metadata":
                            continue
                        if data.get("role") in ("user", "assistant") and data.get("content"):
                            last_msg = data["content"]
            except Exception:
                pass

            cfg = self.load_bot_config(bid)
            instance = self._bots.get(bid)
            bot_activity.append((mtime, bid, {
                "bot_id": bid,
                "name": cfg.name if cfg else bid,
                "running": instance.running if instance else False,
                "last_message": last_msg[:200] if last_msg else "",
                "updated_at": datetime.fromtimestamp(mtime).isoformat(),
            }))

        bot_activity.sort(key=lambda x: x[0], reverse=True)
        return [item[2] for item in bot_activity[:limit]]

    async def send_message(
        self,
        bot_id: str,
        content: str,
        chat_id: str = "web",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Send a message to a running bot and return the response."""
        instance = self._bots.get(bot_id)
        if not instance or not instance.running:
            raise RuntimeError(f"Bot '{bot_id}' is not running")

        canonical_key = f"bot:{bot_id}"

        async def _progress(text: str, *, tool_hint: bool = False) -> None:
            if on_progress:
                await on_progress(text)

        response = await instance.agent_loop.process_direct(
            content,
            session_key=canonical_key,
            channel="web",
            chat_id=chat_id,
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
                        await ch.send(OutboundMessage(
                            channel=ch_name, chat_id=ch_chat_id, content=response,
                        ))
                    except Exception:
                        logger.exception(
                            "Failed to forward web reply to channel %s for bot %s",
                            ch_name, bot_id,
                        )

        return response

    async def auto_start_bots(self) -> None:
        """Scan persisted configs and start bots marked with auto_start: true."""
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
                )
                await self.start_bot(bid, config)
                logger.info("Auto-started bot '%s'", bid)
            except Exception:
                logger.exception("Failed to auto-start bot '%s'", bid)

    async def destroy_bot(self, bot_id: str) -> bool:
        """Stop a bot (if running) and permanently delete its data from disk."""
        await self.stop_bot(bot_id)
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

    async def stop_all(self) -> None:
        """Stop all running bots."""
        for bot_id in list(self._bots.keys()):
            await self.stop_bot(bot_id)

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
            {"id": "default-tutorbot", "name": "Default TutorBot", "content": (
                "# Soul\n\nI am TutorBot, a personal learning companion.\n\n"
                "## Personality\n\n- Helpful and friendly\n- Clear, encouraging, and patient\n"
                "- Adapts explanations to the user's level\n\n"
                "## Values\n\n- Accuracy over speed\n- User privacy and safety\n- Transparency in actions"
            )},
            {"id": "math-tutor", "name": "Math Tutor", "content": (
                "# Soul\n\nI am a math tutor specializing in clear, step-by-step problem solving.\n\n"
                "## Personality\n\n- Patient and methodical\n- Encourages showing work\n"
                "- Celebrates progress on hard problems\n\n"
                "## Teaching Style\n\n- Break complex problems into small steps\n"
                "- Use visual representations when possible\n- Always verify final answers"
            )},
            {"id": "coding-assistant", "name": "Coding Assistant", "content": (
                "# Soul\n\nI am a coding assistant focused on helping developers write better software.\n\n"
                "## Personality\n\n- Precise and detail-oriented\n"
                "- Pragmatic — working code over perfect code\n- Explains trade-offs clearly\n\n"
                "## Approach\n\n- Read before writing; understand context first\n"
                "- Suggest tests alongside implementations\n- Prefer standard patterns over clever tricks"
            )},
            {"id": "research-helper", "name": "Research Helper", "content": (
                "# Soul\n\nI am a research assistant helping users explore academic topics in depth.\n\n"
                "## Personality\n\n- Curious and thorough\n"
                "- Balanced — presents multiple perspectives\n- Cites sources when possible\n\n"
                "## Approach\n\n- Decompose broad questions into focused sub-questions\n"
                "- Distinguish established facts from open questions\n- Suggest further reading"
            )},
            {"id": "language-tutor", "name": "Language Tutor", "content": (
                "# Soul\n\nI am a language learning companion helping users practice and improve.\n\n"
                "## Personality\n\n- Encouraging and patient\n"
                "- Adapts difficulty to learner level\n- Makes learning fun with examples\n\n"
                "## Teaching Style\n\n- Correct mistakes gently with explanations\n"
                "- Use contextual examples over abstract rules\n- Encourage speaking/writing practice"
            )},
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

    def update_soul(self, soul_id: str, name: str | None, content: str | None) -> dict[str, str] | None:
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


_manager: TutorBotManager | None = None


def get_tutorbot_manager() -> TutorBotManager:
    global _manager
    if _manager is None:
        _manager = TutorBotManager()
    return _manager
