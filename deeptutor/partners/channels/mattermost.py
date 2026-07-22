"""Mattermost channel implementation using the native v4 WebSocket + REST API.

Mattermost is a self-hostable, open-source team chat platform. This channel
talks to its *own* API (``/api/v4/websocket`` for events, ``/api/v4`` REST for
sending), so self-hosted deployments get a first-class integration instead of
routing through Mattermost's Slack-compatibility shim.

Transport mirrors the Discord channel — ``httpx`` for REST and ``websockets``
for the event stream — so no extra dependency is needed. Keepalive relies on
the standard WebSocket ping/pong (Mattermost has no app-level heartbeat opcode,
unlike Discord's gateway), and Mattermost renders Markdown natively, so replies
need no format conversion (unlike Slack's mrkdwn).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import ssl
from typing import Any, Literal

import httpx
from loguru import logger
from pydantic import Field
import websockets

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import BaseChannel
from deeptutor.partners.config.paths import get_media_dir
from deeptutor.partners.config.schema import DeliveryOverrides
from deeptutor.partners.helpers import split_message

MATTERMOST_API_PATH = "/api/v4"
# Mattermost's default max post length is 16383 chars; stay safely under it.
MAX_MESSAGE_LEN = 16000
# Mattermost's default max file size is 50MB.
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
# Standard WebSocket keepalive — the lib pings, the server pongs.
WS_PING_INTERVAL_S = 30.0
WS_PING_TIMEOUT_S = 30.0
# Posts are bounded text; bump the frame cap above the 1MB default for headroom.
WS_MAX_MESSAGE_BYTES = 8 * 1024 * 1024
WS_RECONNECT_DELAY_S = 5.0


class MattermostConfig(DeliveryOverrides):
    """Mattermost channel configuration."""

    enabled: bool = False
    # Base server URL, e.g. ``https://mattermost.example.com`` (scheme optional).
    server_url: str = ""
    # Bot account personal access token (Integrations → Bot Accounts).
    bot_token: str = Field(default="", repr=False)
    allow_from: list[str] = Field(default_factory=list)
    # In multi-user channels, respond only when @-mentioned, or to every message.
    group_policy: Literal["mention", "open"] = "mention"
    reply_in_thread: bool = True
    # Self-hosted servers may use a self-signed cert; allow opting out of verify.
    verify_ssl: bool = True


class MattermostChannel(BaseChannel):
    """Mattermost channel using the native v4 WebSocket event stream."""

    name = "mattermost"
    display_name = "Mattermost"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return MattermostConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = MattermostConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: MattermostConfig = config
        self._api_base = self._api_base_url(self.config.server_url)
        self._http: httpx.AsyncClient | None = None
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._bot_user_id: str | None = None
        self._bot_username: str = ""

    # ── URL helpers (pure, testable) ──────────────────────────────────

    @staticmethod
    def _normalize_base_url(server_url: str) -> str:
        """Strip trailing slashes and default to https when no scheme is given."""
        base = (server_url or "").strip().rstrip("/")
        if not base:
            return ""
        if not base.startswith(("http://", "https://")):
            base = f"https://{base}"
        return base

    @classmethod
    def _api_base_url(cls, server_url: str) -> str:
        base = cls._normalize_base_url(server_url)
        return f"{base}{MATTERMOST_API_PATH}" if base else ""

    @classmethod
    def _websocket_url(cls, server_url: str) -> str:
        base = cls._normalize_base_url(server_url)
        if not base:
            return ""
        if base.startswith("https://"):
            ws_base = "wss://" + base[len("https://") :]
        else:
            ws_base = "ws://" + base[len("http://") :]
        return f"{ws_base}{MATTERMOST_API_PATH}/websocket"

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to the Mattermost WebSocket, reconnecting on drop."""
        if not self.config.server_url or not self.config.bot_token:
            logger.error("Mattermost serverUrl/botToken not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.config.bot_token}"},
            timeout=30.0,
            verify=self.config.verify_ssl,
        )

        ws_url = self._websocket_url(self.config.server_url)
        connect_kwargs = self._ws_connect_kwargs(ws_url)

        while self._running:
            try:
                # Resolve our own identity first — we must know it to skip our
                # own posts (echo loop) and to detect @-mentions.
                if not await self._ensure_bot_identity():
                    if self._running:
                        await asyncio.sleep(WS_RECONNECT_DELAY_S)
                    continue

                logger.info("Connecting to Mattermost WebSocket {}...", ws_url)
                async with websockets.connect(ws_url, **connect_kwargs) as ws:
                    self._ws = ws
                    await self._authenticate()
                    logger.info("Mattermost WebSocket connected as @{}", self._bot_username)
                    await self._event_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Mattermost WebSocket error: {}", e)
            finally:
                self._ws = None

            if self._running:
                logger.info("Reconnecting to Mattermost in {}s...", WS_RECONNECT_DELAY_S)
                await asyncio.sleep(WS_RECONNECT_DELAY_S)

    async def stop(self) -> None:
        """Stop the channel and release the WebSocket + HTTP client."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.warning("Mattermost WebSocket close failed: {}", e)
            self._ws = None
        if self._http:
            await self._http.aclose()
            self._http = None

    def _ws_connect_kwargs(self, ws_url: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "ping_interval": WS_PING_INTERVAL_S,
            "ping_timeout": WS_PING_TIMEOUT_S,
            "max_size": WS_MAX_MESSAGE_BYTES,
        }
        if ws_url.startswith("wss://") and not self.config.verify_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl"] = ctx
        return kwargs

    async def _ensure_bot_identity(self) -> bool:
        """Resolve the bot's user id / username via REST (validates the token)."""
        if self._bot_user_id:
            return True
        if not self._http:
            return False
        try:
            resp = await self._http.get(f"{self._api_base}/users/me")
            resp.raise_for_status()
            me = resp.json()
            self._bot_user_id = me.get("id")
            self._bot_username = me.get("username") or ""
            logger.info("Mattermost bot identity: @{} ({})", self._bot_username, self._bot_user_id)
            return bool(self._bot_user_id)
        except Exception as e:
            logger.error("Mattermost: failed to resolve bot identity via /users/me: {}", e)
            return False

    async def _authenticate(self) -> None:
        """Send the WebSocket auth challenge with the bot token."""
        if not self._ws:
            return
        await self._ws.send(
            json.dumps(
                {
                    "seq": 1,
                    "action": "authentication_challenge",
                    "data": {"token": self.config.bot_token},
                }
            )
        )

    # ── Inbound ───────────────────────────────────────────────────────

    async def _event_loop(self) -> None:
        """Read events until the socket closes; dispatch ``posted`` events."""
        if not self._ws:
            return
        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.debug("Mattermost: non-JSON frame ignored")
                continue
            if data.get("event") != "posted":
                continue
            try:
                await self._handle_posted(data.get("data") or {})
            except Exception:
                logger.exception("Mattermost: error handling posted event")

    async def _handle_posted(self, data: dict[str, Any]) -> None:
        """Handle a ``posted`` event: filter, gate, then forward to the bus."""
        raw_post = data.get("post")
        if not isinstance(raw_post, str):
            return
        try:
            post = json.loads(raw_post)
        except json.JSONDecodeError:
            return

        # System messages (joins, header edits, …) carry a non-empty ``type``.
        if post.get("type"):
            return

        user_id = str(post.get("user_id") or "")
        channel_id = str(post.get("channel_id") or "")
        if not user_id or not channel_id:
            return
        # Never react to our own posts — that would loop forever.
        if self._bot_user_id and user_id == self._bot_user_id:
            return
        if not self.is_allowed(user_id):
            return

        channel_type = data.get("channel_type") or ""  # D / O / P / G
        is_direct = channel_type == "D"
        message = post.get("message") or ""

        if not is_direct and not self._should_respond_in_channel(message, data):
            return

        message = self._strip_bot_mention(message)

        # Threading: a reply carries ``root_id``; a root post is its own thread.
        reply_root = post.get("root_id") or ""
        if self.config.reply_in_thread and not reply_root:
            reply_root = str(post.get("id") or "")

        media_paths = await self._download_files(post)

        if not message and not media_paths:
            return

        # Thread-scoped session key for channel/group messages (DMs stay
        # channel-scoped via the default key).
        session_key = (
            f"{self.name}:{channel_id}:{reply_root}" if reply_root and not is_direct else None
        )

        await self._handle_message(
            sender_id=user_id,
            chat_id=channel_id,
            content=message or "[empty message]",
            media=media_paths,
            metadata={
                "mattermost": {
                    "root_id": reply_root,
                    "channel_type": channel_type,
                    "post_id": post.get("id"),
                },
            },
            session_key=session_key,
        )

    def _should_respond_in_channel(self, message: str, data: dict[str, Any]) -> bool:
        """Apply the group-channel policy (open vs. mention-only)."""
        if self.config.group_policy == "open":
            return True
        # "mention": the event carries a JSON-encoded list of mentioned user ids;
        # fall back to scanning the rendered text for ``@username``.
        if self._bot_user_id:
            mentions = data.get("mentions")
            if isinstance(mentions, str):
                try:
                    if self._bot_user_id in json.loads(mentions):
                        return True
                except json.JSONDecodeError:
                    pass
        if self._bot_username and f"@{self._bot_username}" in message:
            return True
        return False

    def _strip_bot_mention(self, text: str) -> str:
        if not text or not self._bot_username:
            return text
        return re.sub(rf"@{re.escape(self._bot_username)}\b\s*", "", text).strip()

    async def _download_files(self, post: dict[str, Any]) -> list[str]:
        file_ids = post.get("file_ids") or []
        if not file_ids or not self._http:
            return []
        media_dir = get_media_dir("mattermost")
        paths: list[str] = []
        for file_id in file_ids:
            local = await self._download_file(str(file_id), media_dir)
            if local:
                paths.append(local)
        return paths

    async def _download_file(self, file_id: str, media_dir: Path) -> str | None:
        assert self._http is not None
        try:
            info_resp = await self._http.get(f"{self._api_base}/files/{file_id}/info")
            info_resp.raise_for_status()
            info = info_resp.json()
            name = info.get("name") or file_id
            size = info.get("size") or 0
            if size and size > MAX_ATTACHMENT_BYTES:
                logger.warning("Mattermost attachment too large, skipping: {}", name)
                return None

            data_resp = await self._http.get(f"{self._api_base}/files/{file_id}")
            data_resp.raise_for_status()

            media_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^\w.\-]", "_", name).strip("._") or file_id
            dest = media_dir / f"{file_id}_{safe_name}"
            dest.write_bytes(data_resp.content)
            return str(dest)
        except Exception as e:
            logger.warning("Mattermost: failed to download attachment {}: {}", file_id, e)
            return None

    # ── Outbound ──────────────────────────────────────────────────────

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Mattermost, threading and uploading as needed.

        Raises on text-post failure so the channel manager's retry policy
        applies; per-file upload failures stay best-effort.
        """
        if not self._http:
            logger.warning("Mattermost HTTP client not running")
            return

        meta = msg.metadata.get("mattermost", {}) if msg.metadata else {}
        root_id = meta.get("root_id") or ""

        # Upload attachments first; the first post carries their file ids.
        file_ids: list[str] = []
        for media_path in msg.media or []:
            file_id = await self._upload_file(msg.chat_id, media_path)
            if file_id:
                file_ids.append(file_id)

        chunks = split_message(msg.content or "", MAX_MESSAGE_LEN)
        if not chunks:
            if not file_ids:
                return
            chunks = [""]  # media-only message still needs one post to carry files

        for i, chunk in enumerate(chunks):
            await self._create_post(
                msg.chat_id,
                chunk,
                root_id=root_id,
                file_ids=file_ids if i == 0 else None,
            )

    async def _create_post(
        self,
        channel_id: str,
        message: str,
        *,
        root_id: str = "",
        file_ids: list[str] | None = None,
    ) -> None:
        assert self._http is not None
        payload: dict[str, Any] = {"channel_id": channel_id, "message": message}
        if root_id:
            payload["root_id"] = root_id
        if file_ids:
            payload["file_ids"] = file_ids
        resp = await self._http.post(f"{self._api_base}/posts", json=payload)
        resp.raise_for_status()

    async def _upload_file(self, channel_id: str, file_path: str) -> str | None:
        assert self._http is not None
        path = Path(file_path)
        if not path.is_file():
            logger.warning("Mattermost file not found, skipping: {}", file_path)
            return None
        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            logger.warning(
                "Mattermost file too large (>{}MB), skipping: {}",
                MAX_ATTACHMENT_BYTES // (1024 * 1024),
                path.name,
            )
            return None
        try:
            with open(path, "rb") as f:
                files = {"files": (path.name, f, "application/octet-stream")}
                resp = await self._http.post(
                    f"{self._api_base}/files",
                    params={"channel_id": channel_id},
                    files=files,
                )
            resp.raise_for_status()
            infos = resp.json().get("file_infos") or []
            if infos:
                return infos[0].get("id")
        except Exception as e:
            logger.error("Mattermost file upload failed for {}: {}", path.name, e)
        return None
