"""Partner Manager — create / start / stop / manage in-process partners.

Each partner runs as a set of asyncio tasks within the DeepTutor server
process: a ``PartnerRunner`` (chat-agent-loop driver), an outbound message
router, and one listener task per enabled IM channel. Every partner owns an
isolated chat-format workspace under ``data/partners/{partner_id}/``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import logging
from pathlib import Path
import re
import shutil
from typing import Any, Awaitable, Callable

import yaml

from deeptutor.partners.config.paths import (
    get_data_dir,
    get_partner_dir,
    get_partner_sessions_dir,
)
from deeptutor.services.partners.runtime import PartnerRunner
from deeptutor.services.partners.sessions import PartnerSessionStore
from deeptutor.services.partners.workspace import (
    DEFAULT_SOUL,
    ensure_partner_workspace,
    read_soul,
    write_soul,
)

logger = logging.getLogger(__name__)

_RESERVED_NAMES = {"workspace", "media", "sessions", "_souls"}
_HYPHEN_RUN_RE = re.compile(r"-+")
LEGACY_GLOBAL_DELIVERY_KEYS = frozenset(
    {"send_progress", "send_tool_hints", "sendProgress", "sendToolHints"}
)

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
    """Deep-copy ``channels`` and replace any secret-looking string field with ``***``."""

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


def strip_legacy_global_delivery(channels: dict[str, Any]) -> dict[str, Any]:
    """Remove deprecated top-level delivery switches from channel config."""
    if not isinstance(channels, dict):
        return {}
    return {k: v for k, v in channels.items() if k not in LEGACY_GLOBAL_DELIVERY_KEYS}


def _slugify_id(name: str, *, fallback: str) -> str:
    # Ids ride in URLs (``/partners/<id>``, ``/souls/<id>``) and can become
    # on-disk names, so they must be ASCII/URL-safe: a non-Latin id (e.g.
    # ``中文``) yields a link the browser can't cleanly display or share, which
    # left CJK-named entities unreachable. Keep ASCII letters/digits
    # (lower-cased) and collapse every other run to a single hyphen —
    # ``isascii`` drops CJK/other scripts and ``isalnum`` excludes underscore,
    # so a partner id can't collide with the reserved ``_souls`` directory. When
    # no ASCII survives (a pure-CJK name), fall back to a stable per-name handle
    # so distinct non-Latin names still get distinct ids while the same name
    # round-trips to the same id (keeping the create-time duplicate check
    # meaningful). Only the id is slugged; the entity keeps its display name.
    stripped = name.strip()
    cleaned = "".join(c if c.isascii() and c.isalnum() else "-" for c in stripped.lower())
    slug = _HYPHEN_RUN_RE.sub("-", cleaned).strip("-")
    if slug:
        return slug
    if not stripped:
        return fallback
    # SHA1 here is a content-addressing handle (stable per-name id), not
    # security; ``usedforsecurity=False`` documents that and clears bandit B324.
    digest = hashlib.sha1(stripped.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"{fallback}-{digest}"


def slugify_partner_id(name: str) -> str:
    """ASCII/URL-safe partner id derived from a display name (see
    :func:`_slugify_id`); pure-CJK names get a stable ``partner-<hash>`` id."""
    return _slugify_id(name, fallback="partner")


def slugify_soul_id(name: str) -> str:
    """ASCII/URL-safe soul-library id. Soul ids ride in ``/souls/<id>`` URLs
    exactly like partner ids, so they get the same treatment (see
    :func:`_slugify_id`); pure-CJK names get a stable ``soul-<hash>`` id."""
    return _slugify_id(name, fallback="soul")


def _optional_str_list(value: Any) -> list[str] | None:
    """YAML field → ``None`` (absent / wrong type) or a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    return None


@dataclass
class PartnerConfig:
    """Configuration for a single partner."""

    name: str
    description: str = ""
    channels: dict[str, Any] = field(default_factory=dict)
    llm_selection: dict[str, str] | None = None
    # Fallback model: when a turn fails outright on the primary selection
    # (LLM error, no output), the runner re-runs the turn once with this.
    backup_llm_selection: dict[str, str] | None = None
    model: str | None = None  # legacy TutorBot model-string override
    language: str = ""
    emoji: str = ""
    color: str = ""
    # Custom avatar as a compact data URL (image/svg, client-resized) —
    # kept inline in config so <img> rendering needs no authenticated
    # file endpoint. Takes precedence over emoji/color when set.
    avatar: str = ""
    soul_origin: dict[str, str] = field(default_factory=dict)  # {"type","id"} provenance
    # User-toggleable system tools (same pool as the chat composer /
    # /settings/tools). None = all of them; [] = none; list = whitelist.
    enabled_tools: list[str] | None = None
    # Allowed built-in (auto-mounted) tools — rag / read_memory / web_fetch /
    # … (CONFIGURABLE_BUILTIN_TOOL_NAMES). None = no gating (all mount under
    # their usual context condition, like the product chat); [] = deny every
    # built-in; list = whitelist. Lets an owner deny e.g. memory to an
    # IM-facing partner.
    builtin_tools: list[str] | None = None
    # Configured MCP tools the partner may load. None = all; [] = MCP off.
    mcp_tools: list[str] | None = None


@dataclass
class LiveTurn:
    """A web turn decoupled from any single WebSocket connection.

    The turn runs as a task on the partner instance and fans its stream frames
    out to per-subscriber queues, buffering them too. A client that reconnects
    mid-turn (a page refresh) re-subscribes and replays the buffer, so the
    in-progress answer survives the reload instead of dying with the old
    socket. Frames are the same shapes the socket already sends
    (``stream_event`` / ``content`` / ``done`` / ``stopped`` / ``error``).
    """

    # The user message that opened the turn, so a client reattaching after a
    # refresh can re-show the question bubble (it isn't persisted until the
    # turn completes).
    user_content: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    terminal: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    subscribers: set[asyncio.Queue] = field(default_factory=set, repr=False)
    task: asyncio.Task | None = field(default=None, repr=False)

    def emit(self, frame: dict[str, Any]) -> None:
        self.events.append(frame)
        for queue in self.subscribers:
            queue.put_nowait(frame)

    def finish(self, frames: list[dict[str, Any]]) -> None:
        self.terminal = frames
        self.done = True
        for queue in self.subscribers:
            for frame in frames:
                queue.put_nowait(frame)
        self.subscribers.clear()

    def subscribe(self) -> asyncio.Queue:
        """Preload the backlog and register — atomically (no await between) so
        no frame is missed or duplicated at the boundary."""
        queue: asyncio.Queue = asyncio.Queue()
        for frame in (*self.events, *self.terminal):
            queue.put_nowait(frame)
        if not self.done:
            self.subscribers.add(queue)
        return queue


@dataclass
class PartnerInstance:
    """A running partner and its runtime objects."""

    partner_id: str
    config: PartnerConfig
    started_at: datetime = field(default_factory=datetime.now)
    tasks: list[asyncio.Task] = field(default_factory=list, repr=False)
    runner: PartnerRunner | None = None
    channel_manager: Any = None
    notify_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    channel_bindings: dict[str, str] = field(default_factory=dict)
    reload_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    last_reload_error: str | None = None
    # In-flight web turns by session_key, decoupled from the socket so a
    # refresh can reattach (see :class:`LiveTurn`).
    live_turns: dict[str, LiveTurn] = field(default_factory=dict, repr=False)

    @property
    def running(self) -> bool:
        return any(not t.done() for t in self.tasks)

    def to_dict(
        self,
        *,
        include_secrets: bool = False,
        mask_secrets: bool = False,
    ) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict (channel shapes as in TutorBot:
        names-only by default, masked dict for detail views, raw only for the
        explicitly-opt-in edit form)."""
        source_channels = strip_legacy_global_delivery(self.config.channels)
        if include_secrets:
            channels: Any = source_channels
        elif mask_secrets:
            channels = mask_channel_secrets(source_channels)
        else:
            channels = list(source_channels.keys())

        return {
            "partner_id": self.partner_id,
            "name": self.config.name,
            "description": self.config.description,
            "channels": channels,
            "llm_selection": self.config.llm_selection,
            "backup_llm_selection": self.config.backup_llm_selection,
            "model": self.config.model,
            "language": self.config.language,
            "emoji": self.config.emoji,
            "color": self.config.color,
            "avatar": self.config.avatar,
            "soul_origin": self.config.soul_origin,
            "enabled_tools": self.config.enabled_tools,
            "builtin_tools": self.config.builtin_tools,
            "mcp_tools": self.config.mcp_tools,
            "running": self.running,
            "started_at": self.started_at.isoformat(),
            "last_reload_error": self.last_reload_error,
        }


class PartnerManager:
    """Manage partner instances running in-process."""

    def __init__(self) -> None:
        self._partners: dict[str, PartnerInstance] = {}
        self._stores: dict[str, PartnerSessionStore] = {}
        self._migrated_legacy = False

    # ── Path helpers ──────────────────────────────────────────────

    @property
    def _partners_dir(self) -> Path:
        return get_data_dir()

    def _partner_dir(self, partner_id: str) -> Path:
        return self._partners_dir / partner_id

    def session_store(self, partner_id: str) -> PartnerSessionStore:
        store = self._stores.get(partner_id)
        if store is None:
            store = PartnerSessionStore(get_partner_sessions_dir(partner_id))
            self._stores[partner_id] = store
        return store

    def _ensure_partner_dirs(self, partner_id: str) -> None:
        get_partner_dir(partner_id)
        ensure_partner_workspace(partner_id)
        get_partner_sessions_dir(partner_id)
        if not read_soul(partner_id).strip():
            write_soul(partner_id, DEFAULT_SOUL)

    # ── Config persistence ────────────────────────────────────────

    # Every PartnerConfig field must be listed here so merge_config can update
    # it via the API; a field omitted here is silently un-updatable.
    # auto_start is intentionally absent — lifecycle state, not config.
    _MERGEABLE_FIELDS = (
        "name",
        "description",
        "channels",
        "llm_selection",
        "backup_llm_selection",
        "model",
        "language",
        "emoji",
        "color",
        "avatar",
        "soul_origin",
        "enabled_tools",
        "builtin_tools",
        "mcp_tools",
    )

    def load_config(self, partner_id: str) -> PartnerConfig | None:
        path = self._partner_dir(partner_id) / "config.yaml"
        if not path.exists():
            return None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return PartnerConfig(
                name=data.get("name", partner_id),
                description=data.get("description", ""),
                channels=strip_legacy_global_delivery(data.get("channels", {}) or {}),
                llm_selection=data.get("llm_selection"),
                backup_llm_selection=data.get("backup_llm_selection"),
                model=data.get("model"),
                language=str(data.get("language", "") or ""),
                emoji=str(data.get("emoji", "") or ""),
                color=str(data.get("color", "") or ""),
                avatar=str(data.get("avatar", "") or ""),
                soul_origin=dict(data.get("soul_origin", {}) or {}),
                enabled_tools=_optional_str_list(data.get("enabled_tools")),
                builtin_tools=_optional_str_list(data.get("builtin_tools")),
                mcp_tools=_optional_str_list(data.get("mcp_tools")),
            )
        except Exception:
            logger.exception("Failed to load partner config %s", partner_id)
            return None

    def save_config(
        self, partner_id: str, config: PartnerConfig, *, auto_start: bool | None = None
    ) -> None:
        """Persist atomically (write-temp + replace).

        ``auto_start`` is the persisted intent to launch on backend boot,
        managed separately from config fields (same contract as TutorBot —
        ``None`` preserves the on-disk value; a brand-new partner defaults to
        ``True``)."""
        partner_dir = self._partner_dir(partner_id)
        path = partner_dir / "config.yaml"
        if auto_start is None:
            auto_start = self._load_auto_start(partner_id, default=False) if path.exists() else True
        partner_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "name": config.name,
            "description": config.description,
            "channels": strip_legacy_global_delivery(config.channels),
            "language": config.language,
            "emoji": config.emoji,
            "color": config.color,
            "avatar": config.avatar,
            "soul_origin": config.soul_origin,
            "auto_start": auto_start,
        }
        if config.llm_selection:
            data["llm_selection"] = config.llm_selection
        if config.backup_llm_selection:
            data["backup_llm_selection"] = config.backup_llm_selection
        if config.model:
            data["model"] = config.model
        if config.enabled_tools is not None:
            data["enabled_tools"] = list(config.enabled_tools)
        if config.builtin_tools is not None:
            data["builtin_tools"] = list(config.builtin_tools)
        if config.mcp_tools is not None:
            data["mcp_tools"] = list(config.mcp_tools)

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        tmp_path.replace(path)

    def _load_auto_start(self, partner_id: str, *, default: bool = False) -> bool:
        path = self._partner_dir(partner_id) / "config.yaml"
        if not path.exists():
            return default
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return bool(data.get("auto_start", default))
        except Exception:
            logger.exception("Failed to load auto_start flag for partner '%s'", partner_id)
            return default

    def auto_start_enabled(self, partner_id: str, *, default: bool = False) -> bool:
        """Return whether this partner is allowed to start without an explicit user action."""
        return self._load_auto_start(partner_id, default=default)

    def merge_config(self, partner_id: str, overrides: dict[str, Any]) -> PartnerConfig:
        """Overlay non-``None`` overrides onto the on-disk config.

        Empty strings / dicts are intentional clears and DO override —
        callers must use ``None`` to mean "leave as-is"."""
        existing = self.load_config(partner_id)
        base = existing or PartnerConfig(name=partner_id)
        for key in self._MERGEABLE_FIELDS:
            if key in overrides and overrides[key] is not None:
                setattr(base, key, overrides[key])
        return base

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start_partner(
        self, partner_id: str, config: PartnerConfig | None = None
    ) -> PartnerInstance:
        if partner_id in self._partners and self._partners[partner_id].running:
            return self._partners[partner_id]

        self._ensure_partner_dirs(partner_id)

        if config is None:
            config = self.load_config(partner_id)
        if config is None:
            config = PartnerConfig(name=partner_id)
            self.save_config(partner_id, config)

        from deeptutor.partners.bus.queue import MessageBus

        bus = MessageBus()
        store = self.session_store(partner_id)
        runner = PartnerRunner(partner_id, config, bus, store, save_config=self.save_config)

        try:
            channel_manager = self._build_channel_manager(config, bus, partner_id=partner_id)
        except Exception:
            logger.exception("Failed to initialise channels for partner '%s'", partner_id)
            channel_manager = None

        instance = PartnerInstance(
            partner_id=partner_id,
            config=config,
            runner=runner,
            channel_manager=channel_manager,
        )

        runner_task = asyncio.create_task(runner.run(), name=f"partner:{partner_id}:runner")
        router_task = asyncio.create_task(
            self._outbound_router(partner_id, bus, instance),
            name=f"partner:{partner_id}:router",
        )
        instance.tasks.extend([runner_task, router_task])

        if channel_manager:
            for ch_name, ch in channel_manager.channels.items():
                instance.tasks.append(
                    asyncio.create_task(ch.start(), name=f"partner:{partner_id}:ch:{ch_name}")
                )

        self._partners[partner_id] = instance
        # Omit auto_start so save_config preserves the persisted intent: a
        # lazy start (web chat) of an auto_start:false partner must not
        # silently re-enable auto-start.
        self.save_config(partner_id, config)
        logger.info("Partner '%s' started", partner_id)
        return instance

    async def _outbound_router(self, partner_id: str, bus: Any, instance: PartnerInstance) -> None:
        """Route outbound messages to channels, web notify_queue, and EventBus."""
        try:
            from deeptutor.events.event_bus import Event, EventType, get_event_bus
            from deeptutor.partners.bus.events import OutboundMessage as _OMsg

            event_bus = get_event_bus()
            while True:
                msg: _OMsg = await bus.consume_outbound()
                is_progress = bool(msg.metadata and msg.metadata.get("_progress"))

                if instance.channel_manager:
                    channel = instance.channel_manager.get_channel(msg.channel)
                    if channel:
                        try:
                            await channel.send(msg)
                        except Exception:
                            logger.exception(
                                "Failed to send to channel %s for partner %s",
                                msg.channel,
                                partner_id,
                            )
                        if not is_progress and msg.chat_id:
                            instance.channel_bindings[msg.channel] = msg.chat_id

                if not is_progress:
                    await instance.notify_queue.put(msg.content or "")
                    await event_bus.publish(
                        Event(
                            type=EventType.CAPABILITY_COMPLETE,
                            task_id=f"partner:{partner_id}:{msg.channel}:{msg.chat_id}",
                            user_input="",
                            agent_output=msg.content or "",
                            metadata={
                                "source": "partner",
                                "partner_id": partner_id,
                                "channel": msg.channel,
                                "chat_id": msg.chat_id,
                            },
                        )
                    )
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Outbound router failed for partner %s", partner_id)

    async def stop_partner(self, partner_id: str, *, preserve_auto_start: bool = False) -> bool:
        """Stop a running partner.

        Manual stops disable future auto-starts; process shutdown preserves
        the persisted intent so host restarts bring the same partners back."""
        instance = self._partners.get(partner_id)
        if not instance:
            return False
        auto_start = (
            self._load_auto_start(partner_id, default=True) if preserve_auto_start else False
        )

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
                logger.exception("Error stopping channels for partner '%s'", partner_id)

        self.save_config(partner_id, instance.config, auto_start=auto_start)
        del self._partners[partner_id]
        logger.info("Partner '%s' stopped (auto_start=%s)", partner_id, auto_start)
        return True

    def _build_channel_manager(
        self,
        config: PartnerConfig,
        bus: Any,
        *,
        partner_id: str,
    ) -> Any | None:
        """Construct a ``ChannelManager`` from ``config.channels`` or ``None``."""
        if not config.channels:
            return None
        from deeptutor.partners.channels.manager import ChannelManager
        from deeptutor.partners.config.schema import ChannelsConfig

        channels_config = ChannelsConfig(**config.channels)
        manager = ChannelManager(channels_config, bus)
        if not manager.channels:
            logger.info("No channels matched config for partner '%s'", partner_id)
            return None
        logger.info(
            "Channels enabled for partner '%s': %s",
            partner_id,
            list(manager.channels.keys()),
        )
        return manager

    async def reload_channels(self, partner_id: str) -> None:
        """Restart channel listeners from ``instance.config.channels``.

        Cancels only ``partner:{id}:ch:*`` tasks; runner and router keep
        running. Serialised per partner via ``instance.reload_lock``. On
        failure the listeners stay down and the error is recorded on
        ``instance.last_reload_error`` for the UI."""
        instance = self._partners.get(partner_id)
        if not instance or not instance.running:
            return

        async with instance.reload_lock:
            await self._teardown_channel_listeners(instance, partner_id)

            try:
                channel_manager = self._build_channel_manager(
                    instance.config,
                    instance.runner.bus if instance.runner else None,
                    partner_id=partner_id,
                )
            except Exception as exc:
                logger.exception("Failed to reload channels for partner '%s'", partner_id)
                instance.channel_manager = None
                instance.last_reload_error = f"{type(exc).__name__}: {exc}"
                raise

            instance.channel_manager = channel_manager
            instance.last_reload_error = None
            if channel_manager:
                for ch_name, ch in channel_manager.channels.items():
                    instance.tasks.append(
                        asyncio.create_task(ch.start(), name=f"partner:{partner_id}:ch:{ch_name}")
                    )
                logger.info(
                    "Reloaded channels for partner '%s': %s",
                    partner_id,
                    list(channel_manager.channels.keys()),
                )

    async def _teardown_channel_listeners(
        self,
        instance: PartnerInstance,
        partner_id: str,
    ) -> None:
        ch_prefix = f"partner:{partner_id}:ch:"
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
                logger.exception(
                    "Error stopping channels before reload for partner '%s'", partner_id
                )

        instance.channel_manager = None
        instance.channel_bindings.clear()

    # ── Listing & discovery ───────────────────────────────────────

    def _discover_partner_ids(self) -> set[str]:
        self._migrate_legacy_tutorbot()
        ids: set[str] = set()
        if not self._partners_dir.exists():
            return ids
        for entry in self._partners_dir.iterdir():
            if entry.name in _RESERVED_NAMES or entry.name.startswith((".", "_")):
                continue
            if entry.is_dir() and (entry / "config.yaml").exists():
                ids.add(entry.name)
        return ids

    def list_partners(self) -> list[dict[str, Any]]:
        """All known partners (running + configured on disk); channels keys-only."""
        result: dict[str, dict[str, Any]] = {}

        for inst in self._partners.values():
            result[inst.partner_id] = inst.to_dict()

        for pid in self._discover_partner_ids():
            if pid in result:
                continue
            cfg = self.load_config(pid)
            result[pid] = {
                "partner_id": pid,
                "name": cfg.name if cfg else pid,
                "description": cfg.description if cfg else "",
                "channels": list(cfg.channels.keys()) if cfg else [],
                "llm_selection": cfg.llm_selection if cfg else None,
                "backup_llm_selection": cfg.backup_llm_selection if cfg else None,
                "model": cfg.model if cfg else None,
                "language": cfg.language if cfg else "",
                "emoji": cfg.emoji if cfg else "",
                "color": cfg.color if cfg else "",
                "avatar": cfg.avatar if cfg else "",
                "soul_origin": cfg.soul_origin if cfg else {},
                "enabled_tools": cfg.enabled_tools if cfg else None,
                "builtin_tools": cfg.builtin_tools if cfg else None,
                "mcp_tools": cfg.mcp_tools if cfg else None,
                "running": False,
                "started_at": None,
            }

        return list(result.values())

    def get_partner(self, partner_id: str) -> PartnerInstance | None:
        return self._partners.get(partner_id)

    def partner_exists(self, partner_id: str) -> bool:
        return (self._partner_dir(partner_id) / "config.yaml").exists()

    @staticmethod
    def web_session_key(
        partner_id: str, *, chat_id: str = "web", session_id: str | None = None
    ) -> str:
        normalized_session = str(session_id or "").strip()
        if normalized_session:
            return f"web:{normalized_session}"
        normalized_chat = str(chat_id or "web").strip() or "web"
        if normalized_chat != "web":
            return f"web:{normalized_chat}"
        return f"partner:{partner_id}"

    def get_history(
        self, partner_id: str, *, session_key: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        store = self.session_store(partner_id)
        if session_key:
            return store.messages(session_key, limit=limit)
        return store.merged_messages(limit=limit)

    def get_recent_active_partners(self, limit: int = 3) -> list[dict[str, Any]]:
        activity: list[tuple[str, dict[str, Any]]] = []
        for pid in self._discover_partner_ids():
            sessions = self.session_store(pid).list_sessions()
            if not sessions:
                continue
            newest = sessions[0]
            cfg = self.load_config(pid)
            instance = self._partners.get(pid)
            activity.append(
                (
                    str(newest.get("updated_at", "")),
                    {
                        "partner_id": pid,
                        "name": cfg.name if cfg else pid,
                        "running": instance.running if instance else False,
                        "last_message": newest.get("last_message", ""),
                        "updated_at": newest.get("updated_at", ""),
                    },
                )
            )
        activity.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in activity[:limit]]

    # ── Messaging (web entry point) ───────────────────────────────

    async def send_message(
        self,
        partner_id: str,
        content: str,
        chat_id: str = "web",
        session_id: str | None = None,
        media: list[str] | None = None,
        on_event: Callable[[Any], Awaitable[None]] | None = None,
        session_key: str | None = None,
    ) -> str:
        """Send a web message to a running partner and return the reply.

        ``session_key``, when given, is used verbatim (the web app drives a
        stable, colon-free key it persists locally); otherwise it is derived
        from ``session_id`` / ``chat_id`` via :meth:`web_session_key`.
        """
        instance = self._partners.get(partner_id)
        if not instance or not instance.running or not instance.runner:
            raise RuntimeError(f"Partner '{partner_id}' is not running")

        from deeptutor.partners.bus.events import InboundMessage

        resolved_key = (
            str(session_key).strip()
            if session_key
            else self.web_session_key(partner_id, chat_id=chat_id, session_id=session_id)
        )
        msg = InboundMessage(
            channel="web",
            sender_id="web",
            chat_id=session_id or chat_id,
            content=content,
            media=media or [],
            session_key_override=resolved_key,
        )
        return await instance.runner.process_message(msg, on_event=on_event)

    # ── Live web turns (refresh-survivable streaming) ─────────────

    def start_web_turn(
        self,
        partner_id: str,
        session_key: str,
        content: str,
        media: list[str] | None = None,
    ) -> "LiveTurn":
        """Run a web turn as an instance-owned task and return its LiveTurn.

        If a turn is already in flight for this session, returns it (one at a
        time per session). The turn keeps running even if every socket detaches.
        """
        instance = self._partners.get(partner_id)
        if not instance or not instance.running or not instance.runner:
            raise RuntimeError(f"Partner '{partner_id}' is not running")
        existing = instance.live_turns.get(session_key)
        if existing is not None and not existing.done:
            return existing
        turn = LiveTurn(user_content=content)
        instance.live_turns[session_key] = turn
        turn.task = asyncio.create_task(
            self._drive_web_turn(partner_id, session_key, content, media or [], turn),
            name=f"partner:{partner_id}:webturn",
        )
        return turn

    def subscribe_web_turn(self, partner_id: str, session_key: str) -> "LiveTurn | None":
        """The in-flight turn for a session, or None (completed turns are read
        back from history instead)."""
        instance = self._partners.get(partner_id)
        if not instance:
            return None
        turn = instance.live_turns.get(session_key)
        return turn if turn is not None and not turn.done else None

    def stop_web_turn(self, partner_id: str, session_key: str) -> bool:
        instance = self._partners.get(partner_id)
        if not instance:
            return False
        turn = instance.live_turns.get(session_key)
        if turn is None or turn.done or turn.task is None or turn.task.done():
            return False
        turn.task.cancel()
        return True

    async def _drive_web_turn(
        self,
        partner_id: str,
        session_key: str,
        content: str,
        media: list[str],
        turn: "LiveTurn",
    ) -> None:
        async def on_event(event: Any) -> None:
            turn.emit({"type": "stream_event", "event": event.to_dict()})

        try:
            final = await self.send_message(
                partner_id,
                content,
                session_key=session_key,
                media=media,
                on_event=on_event,
            )
            turn.finish([{"type": "content", "content": final}, {"type": "done"}])
        except asyncio.CancelledError:
            turn.finish([{"type": "stopped"}])
            raise
        except RuntimeError as exc:
            turn.finish([{"type": "error", "content": str(exc)}, {"type": "done"}])
        except Exception as exc:  # noqa: BLE001
            logger.exception("Web turn crashed for partner '%s'", partner_id)
            turn.finish(
                [
                    {"type": "error", "content": f"Internal error ({type(exc).__name__})"},
                    {"type": "done"},
                ]
            )

    # ── Session lifecycle (web management) ────────────────────────

    def resume_session(self, partner_id: str, session_key: str) -> dict[str, Any] | None:
        """Clear a session's archived flag so it becomes current again."""
        store = self.session_store(partner_id)
        store.set_archived(session_key, False)
        for session in store.list_sessions():
            if session["session_key"] == store._stem(session_key):
                return session
        return None

    def delete_session(self, partner_id: str, session_key: str) -> bool:
        return self.session_store(partner_id).delete_session(session_key)

    def branch_session(
        self, partner_id: str, source_key: str, new_key: str
    ) -> dict[str, Any] | None:
        return self.session_store(partner_id).branch(source_key, new_key)

    def archive_session(self, partner_id: str, session_key: str) -> None:
        self.session_store(partner_id).set_archived(session_key, True)

    # ── Boot / shutdown ───────────────────────────────────────────

    async def auto_start_partners(self) -> None:
        for pid in self._discover_partner_ids():
            if pid in self._partners and self._partners[pid].running:
                continue
            try:
                if not self._load_auto_start(pid, default=False):
                    continue
                config = self.load_config(pid)
                if config is None:
                    continue
                await self.start_partner(pid, config)
                logger.info("Auto-started partner '%s'", pid)
            except Exception:
                logger.exception("Failed to auto-start partner '%s'", pid)

    async def stop_all(self, *, preserve_auto_start: bool = True) -> None:
        for partner_id in list(self._partners.keys()):
            await self.stop_partner(partner_id, preserve_auto_start=preserve_auto_start)

    async def destroy_partner(self, partner_id: str) -> bool:
        await self.stop_partner(partner_id, preserve_auto_start=False)
        self._stores.pop(partner_id, None)
        try:
            from deeptutor.services.cron import get_cron_service

            get_cron_service().remove_owner_jobs(f"partner:{partner_id}")
        except Exception:
            logger.warning("Failed to clear cron jobs for '%s'", partner_id, exc_info=True)
        partner_dir = self._partner_dir(partner_id)
        if not partner_dir.exists():
            return False
        shutil.rmtree(partner_dir)
        logger.info("Partner '%s' destroyed (data deleted)", partner_id)
        return True

    # ── Legacy TutorBot migration ─────────────────────────────────

    def _migrate_legacy_tutorbot(self) -> None:
        """One-shot migration of ``data/tutorbot/`` bots into partners.

        Channel configs (with secrets), LLM selection, and souls survive;
        the old engine's bootstrap files do not. ``persona`` becomes the
        partner's SOUL.md. The legacy tree is left in place untouched so the
        migration is non-destructive."""
        if self._migrated_legacy:
            return
        self._migrated_legacy = True

        legacy_root = self._partners_dir.parent / "tutorbot"
        if not legacy_root.is_dir():
            return

        legacy_souls = legacy_root / "_souls.yaml"
        new_souls = self._souls_file
        if legacy_souls.is_file() and not new_souls.exists():
            try:
                self._partners_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy_souls, new_souls)
            except OSError:
                logger.exception("Failed to migrate TutorBot souls library")

        for entry in legacy_root.iterdir():
            if not entry.is_dir() or entry.name in _RESERVED_NAMES | {"bots"}:
                continue
            legacy_config = entry / "config.yaml"
            if not legacy_config.is_file():
                continue
            partner_id = entry.name
            if (self._partner_dir(partner_id) / "config.yaml").exists():
                continue
            try:
                data = yaml.safe_load(legacy_config.read_text(encoding="utf-8")) or {}
                config = PartnerConfig(
                    name=data.get("name", partner_id),
                    description=data.get("description", ""),
                    channels=data.get("channels", {}) or {},
                    llm_selection=data.get("llm_selection"),
                    model=data.get("model"),
                    soul_origin={"type": "tutorbot", "id": partner_id},
                )
                self._ensure_partner_dirs(partner_id)
                persona = str(data.get("persona", "") or "").strip()
                if persona:
                    write_soul(partner_id, persona)
                self.save_config(partner_id, config, auto_start=bool(data.get("auto_start", False)))
                legacy_sessions = entry / "workspace" / "sessions"
                if legacy_sessions.is_dir():
                    dst = get_partner_sessions_dir(partner_id)
                    for jsonl in legacy_sessions.glob("*.jsonl"):
                        target = dst / jsonl.name
                        if not target.exists():
                            shutil.copy2(jsonl, target)
                logger.info("Migrated TutorBot '%s' to partner", partner_id)
            except Exception:
                logger.exception("Failed to migrate TutorBot '%s'", partner_id)

    # ── Soul template library ─────────────────────────────────────

    @property
    def _souls_file(self) -> Path:
        return self._partners_dir / "_souls.yaml"

    def _load_souls(self) -> list[dict[str, str]]:
        path = self._souls_file
        if not path.exists():
            self._seed_default_souls()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            souls = data if isinstance(data, list) else []
        except Exception:
            return []
        refreshed = _refresh_stale_default_souls(souls)
        if refreshed is not None:
            self._save_souls(refreshed)
            return refreshed
        return souls

    def _save_souls(self, souls: list[dict[str, str]]) -> None:
        self._partners_dir.mkdir(parents=True, exist_ok=True)
        self._souls_file.write_text(
            yaml.dump(souls, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

    def _seed_default_souls(self) -> None:
        self._save_souls([dict(entry) for entry in DEFAULT_SOUL_TEMPLATES])

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


# ── Default soul templates ────────────────────────────────────────
#
# Seeded into a fresh library, and used to refresh untouched copies of the
# old seeds (see ``_refresh_stale_default_souls``). Partners live in IM
# channels, so every template bakes in a chat-sized voice.

DEFAULT_SOUL_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "id": "companion",
        "name": "Learning Companion",
        "content": """# Soul

I am a learning companion — a steady, curious presence that helps people
actually understand things, not just collect answers.

## Voice

- Warm, direct, and concrete; no lecture-hall tone
- Chat-sized messages: one idea at a time, short paragraphs
- Plain words first, precise terms second — I define jargon the moment I use it

## How I help

- Start from what you already know, then build exactly one step up
- Prefer a worked example over an abstract explanation
- Check understanding with one small question, never a quiz barrage
- When I don't know, I say so and find out — accuracy beats fluency

## Boundaries

- On homework-style questions I guide before I reveal: hint, stronger hint, then the step
- I keep your pace — encouragement, never condescension
""",
    },
    {
        "id": "math-tutor",
        "name": "Math Tutor",
        "content": """# Soul

I am a math tutor. What I'm after is the moment it clicks — not the answer itself.

## Voice

- Calm and unhurried; math anxiety is real and I never feed it
- Small steps, one per message, written to be read in a chat window
- Notation when it sharpens the idea, words when they're clearer

## Method

- Diagnose first: where exactly does your reasoning break?
- Socratic by default — a nudge, then a stronger hint, then the step itself
- Always ask "why does this rule work", not just "apply this rule"
- After we solve it, one quick variation to confirm it actually clicked

## Habits

- Estimate before computing; sanity-check after
- A wrong answer is information, not failure — we find the good idea inside it
""",
    },
    {
        "id": "coding-assistant",
        "name": "Coding Assistant",
        "content": """# Soul

I am a coding assistant — a pragmatic pair programmer living in your chat.

## Voice

- Precise and to the point: the snippet that matters, not a wall of code
- Code speaks first, prose explains why
- Honest about uncertainty and trade-offs — no hand-waving

## Craft

- Read before writing: respect the existing style and constraints
- Smallest change that solves the problem; name the trade-off when there is one
- Errors and edge cases are part of the answer, not an afterthought
- Every fix ships with a way to verify it — a test, a command, an expected output

## Boundaries

- I don't guess APIs; when unsure I say so and show how to check
""",
    },
    {
        "id": "research-helper",
        "name": "Research Helper",
        "content": """# Soul

I am a research helper. I turn vague questions into answerable ones, and
answers into something you can actually trust.

## Voice

- Neutral and curious; I argue with evidence, not adjectives
- Structured replies sized for chat: the claim, the evidence, what's still open

## Method

- Decompose broad questions into specific sub-questions before searching
- Separate established findings, active debate, and speculation — and label which is which
- Prefer primary sources; cite what I rely on so you can check it
- Steelman the opposing reading before settling a question

## Honesty

- "The evidence is thin here" is a finding, not an apology
- I flag my own uncertainty instead of smoothing it over
""",
    },
    {
        "id": "language-tutor",
        "name": "Language Tutor",
        "content": """# Soul

I am a language tutor. You learn a language by using it — so this chat is
the classroom.

## Voice

- Friendly and a little playful; mistakes are welcome here
- I match your level: simple words for beginners, nuance as you grow

## Method

- Converse first, correct second: I respond to what you said, then gently fix how you said it
- One correction at a time, with a one-line why
- Phrases in context, never isolated word lists
- I recycle yesterday's vocabulary into today's conversation

## Habits

- I celebrate attempts at structures we haven't covered yet
- Ask me "how do I say X" and you get the natural phrasing, not the literal one
""",
    },
)

# Verbatim texts of retired seeds (including the TutorBot-era variants).
# A library entry that still matches one of these — or that sits on a seed
# id and still mentions TutorBot — is an untouched old seed: safe to swap
# for the current template without losing any user writing.
_TUTORBOT_SEED = (
    "# Soul\n\nI am TutorBot, a personal learning companion.\n\n"
    "## Personality\n\n- Helpful and friendly\n- Clear, encouraging, and patient\n"
    "- Adapts explanations to the user's level\n\n"
    "## Values\n\n- Accuracy over speed\n- User privacy and safety\n- Transparency in actions"
)
_SUPERSEDED_SOUL_CONTENTS = frozenset(
    {
        _TUTORBOT_SEED,
        _TUTORBOT_SEED.replace("I am TutorBot,", "I am"),
        (
            "# Soul\n\nI am a math tutor specializing in clear, step-by-step problem solving.\n\n"
            "## Personality\n\n- Patient and methodical\n- Encourages showing work\n"
            "- Celebrates progress on hard problems\n\n"
            "## Teaching Style\n\n- Break complex problems into small steps\n"
            "- Use visual representations when possible\n- Always verify final answers"
        ),
        (
            "# Soul\n\nI am a coding assistant focused on helping developers write better software.\n\n"
            "## Personality\n\n- Precise and detail-oriented\n"
            "- Pragmatic — working code over perfect code\n- Explains trade-offs clearly\n\n"
            "## Approach\n\n- Read before writing; understand context first\n"
            "- Suggest tests alongside implementations\n- Prefer standard patterns over clever tricks"
        ),
        (
            "# Soul\n\nI am a research assistant helping users explore academic topics in depth.\n\n"
            "## Personality\n\n- Curious and thorough\n"
            "- Balanced — presents multiple perspectives\n- Cites sources when possible\n\n"
            "## Approach\n\n- Decompose broad questions into focused sub-questions\n"
            "- Distinguish established facts from open questions\n- Suggest further reading"
        ),
        (
            "# Soul\n\nI am a language learning companion helping users practice and improve.\n\n"
            "## Personality\n\n- Encouraging and patient\n"
            "- Adapts difficulty to learner level\n- Makes learning fun with examples\n\n"
            "## Teaching Style\n\n- Correct mistakes gently with explanations\n"
            "- Use contextual examples over abstract rules\n- Encourage speaking/writing practice"
        ),
    }
)
# TutorBot-era libraries shipped the default under these ids.
_LEGACY_SOUL_ID_ALIASES = {"default-tutorbot": "companion", "default": "companion"}


def _is_stale_seed(entry: dict[str, str]) -> bool:
    content = str(entry.get("content") or "")
    return content.strip() in {c.strip() for c in _SUPERSEDED_SOUL_CONTENTS} or (
        "tutorbot" in content.lower()
    )


def _refresh_stale_default_souls(
    souls: list[dict[str, str]],
) -> list[dict[str, str]] | None:
    """Upgrade untouched old-seed entries in place; ``None`` if nothing changed.

    Only entries on known seed ids (or their TutorBot-era aliases) are
    touched, and only when their content is provably an old seed — user-
    authored and user-edited souls pass through verbatim.
    """
    defaults = {e["id"]: e for e in DEFAULT_SOUL_TEMPLATES}
    present_ids = {str(e.get("id") or "") for e in souls}
    out: list[dict[str, str]] = []
    changed = False
    for entry in souls:
        sid = str(entry.get("id") or "")
        canonical = _LEGACY_SOUL_ID_ALIASES.get(sid, sid)
        if canonical not in defaults or not _is_stale_seed(entry):
            out.append(entry)
            continue
        changed = True
        if canonical != sid and canonical in present_ids:
            continue  # canonical entry exists separately; drop the legacy alias
        if any(str(e.get("id")) == canonical for e in out):
            continue  # a second alias already collapsed into this id
        out.append(dict(defaults[canonical]))
        present_ids.add(canonical)
    return out if changed else None


_manager: PartnerManager | None = None


def get_partner_manager() -> PartnerManager:
    global _manager
    if _manager is None:
        _manager = PartnerManager()
    return _manager
