"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""

import asyncio
import base64
from collections import OrderedDict
from dataclasses import dataclass
from http import HTTPStatus
import importlib.util
import inspect
import json
import os
import re
import shlex
import threading
from threading import Lock
import time
from typing import Any, Literal
import uuid

from loguru import logger
from pydantic import Field

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import BaseChannel
from deeptutor.partners.config.schema import DeliveryOverrides, StreamingSupport
from deeptutor.partners.helpers import split_markdown_table_row

FEISHU_AVAILABLE = importlib.util.find_spec("lark_oapi") is not None


def _card_aware_ws_client(base_client: type[Any], ws_module: Any) -> type[Any]:
    """Dispatch card callbacks skipped by supported lark-oapi WebSocket clients.

    The SDK's event dispatcher already understands card actions; older WS
    clients return before calling it. Keep the original CARD frame type when
    writing the callback response so Feishu can replace the clicked card.
    """

    class CardAwareClient(base_client):
        async def _handle_data_frame(self, frame: Any) -> None:
            message_type = ws_module._get_by_key(frame.headers, ws_module.HEADER_TYPE)
            if message_type != ws_module.MessageType.CARD.value:
                await super()._handle_data_frame(frame)
                return

            headers = frame.headers
            message_id = ws_module._get_by_key(headers, ws_module.HEADER_MESSAGE_ID)
            part_count = int(ws_module._get_by_key(headers, ws_module.HEADER_SUM))
            part_number = int(ws_module._get_by_key(headers, ws_module.HEADER_SEQ))
            payload = frame.payload
            if part_count > 1:
                payload = self._combine(message_id, part_count, part_number, payload)
                if payload is None:
                    return

            response = ws_module.Response(code=HTTPStatus.OK)
            try:
                started = time.monotonic()
                result = self._event_handler.do_without_validation(payload)
                elapsed_ms = round((time.monotonic() - started) * 1000)
                header = headers.add()
                header.key = ws_module.HEADER_BIZ_RT
                header.value = str(elapsed_ms)
                if result is not None:
                    response.data = base64.b64encode(
                        ws_module.JSON.marshal(result).encode(ws_module.UTF_8)
                    )
            except Exception:
                logger.exception("Feishu card callback failed (message_id={})", message_id)
                response = ws_module.Response(code=HTTPStatus.INTERNAL_SERVER_ERROR)

            frame.payload = ws_module.JSON.marshal(response).encode(ws_module.UTF_8)
            await self._write_message(frame.SerializeToString())

    return CardAwareClient


# Message type display mapping
MSG_TYPE_MAP = {
    "image": "[image]",
    "audio": "[audio]",
    "file": "[file]",
    "sticker": "[sticker]",
}


def _extract_share_card_content(content_json: dict, msg_type: str) -> str:
    """Extract text representation from share cards and interactive messages."""
    parts = []

    if msg_type == "share_chat":
        parts.append(f"[shared chat: {content_json.get('chat_id', '')}]")
    elif msg_type == "share_user":
        parts.append(f"[shared user: {content_json.get('user_id', '')}]")
    elif msg_type == "interactive":
        parts.extend(_extract_interactive_content(content_json))
    elif msg_type == "share_calendar_event":
        parts.append(f"[shared calendar event: {content_json.get('event_key', '')}]")
    elif msg_type == "system":
        parts.append("[system message]")
    elif msg_type == "merge_forward":
        parts.append("[merged forward messages]")

    return "\n".join(parts) if parts else f"[{msg_type}]"


def _extract_interactive_content(content: dict) -> list[str]:
    """Recursively extract text and links from interactive card content."""
    parts = []

    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return [content] if content.strip() else []

    if not isinstance(content, dict):
        return parts

    if "title" in content:
        title = content["title"]
        if isinstance(title, dict):
            title_content = title.get("content", "") or title.get("text", "")
            if title_content:
                parts.append(f"title: {title_content}")
        elif isinstance(title, str):
            parts.append(f"title: {title}")

    for elements in (
        content.get("elements", []) if isinstance(content.get("elements"), list) else []
    ):
        for element in elements:
            parts.extend(_extract_element_content(element))

    card = content.get("card", {})
    if card:
        parts.extend(_extract_interactive_content(card))

    header = content.get("header", {})
    if header:
        header_title = header.get("title", {})
        if isinstance(header_title, dict):
            header_text = header_title.get("content", "") or header_title.get("text", "")
            if header_text:
                parts.append(f"title: {header_text}")

    return parts


def _extract_element_content(element: dict) -> list[str]:
    """Extract content from a single card element."""
    parts = []

    if not isinstance(element, dict):
        return parts

    tag = element.get("tag", "")

    if tag in ("markdown", "lark_md"):
        content = element.get("content", "")
        if content:
            parts.append(content)

    elif tag == "div":
        text = element.get("text", {})
        if isinstance(text, dict):
            text_content = text.get("content", "") or text.get("text", "")
            if text_content:
                parts.append(text_content)
        elif isinstance(text, str):
            parts.append(text)
        for field in element.get("fields", []):
            if isinstance(field, dict):
                field_text = field.get("text", {})
                if isinstance(field_text, dict):
                    c = field_text.get("content", "")
                    if c:
                        parts.append(c)

    elif tag == "a":
        href = element.get("href", "")
        text = element.get("text", "")
        if href:
            parts.append(f"link: {href}")
        if text:
            parts.append(text)

    elif tag == "button":
        text = element.get("text", {})
        if isinstance(text, dict):
            c = text.get("content", "")
            if c:
                parts.append(c)
        url = element.get("url", "") or element.get("multi_url", {}).get("url", "")
        if url:
            parts.append(f"link: {url}")

    elif tag == "img":
        alt = element.get("alt", {})
        parts.append(alt.get("content", "[image]") if isinstance(alt, dict) else "[image]")

    elif tag == "note":
        for ne in element.get("elements", []):
            parts.extend(_extract_element_content(ne))

    elif tag == "column_set":
        for col in element.get("columns", []):
            for ce in col.get("elements", []):
                parts.extend(_extract_element_content(ce))

    elif tag == "plain_text":
        content = element.get("content", "")
        if content:
            parts.append(content)

    else:
        for ne in element.get("elements", []):
            parts.extend(_extract_element_content(ne))

    return parts


def _extract_post_content(content_json: dict) -> tuple[str, list[str]]:
    """Extract text and image keys from Feishu post (rich text) message.

    Handles three payload shapes:
    - Direct:    {"title": "...", "content": [[...]]}
    - Localized: {"zh_cn": {"title": "...", "content": [...]}}
    - Wrapped:   {"post": {"zh_cn": {"title": "...", "content": [...]}}}
    """

    def _parse_block(block: dict) -> tuple[str | None, list[str]]:
        if not isinstance(block, dict) or not isinstance(block.get("content"), list):
            return None, []
        texts, images = [], []
        if title := block.get("title"):
            texts.append(title)
        for row in block["content"]:
            if not isinstance(row, list):
                continue
            for el in row:
                if not isinstance(el, dict):
                    continue
                tag = el.get("tag")
                if tag in ("text", "a"):
                    texts.append(el.get("text", ""))
                elif tag == "at":
                    texts.append(f"@{el.get('user_name', 'user')}")
                elif tag == "img" and (key := el.get("image_key")):
                    images.append(key)
        return (" ".join(texts).strip() or None), images

    # Unwrap optional {"post": ...} envelope
    root = content_json
    if isinstance(root, dict) and isinstance(root.get("post"), dict):
        root = root["post"]
    if not isinstance(root, dict):
        return "", []

    # Direct format
    if "content" in root:
        text, imgs = _parse_block(root)
        if text or imgs:
            return text or "", imgs

    # Localized: prefer known locales, then fall back to any dict child
    for key in ("zh_cn", "en_us", "ja_jp"):
        if key in root:
            text, imgs = _parse_block(root[key])
            if text or imgs:
                return text or "", imgs
    for val in root.values():
        if isinstance(val, dict):
            text, imgs = _parse_block(val)
            if text or imgs:
                return text or "", imgs

    return "", []


def _extract_post_text(content_json: dict) -> str:
    """Extract plain text from Feishu post (rich text) message content.

    Legacy wrapper for _extract_post_content, returns only text.
    """
    text, _ = _extract_post_content(content_json)
    return text


class FeishuConfig(DeliveryOverrides, StreamingSupport):
    """Feishu/Lark channel configuration using WebSocket long connection."""

    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    domain: Literal["feishu", "lark"] = "feishu"
    encrypt_key: str = ""
    verification_token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    react_emoji: str = "THUMBSUP"
    group_policy: Literal["open", "mention"] = "mention"


_STREAM_ELEMENT_ID = "streaming_md"


@dataclass
class _FeishuStreamBuf:
    """Per-chat streaming accumulator using CardKit streaming API."""

    text: str = ""
    card_id: str | None = None
    sequence: int = 0
    last_edit: float = 0.0
    stream_id: str | None = None
    reply_to_message_id: str | None = None


@dataclass
class _ModelPicker:
    """Server-owned model choices; card button values contain only an index."""

    sender_id: str
    providers: list[dict[str, Any]]
    options: list[dict[str, Any]]
    current: dict[str, str]
    created_at: float
    pending: bool = False
    pending_index: int | None = None


class FeishuChannel(BaseChannel):
    """
    Feishu/Lark channel using WebSocket long connection.

    Uses WebSocket to receive events - no public IP or webhook required.

    Requires:
    - App ID and App Secret from Feishu Open Platform
    - Bot capability enabled
    - Event subscription enabled (im.message.receive_v1)
    """

    name = "feishu"
    display_name = "Feishu"

    _STREAM_EDIT_INTERVAL = 0.5  # throttle between CardKit streaming updates
    _MAX_CONFIRMED_STREAMS = 1000
    _WORKING_REACTION_TTL = 60 * 60
    _MAX_WORKING_REACTIONS = 1000
    _REACTION_DELETE_RETRY_DELAYS = (0.15, 0.5)
    _REACTION_LATE_RETRY_DELAYS = (0, 5, 30, 120)
    _MODEL_PAGE_SIZE = 6
    _MODEL_PICKER_TTL = 60 * 60
    _MAX_MODEL_PICKERS = 100

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return FeishuConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = FeishuConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: FeishuConfig = config
        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: threading.Thread | None = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()  # Ordered dedup cache
        self._stream_bufs: dict[str, _FeishuStreamBuf] = {}
        self._confirmed_streams: OrderedDict[str, None] = OrderedDict()
        self._working_reactions: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._reaction_cleanup_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._reaction_expiry_tasks: dict[str, asyncio.Task[None]] = {}
        self._model_pickers: OrderedDict[str, _ModelPicker] = OrderedDict()
        self._model_picker_lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    @staticmethod
    def _stream_key(chat_id: str, metadata: dict[str, Any] | None = None) -> str:
        """Scope streaming buffers to the stream segment when available."""
        meta = metadata or {}
        return str(meta.get("_stream_id") or chat_id)

    def _confirm_stream_delivery(self, stream_key: str) -> None:
        self._confirmed_streams[stream_key] = None
        self._confirmed_streams.move_to_end(stream_key)
        while len(self._confirmed_streams) > self._MAX_CONFIRMED_STREAMS:
            self._confirmed_streams.popitem(last=False)

    def consume_stream_delivery(self, metadata: dict[str, Any]) -> bool:
        """Confirm the final card reached Feishu before suppressing plain text."""
        stream_id = str(metadata.get("_stream_id") or "")
        if stream_id and stream_id in self._confirmed_streams:
            self._confirmed_streams.pop(stream_id)
            return True
        return False

    @staticmethod
    def _register_optional_event(builder: Any, method_name: str, handler: Any) -> Any:
        """Register an event handler only when the SDK supports it."""
        method = getattr(builder, method_name, None)
        return method(handler) if callable(method) else builder

    async def start(self) -> None:
        """Start the Feishu bot with WebSocket long connection."""
        if not FEISHU_AVAILABLE:
            logger.error("Feishu SDK not installed. Run: pip install lark-oapi")
            self.set_setup_state(
                "unavailable",
                message="Required channel dependency is not installed on this server.",
            )
            return

        if not self.config.app_id or not self.config.app_secret:
            logger.error("Feishu app_id and app_secret not configured")
            self.set_setup_state(
                "action_required",
                message=(
                    "Required fields are missing. Complete the channel configuration "
                    "and save again."
                ),
            )
            return

        import lark_oapi as lark
        from lark_oapi.core.const import FEISHU_DOMAIN, LARK_DOMAIN

        ws_module = lark.ws.client

        self._running = True
        self._loop = asyncio.get_running_loop()
        sdk_domain = LARK_DOMAIN if self.config.domain == "lark" else FEISHU_DOMAIN

        # Create Lark client for sending messages
        self._client = (
            lark.Client.builder()
            .app_id(self.config.app_id)
            .app_secret(self.config.app_secret)
            .domain(sdk_domain)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
        builder = lark.EventDispatcherHandler.builder(
            self.config.encrypt_key or "",
            self.config.verification_token or "",
        ).register_p2_im_message_receive_v1(self._on_message_sync)
        builder = self._register_optional_event(
            builder, "register_p2_im_message_reaction_created_v1", self._on_reaction_created
        )
        builder = self._register_optional_event(
            builder, "register_p2_im_message_message_read_v1", self._on_message_read
        )
        builder = self._register_optional_event(
            builder,
            "register_p2_im_chat_access_event_bot_p2p_chat_entered_v1",
            self._on_bot_p2p_chat_entered,
        )
        builder = self._register_optional_event(
            builder, "register_p2_card_action_trigger", self._on_card_action_sync
        )
        event_handler = builder.build()

        # The supported SDK's WS client drops CARD frames before its callback
        # dispatcher runs. Route those frames while preserving the SDK's normal
        # EVENT path and response envelope.
        ws_client_cls = _card_aware_ws_client(lark.ws.Client, ws_module)
        ws_kwargs: dict[str, Any] = {
            "event_handler": event_handler,
            "log_level": lark.LogLevel.INFO,
            "domain": sdk_domain,
        }
        # extra_ua_tags was added after the minimum supported SDK version.
        if "extra_ua_tags" in inspect.signature(lark.ws.Client.__init__).parameters:
            ws_kwargs["extra_ua_tags"] = ["channel"]
        self._ws_client = ws_client_cls(
            self.config.app_id,
            self.config.app_secret,
            **ws_kwargs,
        )

        # Start WebSocket client in a separate thread with reconnect loop.
        # A dedicated event loop is created for this thread so that lark_oapi's
        # module-level `loop = asyncio.get_event_loop()` picks up an idle loop
        # instead of the already-running main asyncio loop, which would cause
        # "This event loop is already running" errors.
        def run_ws():
            import time

            import lark_oapi.ws.client as _lark_ws_client

            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            # Patch the module-level loop used by lark's ws Client.start()
            _lark_ws_client.loop = ws_loop
            try:
                while self._running:
                    try:
                        self.set_setup_state("connecting")
                        self._ws_client.start()
                    except Exception as e:
                        logger.warning("Feishu WebSocket error: {}", e)
                        self.set_setup_state(
                            "error",
                            message="Channel connection failed; the listener will retry.",
                        )
                    if self._running:
                        time.sleep(5)
            finally:
                ws_loop.close()

        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()

        logger.info("Feishu bot started with WebSocket long connection")
        logger.info("No public IP required - using WebSocket to receive events")
        self.set_setup_state("running")

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """
        Stop the Feishu bot.

        Notice: lark.ws.Client does not expose stop method， simply exiting the program will close the client.

        Reference: https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/ws/client.py#L86
        """
        self._running = False
        self._confirmed_streams.clear()
        cleanup_tasks = [
            *self._reaction_cleanup_tasks.values(),
            *self._reaction_expiry_tasks.values(),
        ]
        for task in cleanup_tasks:
            task.cancel()
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        self._reaction_cleanup_tasks.clear()
        self._reaction_expiry_tasks.clear()
        self._working_reactions.clear()
        with self._model_picker_lock:
            self._model_pickers.clear()
        logger.info("Feishu bot stopped")

    def _is_bot_mentioned(self, message: Any) -> bool:
        """Check if the bot is @mentioned in the message."""
        raw_content = message.content or ""
        if "@_all" in raw_content:
            return True

        for mention in getattr(message, "mentions", None) or []:
            mid = getattr(mention, "id", None)
            if not mid:
                continue
            # Bot mentions have no user_id (None or "") but a valid open_id
            if not getattr(mid, "user_id", None) and (
                getattr(mid, "open_id", None) or ""
            ).startswith("ou_"):
                return True
        return False

    def _is_group_message_for_bot(self, message: Any) -> bool:
        """Allow group messages when policy is open or bot is @mentioned."""
        if self.config.group_policy == "open":
            return True
        return self._is_bot_mentioned(message)

    def _add_reaction_sync(self, message_id: str, emoji_type: str) -> str | None:
        """Sync helper for adding reaction (runs in thread pool)."""
        from lark_oapi.api.im.v1 import (
            CreateMessageReactionRequest,
            CreateMessageReactionRequestBody,
            Emoji,
        )

        try:
            request = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                    .build()
                )
                .build()
            )

            response = self._client.im.v1.message_reaction.create(request)

            if not response.success():
                logger.warning(
                    "Failed to add reaction: code={}, msg={}", response.code, response.msg
                )
            else:
                logger.debug("Added {} reaction to message {}", emoji_type, message_id)
                reaction_id = getattr(getattr(response, "data", None), "reaction_id", None)
                return reaction_id if isinstance(reaction_id, str) and reaction_id else None
        except Exception as e:
            logger.warning("Error adding reaction: {}", e)
        return None

    def _prune_working_reactions(self) -> list[tuple[str, tuple[str, float]]]:
        """Bound receipts for turns that never produce a deliverable answer."""
        now = time.monotonic()
        expired: list[tuple[str, tuple[str, float]]] = []
        while self._working_reactions:
            _, (_, created_at) = next(iter(self._working_reactions.items()))
            if (
                len(self._working_reactions) <= self._MAX_WORKING_REACTIONS
                and now - created_at < self._WORKING_REACTION_TTL
            ):
                break
            message_id, receipt = self._working_reactions.popitem(last=False)
            expiry_task = self._reaction_expiry_tasks.pop(message_id, None)
            if expiry_task:
                expiry_task.cancel()
            expired.append((message_id, receipt))
        return expired

    def _remove_reaction_sync(self, message_id: str, reaction_id: str) -> bool:
        from lark_oapi.api.im.v1 import DeleteMessageReactionRequest

        try:
            request = (
                DeleteMessageReactionRequest.builder()
                .message_id(message_id)
                .reaction_id(reaction_id)
                .build()
            )
            response = self._client.im.v1.message_reaction.delete(request)
            if response.success():
                return True
            logger.warning(
                "Failed to remove Feishu working reaction: code={}, msg={}",
                response.code,
                response.msg,
            )
        except Exception as e:
            logger.warning("Error removing Feishu working reaction: {}", e)
        return False

    async def _delete_reaction(self, message_id: str, reaction_id: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._remove_reaction_sync, message_id, reaction_id)

    def _clear_reaction_receipt(self, message_id: str, receipt: tuple[str, float]) -> None:
        if self._working_reactions.get(message_id) != receipt:
            return
        self._working_reactions.pop(message_id, None)
        expiry_task = self._reaction_expiry_tasks.pop(message_id, None)
        if expiry_task and expiry_task is not asyncio.current_task():
            expiry_task.cancel()

    def _schedule_reaction_expiry(self, message_id: str, receipt: tuple[str, float]) -> None:
        async def expire() -> None:
            try:
                await asyncio.sleep(self._WORKING_REACTION_TTL)
                if self._working_reactions.get(message_id) == receipt:
                    await self._finish_reaction(message_id)
            finally:
                if self._reaction_expiry_tasks.get(message_id) is asyncio.current_task():
                    self._reaction_expiry_tasks.pop(message_id, None)

        self._reaction_expiry_tasks[message_id] = asyncio.create_task(expire())

    def _schedule_reaction_cleanup(self, message_id: str, receipt: tuple[str, float]) -> None:
        key = (message_id, receipt[0])
        if key in self._reaction_cleanup_tasks:
            return

        async def retry() -> None:
            try:
                for delay in self._REACTION_LATE_RETRY_DELAYS:
                    if delay:
                        await asyncio.sleep(delay)
                    if not self._client:
                        return
                    if await self._delete_reaction(*key):
                        self._clear_reaction_receipt(message_id, receipt)
                        return
            finally:
                self._reaction_cleanup_tasks.pop(key, None)

        self._reaction_cleanup_tasks[key] = asyncio.create_task(retry())

    async def _finish_reaction(self, message_id: str) -> None:
        receipt = self._working_reactions.get(message_id)
        if not receipt or not self._client:
            return
        reaction_id, _ = receipt
        for delay in (0, *self._REACTION_DELETE_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            if await self._delete_reaction(message_id, reaction_id):
                self._clear_reaction_receipt(message_id, receipt)
                return
        self._schedule_reaction_cleanup(message_id, receipt)

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """
        Add a reaction emoji to a message (non-blocking).

        Common emoji types: THUMBSUP, OK, EYES, DONE, OnIt, HEART
        """
        if not self._client:
            return

        loop = asyncio.get_running_loop()
        reaction_id = await loop.run_in_executor(
            None, self._add_reaction_sync, message_id, emoji_type
        )
        if reaction_id:
            previous = self._working_reactions.get(message_id)
            if previous:
                previous_expiry = self._reaction_expiry_tasks.pop(message_id, None)
                if previous_expiry:
                    previous_expiry.cancel()
                self._schedule_reaction_cleanup(message_id, previous)
            receipt = (reaction_id, time.monotonic())
            self._working_reactions[message_id] = receipt
            self._schedule_reaction_expiry(message_id, receipt)
            for old_message_id, old_receipt in self._prune_working_reactions():
                self._schedule_reaction_cleanup(old_message_id, old_receipt)

    # Regex to match markdown tables (header + separator + data rows)
    _TABLE_RE = re.compile(
        r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
        re.MULTILINE,
    )

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    _CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)

    @staticmethod
    def _parse_md_table(table_text: str) -> dict | None:
        """Parse a markdown table into a Feishu table element."""
        lines = [_line.strip() for _line in table_text.strip().split("\n") if _line.strip()]
        if len(lines) < 3:
            return None

        headers = split_markdown_table_row(lines[0])
        rows = [split_markdown_table_row(_line) for _line in lines[2:]]
        columns = [
            {"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
            for i, h in enumerate(headers)
        ]
        return {
            "tag": "table",
            "page_size": len(rows) + 1,
            "columns": columns,
            "rows": [
                {f"c{i}": r[i] if i < len(r) else "" for i in range(len(headers))} for r in rows
            ],
        }

    def _build_card_elements(self, content: str) -> list[dict]:
        """Split content into div/markdown + table elements for Feishu card."""
        elements, last_end = [], 0
        for m in self._TABLE_RE.finditer(content):
            before = content[last_end : m.start()]
            if before.strip():
                elements.extend(self._split_headings(before))
            elements.append(
                self._parse_md_table(m.group(1)) or {"tag": "markdown", "content": m.group(1)}
            )
            last_end = m.end()
        remaining = content[last_end:]
        if remaining.strip():
            elements.extend(self._split_headings(remaining))
        return elements or [{"tag": "markdown", "content": content}]

    @staticmethod
    def _split_elements_by_table_limit(
        elements: list[dict], max_tables: int = 1
    ) -> list[list[dict]]:
        """Split card elements into groups with at most *max_tables* table elements each.

        Feishu cards have a hard limit of one table per card (API error 11310).
        When the rendered content contains multiple markdown tables each table is
        placed in a separate card message so every table reaches the user.
        """
        if not elements:
            return [[]]
        groups: list[list[dict]] = []
        current: list[dict] = []
        table_count = 0
        for el in elements:
            if el.get("tag") == "table":
                if table_count >= max_tables:
                    if current:
                        groups.append(current)
                    current = []
                    table_count = 0
                current.append(el)
                table_count += 1
            else:
                current.append(el)
        if current:
            groups.append(current)
        return groups or [[]]

    def _split_headings(self, content: str) -> list[dict]:
        """Split content by headings, converting headings to div elements."""
        protected = content
        code_blocks: list[str] = []
        for m in self._CODE_BLOCK_RE.finditer(content):
            code_blocks.append(m.group(1))
            protected = protected.replace(m.group(1), f"\x00CODE{len(code_blocks) - 1}\x00", 1)

        elements: list[dict[str, Any]] = []
        last_end = 0
        for m in self._HEADING_RE.finditer(protected):
            before = protected[last_end : m.start()].strip()
            if before:
                elements.append({"tag": "markdown", "content": before})
            text = m.group(2).strip()
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{text}**",
                    },
                }
            )
            last_end = m.end()
        remaining = protected[last_end:].strip()
        if remaining:
            elements.append({"tag": "markdown", "content": remaining})

        for i, cb in enumerate(code_blocks):
            for el in elements:
                if el.get("tag") == "markdown":
                    el["content"] = el["content"].replace(f"\x00CODE{i}\x00", cb)

        return elements or [{"tag": "markdown", "content": content}]

    # ── Smart format detection ──────────────────────────────────────────
    # Patterns that indicate "complex" markdown needing card rendering
    _COMPLEX_MD_RE = re.compile(
        r"```"  # fenced code block
        r"|^\|.+\|.*\n\s*\|[-:\s|]+\|"  # markdown table (header + separator)
        r"|^#{1,6}\s+",  # headings
        re.MULTILINE,
    )

    # Simple markdown patterns (bold, italic, strikethrough)
    _SIMPLE_MD_RE = re.compile(
        r"\*\*.+?\*\*"  # **bold**
        r"|__.+?__"  # __bold__
        r"|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"  # *italic* (single *)
        r"|~~.+?~~",  # ~~strikethrough~~
        re.DOTALL,
    )

    # Markdown link: [text](url)
    _MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")

    # Unordered list items
    _LIST_RE = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)

    # Ordered list items
    _OLIST_RE = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)

    # Max length for plain text format
    _TEXT_MAX_LEN = 200

    # Max length for post (rich text) format; beyond this, use card
    _POST_MAX_LEN = 2000

    @classmethod
    def _detect_msg_format(cls, content: str) -> str:
        """Determine the optimal Feishu message format for *content*.

        Returns one of:
        - ``"text"``        – plain text, short and no markdown
        - ``"post"``        – rich text (links only, moderate length)
        - ``"interactive"`` – card with full markdown rendering
        """
        stripped = content.strip()

        # Complex markdown (code blocks, tables, headings) → always card
        if cls._COMPLEX_MD_RE.search(stripped):
            return "interactive"

        # Long content → card (better readability with card layout)
        if len(stripped) > cls._POST_MAX_LEN:
            return "interactive"

        # Has bold/italic/strikethrough → card (post format can't render these)
        if cls._SIMPLE_MD_RE.search(stripped):
            return "interactive"

        # Has list items → card (post format can't render list bullets well)
        if cls._LIST_RE.search(stripped) or cls._OLIST_RE.search(stripped):
            return "interactive"

        # Has links → post format (supports <a> tags)
        if cls._MD_LINK_RE.search(stripped):
            return "post"

        # Short plain text → text format
        if len(stripped) <= cls._TEXT_MAX_LEN:
            return "text"

        # Medium plain text without any formatting → post format
        return "post"

    @classmethod
    def _markdown_to_post(cls, content: str) -> str:
        """Convert markdown content to Feishu post message JSON.

        Handles links ``[text](url)`` as ``a`` tags; everything else as ``text`` tags.
        Each line becomes a paragraph (row) in the post body.
        """
        lines = content.strip().split("\n")
        paragraphs: list[list[dict]] = []

        for line in lines:
            elements: list[dict] = []
            last_end = 0

            for m in cls._MD_LINK_RE.finditer(line):
                # Text before this link
                before = line[last_end : m.start()]
                if before:
                    elements.append({"tag": "text", "text": before})
                elements.append(
                    {
                        "tag": "a",
                        "text": m.group(1),
                        "href": m.group(2),
                    }
                )
                last_end = m.end()

            # Remaining text after last link
            remaining = line[last_end:]
            if remaining:
                elements.append({"tag": "text", "text": remaining})

            # Empty line → empty paragraph for spacing
            if not elements:
                elements.append({"tag": "text", "text": ""})

            paragraphs.append(elements)

        post_body = {
            "zh_cn": {
                "content": paragraphs,
            }
        }
        return json.dumps(post_body, ensure_ascii=False)

    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"}
    _AUDIO_EXTS = {".opus"}
    _VIDEO_EXTS = {".mp4", ".mov", ".avi"}
    _FILE_TYPE_MAP = {
        ".opus": "opus",
        ".mp4": "mp4",
        ".pdf": "pdf",
        ".doc": "doc",
        ".docx": "doc",
        ".xls": "xls",
        ".xlsx": "xls",
        ".ppt": "ppt",
        ".pptx": "ppt",
    }

    def _upload_image_sync(self, file_path: str) -> str | None:
        """Upload an image to Feishu and return the image_key."""
        from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

        try:
            with open(file_path, "rb") as f:
                request = (
                    CreateImageRequest.builder()
                    .request_body(
                        CreateImageRequestBody.builder().image_type("message").image(f).build()
                    )
                    .build()
                )
                response = self._client.im.v1.image.create(request)
                if response.success():
                    image_key = response.data.image_key
                    logger.debug("Uploaded image {}: {}", os.path.basename(file_path), image_key)
                    return image_key
                else:
                    logger.error(
                        "Failed to upload image: code={}, msg={}", response.code, response.msg
                    )
                    return None
        except Exception as e:
            logger.error("Error uploading image {}: {}", file_path, e)
            return None

    def _upload_file_sync(self, file_path: str) -> str | None:
        """Upload a file to Feishu and return the file_key."""
        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody

        ext = os.path.splitext(file_path)[1].lower()
        file_type = self._FILE_TYPE_MAP.get(ext, "stream")
        file_name = os.path.basename(file_path)
        try:
            with open(file_path, "rb") as f:
                request = (
                    CreateFileRequest.builder()
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(file_name)
                        .file(f)
                        .build()
                    )
                    .build()
                )
                response = self._client.im.v1.file.create(request)
                if response.success():
                    file_key = response.data.file_key
                    logger.debug("Uploaded file {}: {}", file_name, file_key)
                    return file_key
                else:
                    logger.error(
                        "Failed to upload file: code={}, msg={}", response.code, response.msg
                    )
                    return None
        except Exception as e:
            logger.error("Error uploading file {}: {}", file_path, e)
            return None

    def _download_image_sync(
        self, message_id: str, image_key: str
    ) -> tuple[bytes | None, str | None]:
        """Download an image from Feishu message by message_id and image_key."""
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(image_key)
                .type("image")
                .build()
            )
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                # GetMessageResourceRequest returns BytesIO, need to read bytes
                if hasattr(file_data, "read"):
                    file_data = file_data.read()
                return file_data, response.file_name
            else:
                logger.error(
                    "Failed to download image: code={}, msg={}", response.code, response.msg
                )
                return None, None
        except Exception as e:
            logger.error("Error downloading image {}: {}", image_key, e)
            return None, None

    def _download_file_sync(
        self, message_id: str, file_key: str, resource_type: str = "file"
    ) -> tuple[bytes | None, str | None]:
        """Download a file/audio/media from a Feishu message by message_id and file_key."""
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        # Feishu API only accepts 'image' or 'file' as type parameter
        # Convert 'audio' to 'file' for API compatibility
        if resource_type == "audio":
            resource_type = "file"

        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type(resource_type)
                .build()
            )
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                if hasattr(file_data, "read"):
                    file_data = file_data.read()
                return file_data, response.file_name
            else:
                logger.error(
                    "Failed to download {}: code={}, msg={}",
                    resource_type,
                    response.code,
                    response.msg,
                )
                return None, None
        except Exception:
            logger.exception("Error downloading {} {}", resource_type, file_key)
            return None, None

    async def _download_and_save_media(
        self, msg_type: str, content_json: dict, message_id: str | None = None
    ) -> tuple[str | None, str]:
        """
        Download media from Feishu and save to local disk.

        Returns:
            (file_path, content_text) - file_path is None if download failed
        """
        loop = asyncio.get_running_loop()
        media_dir = self.media_dir()

        data, filename = None, None

        if msg_type == "image":
            image_key = content_json.get("image_key")
            if image_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_image_sync, message_id, image_key
                )
                if not filename:
                    filename = f"{image_key[:16]}.jpg"

        elif msg_type in ("audio", "file", "media"):
            file_key = content_json.get("file_key")
            if file_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_file_sync, message_id, file_key, msg_type
                )
                if not filename:
                    filename = file_key[:16]
                if msg_type == "audio" and not filename.endswith(".opus"):
                    filename = f"{filename}.opus"

        if data and filename:
            file_path = media_dir / filename
            file_path.write_bytes(data)
            logger.debug("Downloaded {} to {}", msg_type, file_path)
            return str(file_path), f"[{msg_type}: {filename}]"

        return None, f"[{msg_type}: download failed]"

    def _send_message_sync(
        self,
        receive_id_type: str,
        receive_id: str,
        msg_type: str,
        content: str,
        reply_to_message_id: str | None = None,
    ) -> bool:
        """Send a message as a real Feishu reply when its source is known."""
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
            ReplyMessageRequest,
            ReplyMessageRequestBody,
        )

        try:
            if reply_to_message_id:
                request = (
                    ReplyMessageRequest.builder()
                    .message_id(reply_to_message_id)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .msg_type(msg_type)
                        .content(content)
                        .reply_in_thread(True)
                        .build()
                    )
                    .build()
                )
                response = self._client.im.v1.message.reply(request)
                if response.success():
                    logger.debug(
                        "Feishu {} reply sent to {} (message_id={})",
                        msg_type,
                        receive_id,
                        reply_to_message_id,
                    )
                    return True
                # A rejected reply may be an expired source message or an
                # unsupported type in a thread. Preserve the answer via the
                # original create path; a transport exception is different,
                # because its send outcome is unknown and a fallback may duplicate.
                logger.warning(
                    "Feishu {} reply rejected (message_id={}, code={}, msg={}); "
                    "falling back to a standalone message",
                    msg_type,
                    reply_to_message_id,
                    response.code,
                    response.msg,
                )
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.message.create(request)
            if not response.success():
                logger.error(
                    "Failed to send Feishu {} message: code={}, msg={}, log_id={}",
                    msg_type,
                    response.code,
                    response.msg,
                    response.get_log_id(),
                )
                return False
            logger.debug("Feishu {} message sent to {}", msg_type, receive_id)
            return True
        except Exception as e:
            logger.error("Error sending Feishu {} message: {}", msg_type, e)
            return False

    # ── CardKit streaming (send_delta) ───────────────────────────────

    def _create_streaming_card_sync(
        self, receive_id_type: str, chat_id: str, reply_to_message_id: str | None = None
    ) -> str | None:
        """Create a CardKit streaming card, send it to chat, return card_id."""
        from lark_oapi.api.cardkit.v1 import CreateCardRequest, CreateCardRequestBody

        card_json = {
            "schema": "2.0",
            "config": {"wide_screen_mode": True, "update_multi": True, "streaming_mode": True},
            "body": {
                "elements": [{"tag": "markdown", "content": "", "element_id": _STREAM_ELEMENT_ID}]
            },
        }
        try:
            request = (
                CreateCardRequest.builder()
                .request_body(
                    CreateCardRequestBody.builder()
                    .type("card_json")
                    .data(json.dumps(card_json, ensure_ascii=False))
                    .build()
                )
                .build()
            )
            response = self._client.cardkit.v1.card.create(request)
            if not response.success():
                logger.warning(
                    "Failed to create Feishu streaming card: code={}, msg={}",
                    response.code,
                    response.msg,
                )
                return None
            card_id = getattr(response.data, "card_id", None)
            if card_id:
                card_content = json.dumps(
                    {"type": "card", "data": {"card_id": card_id}}, ensure_ascii=False
                )
                if self._send_message_sync(
                    receive_id_type, chat_id, "interactive", card_content, reply_to_message_id
                ):
                    return card_id
                logger.warning(
                    "Created Feishu streaming card {} but failed to send it to {}",
                    card_id,
                    chat_id,
                )
            return None
        except Exception as e:
            logger.warning("Error creating Feishu streaming card: {}", e)
            return None

    def _stream_update_text_sync(self, card_id: str, content: str, sequence: int) -> bool:
        """Stream-update the markdown element on a CardKit card (typewriter effect)."""
        from lark_oapi.api.cardkit.v1 import (
            ContentCardElementRequest,
            ContentCardElementRequestBody,
        )

        try:
            request = (
                ContentCardElementRequest.builder()
                .card_id(card_id)
                .element_id(_STREAM_ELEMENT_ID)
                .request_body(
                    ContentCardElementRequestBody.builder()
                    .content(content)
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = self._client.cardkit.v1.card_element.content(request)
            if not response.success():
                logger.warning(
                    "Failed to stream-update Feishu card {}: code={}, msg={}",
                    card_id,
                    response.code,
                    response.msg,
                )
                return False
            return True
        except Exception as e:
            logger.warning("Error stream-updating Feishu card {}: {}", card_id, e)
            return False

    def _close_streaming_mode_sync(self, card_id: str, sequence: int) -> bool:
        """Turn off CardKit streaming_mode after the final content update.

        Per Feishu docs, streaming cards keep a generating-style summary in
        the session list until streaming_mode is set to false via card
        settings. Sequence must strictly exceed the previous card operation.
        """
        from lark_oapi.api.cardkit.v1 import SettingsCardRequest, SettingsCardRequestBody

        settings_payload = json.dumps({"config": {"streaming_mode": False}}, ensure_ascii=False)
        try:
            request = (
                SettingsCardRequest.builder()
                .card_id(card_id)
                .request_body(
                    SettingsCardRequestBody.builder()
                    .settings(settings_payload)
                    .sequence(sequence)
                    .uuid(str(uuid.uuid4()))
                    .build()
                )
                .build()
            )
            response = self._client.cardkit.v1.card.settings(request)
            if not response.success():
                logger.warning(
                    "Failed to close streaming on Feishu card {}: code={}, msg={}",
                    card_id,
                    response.code,
                    response.msg,
                )
                return False
            return True
        except Exception as e:
            logger.warning("Error closing streaming on Feishu card {}: {}", card_id, e)
            return False

    async def send_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Progressive streaming via CardKit: create card on first delta, stream-update after.

        Buffers are keyed by ``_stream_id`` so each loop round gets its own
        card (narration rounds freeze in place; the finish round becomes the
        reply). On ``_stream_end`` the final text lands via a last stream
        update, then streaming_mode closes; if that fails (e.g. Feishu timed
        the card out) the text falls back to a regular interactive card.
        """
        if not self._client:
            return
        meta = metadata or {}
        stream_key = self._stream_key(chat_id, meta)
        loop = asyncio.get_running_loop()
        rid_type = "chat_id" if chat_id.startswith("oc_") else "open_id"
        inbound_message_id = str(meta.get("message_id") or "").strip() or None

        if meta.get("_stream_end"):
            buf = self._stream_bufs.pop(stream_key, None)
            if not buf or not buf.text.strip():
                return
            reply_to_message_id = buf.reply_to_message_id or inbound_message_id
            if buf.card_id:
                buf.sequence += 1
                ok = await loop.run_in_executor(
                    None,
                    self._stream_update_text_sync,
                    buf.card_id,
                    buf.text,
                    buf.sequence,
                )
                if ok:
                    buf.sequence += 1
                    closed = await loop.run_in_executor(
                        None,
                        self._close_streaming_mode_sync,
                        buf.card_id,
                        buf.sequence,
                    )
                    if not closed:
                        # The final content update already succeeded. A new
                        # card here would duplicate an answer the user can see.
                        logger.warning(
                            "Feishu streaming card {} displayed its final text but could not close",
                            buf.card_id,
                        )
                    if meta.get("_stream_final"):
                        self._confirm_stream_delivery(stream_key)
                        if reply_to_message_id:
                            await self._finish_reaction(reply_to_message_id)
                    return
                logger.warning(
                    "Feishu streaming card {} final update failed, falling back to regular card",
                    buf.card_id,
                )
            delivered = True
            for chunk in self._split_elements_by_table_limit(self._build_card_elements(buf.text)):
                card = json.dumps(
                    {"config": {"wide_screen_mode": True}, "elements": chunk},
                    ensure_ascii=False,
                )
                sent = await loop.run_in_executor(
                    None,
                    self._send_message_sync,
                    rid_type,
                    chat_id,
                    "interactive",
                    card,
                    reply_to_message_id,
                )
                delivered = delivered and sent
            if delivered and meta.get("_stream_final"):
                self._confirm_stream_delivery(stream_key)
                if reply_to_message_id:
                    await self._finish_reaction(reply_to_message_id)
            return

        buf = self._stream_bufs.get(stream_key)
        if buf is None:
            buf = _FeishuStreamBuf(
                stream_id=meta.get("_stream_id"),
                reply_to_message_id=inbound_message_id,
            )
            self._stream_bufs[stream_key] = buf
        buf.text += delta
        if not buf.text.strip():
            return

        now = time.monotonic()
        if buf.card_id is None:
            card_id = await loop.run_in_executor(
                None,
                self._create_streaming_card_sync,
                rid_type,
                chat_id,
                buf.reply_to_message_id,
            )
            if card_id:
                buf.card_id = card_id
                buf.sequence = 1
                await loop.run_in_executor(
                    None, self._stream_update_text_sync, card_id, buf.text, 1
                )
                buf.last_edit = now
        elif (now - buf.last_edit) >= self._STREAM_EDIT_INTERVAL:
            buf.sequence += 1
            await loop.run_in_executor(
                None, self._stream_update_text_sync, buf.card_id, buf.text, buf.sequence
            )
            buf.last_edit = now

    def _prune_model_pickers(self) -> None:
        """Called while the picker lock is held."""
        now = time.monotonic()
        for picker_id, picker in list(self._model_pickers.items()):
            if now - picker.created_at >= self._MODEL_PICKER_TTL:
                del self._model_pickers[picker_id]
        while len(self._model_pickers) > self._MAX_MODEL_PICKERS:
            self._model_pickers.popitem(last=False)

    @staticmethod
    def _model_label(option: dict[str, Any]) -> str:
        provider = str(option.get("provider_label") or option.get("profile_name") or "LLM")
        model = str(option.get("model_name") or option.get("model") or "model")
        return f"{provider} · {model}"

    @staticmethod
    def _provider_label(provider: dict[str, Any]) -> str:
        return str(
            provider.get("profile_name")
            or provider.get("provider_label")
            or provider.get("profile_id")
            or "LLM"
        )

    @staticmethod
    def _provider_option_indices(picker: _ModelPicker, provider_index: int) -> list[int]:
        profile_id = picker.providers[provider_index]["profile_id"]
        return [
            index
            for index, option in enumerate(picker.options)
            if option.get("profile_id") == profile_id
        ]

    def _provider_picker_card(self, picker_id: str, picker: _ModelPicker) -> dict[str, Any]:
        elements: list[dict[str, Any]] = [
            {"tag": "div", "text": {"tag": "plain_text", "content": "Choose a provider"}}
        ]
        for index, provider in enumerate(picker.providers):
            current = picker.current.get("profile_id") == provider.get("profile_id")
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": f"{'✓ ' if current else ''}{self._provider_label(provider)}"[
                                    :90
                                ],
                            },
                            "type": "primary" if current else "default",
                            "value": {
                                "picker_id": picker_id,
                                "action": "pick_provider",
                                "index": index,
                            },
                        }
                    ],
                }
            )
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "Switch model"}},
            "elements": elements,
        }

    def _model_picker_card(
        self,
        picker_id: str,
        picker: _ModelPicker,
        provider_index: int,
        page: int,
        *,
        status: str = "",
    ) -> dict[str, Any]:
        option_indices = self._provider_option_indices(picker, provider_index)
        total_pages = max(
            1, (len(option_indices) + self._MODEL_PAGE_SIZE - 1) // self._MODEL_PAGE_SIZE
        )
        page = max(0, min(page, total_pages - 1))
        start = page * self._MODEL_PAGE_SIZE
        provider = picker.providers[provider_index]
        name_counts: dict[str, int] = {}
        for index in option_indices:
            option = picker.options[index]
            name = str(option.get("model_name") or option.get("model") or "model").casefold()
            name_counts[name] = name_counts.get(name, 0) + 1
        elements: list[dict[str, Any]] = []
        if status:
            elements.append({"tag": "div", "text": {"tag": "plain_text", "content": status}})
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "plain_text",
                    "content": (
                        f"{self._provider_label(provider)} · Choose a model · "
                        f"Page {page + 1} of {total_pages}"
                    ),
                },
            }
        )
        for local_index, index in enumerate(
            option_indices[start : start + self._MODEL_PAGE_SIZE], start=start
        ):
            option = picker.options[index]
            current = picker.current.get("profile_id") == option.get(
                "profile_id"
            ) and picker.current.get("model_id") == option.get("model_id")
            model_name = str(option.get("model_name") or option.get("model") or "model")
            if name_counts[model_name.casefold()] > 1:
                model_name += f" ({option['model']})"
            label = f"{'✓ ' if current else ''}{local_index + 1}. {model_name}"
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": label[:90]},
                            "type": "primary" if current else "default",
                            "value": {
                                "picker_id": picker_id,
                                "action": "select",
                                "provider_index": provider_index,
                                "index": index,
                            },
                        }
                    ],
                }
            )
        navigation = []
        for label, target in (("◀ Previous", page - 1), ("Next ▶", page + 1)):
            if 0 <= target < total_pages:
                navigation.append(
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": label},
                        "type": "default",
                        "value": {
                            "picker_id": picker_id,
                            "action": "page",
                            "provider_index": provider_index,
                            "page": target,
                        },
                    }
                )
        navigation.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "◀ Providers"},
                "type": "default",
                "value": {"picker_id": picker_id, "action": "providers"},
            }
        )
        elements.append({"tag": "action", "actions": navigation})
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "Switch model"}},
            "elements": elements,
        }

    @staticmethod
    def _model_status_card(content: str) -> dict[str, Any]:
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "Switch model"}},
            "elements": [{"tag": "div", "text": {"tag": "plain_text", "content": content}}],
        }

    def _patch_model_card_sync(self, message_id: str, card: dict[str, Any]) -> bool:
        """Replace the clicked card after the command finishes."""
        from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

        try:
            request = (
                PatchMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    PatchMessageRequestBody.builder()
                    .content(json.dumps(card, ensure_ascii=False))
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.message.patch(request)
            if response.success():
                return True
            logger.warning(
                "Failed to patch Feishu model picker {}: code={}, msg={}",
                message_id,
                response.code,
                response.msg,
            )
        except Exception as exc:
            logger.warning("Error patching Feishu model picker {}: {}", message_id, exc)
        return False

    async def _queue_model_choice(
        self,
        *,
        sender_id: str,
        message_id: str,
        picker_id: str,
        option: dict[str, Any],
    ) -> None:
        """Enter the normal Partner command runner after the callback has returned."""
        command = (
            "/model "
            f"{shlex.quote(str(option['profile_id']))} "
            f"{shlex.quote(str(option['model_id']))}"
        )
        await self._handle_message(
            sender_id=sender_id,
            chat_id=sender_id,
            content=command,
            metadata={
                "chat_type": "p2p",
                "_feishu_model_picker_message_id": message_id,
                "_feishu_model_picker_id": picker_id,
            },
        )

    def _on_card_action_sync(self, data: Any) -> Any:
        """Return page/status cards within Feishu's callback deadline."""
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            CallBackToast,
            P2CardActionTriggerResponse,
        )

        def card_response(card: dict[str, Any]) -> Any:
            response = P2CardActionTriggerResponse()
            response.card = CallBackCard()
            response.card.type = "raw"
            response.card.data = card
            return response

        def error_response(message: str) -> Any:
            response = P2CardActionTriggerResponse()
            response.toast = CallBackToast()
            response.toast.type = "error"
            response.toast.content = message
            return response

        event = getattr(data, "event", None)
        value = getattr(getattr(event, "action", None), "value", None)
        operator = getattr(event, "operator", None)
        context = getattr(event, "context", None)
        if not isinstance(value, dict):
            return error_response("Invalid model picker action.")
        picker_id = value.get("picker_id")
        sender_id = str(getattr(operator, "open_id", "") or "")
        message_id = str(getattr(context, "open_message_id", "") or "")
        if not isinstance(picker_id, str) or not sender_id or not message_id:
            return error_response("Invalid model picker action.")
        with self._model_picker_lock:
            self._prune_model_pickers()
            picker = self._model_pickers.get(picker_id)
            if picker is None or picker.sender_id != sender_id or not self.is_allowed(sender_id):
                return error_response("This model picker expired. Send /model again.")
            if picker.pending:
                return error_response("A model switch is already in progress.")
            action = value.get("action")
            if action == "providers":
                return card_response(self._provider_picker_card(picker_id, picker))
            if action == "pick_provider":
                provider_index = value.get("index")
                if (
                    type(provider_index) is not int
                    or not 0 <= provider_index < len(picker.providers)
                    or not self._provider_option_indices(picker, provider_index)
                ):
                    return error_response("Invalid model provider.")
                return card_response(self._model_picker_card(picker_id, picker, provider_index, 0))
            provider_index = value.get("provider_index")
            if type(provider_index) is not int or not 0 <= provider_index < len(picker.providers):
                return error_response("Invalid model provider.")
            option_indices = self._provider_option_indices(picker, provider_index)
            if action == "page":
                page = value.get("page")
                if type(page) is not int or not 0 <= page * self._MODEL_PAGE_SIZE < len(
                    option_indices
                ):
                    return error_response("Invalid model picker page.")
                return card_response(
                    self._model_picker_card(picker_id, picker, provider_index, page)
                )
            if action != "select":
                return error_response("Invalid model picker action.")
            index = value.get("index")
            if type(index) is not int or index not in option_indices:
                return error_response("Invalid model choice.")
            loop = self._loop
            if loop is None or not loop.is_running():
                return error_response("The bot is reconnecting. Send /model again.")
            option = picker.options[index]
            current = next(
                (
                    row
                    for row in picker.options
                    if row.get("profile_id") == picker.current.get("profile_id")
                    and row.get("model_id") == picker.current.get("model_id")
                ),
                None,
            )
            previous = self._model_label(current) if current else "default"
            pending_page = option_indices.index(index) // self._MODEL_PAGE_SIZE
            pending_card = self._model_picker_card(
                picker_id,
                picker,
                provider_index,
                pending_page,
                status=f"⏳ Switching model: {previous} → {self._model_label(option)}…",
            )
            picker.pending = True
            picker.pending_index = index
            try:
                queued = asyncio.run_coroutine_threadsafe(
                    self._queue_model_choice(
                        sender_id=sender_id,
                        message_id=message_id,
                        picker_id=picker_id,
                        option=option,
                    ),
                    loop,
                )
            except RuntimeError:
                picker.pending = False
                picker.pending_index = None
                return error_response("The bot is reconnecting. Send /model again.")

            def release_failed_queue(future: Any) -> None:
                if not future.cancelled() and future.exception() is None:
                    return
                with self._model_picker_lock:
                    live = self._model_pickers.get(picker_id)
                    if live is picker and live.pending_index == index:
                        live.pending = False
                        live.pending_index = None

        # A completed future runs its callback immediately in this thread.
        # Register it after releasing the picker lock so a fast queue failure
        # can clear the pending state without deadlocking the card callback.
        queued.add_done_callback(release_failed_queue)
        return card_response(pending_card)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Feishu, including media (images/files) if present."""
        if not self._client:
            logger.warning("Feishu client not initialized")
            return

        try:
            receive_id_type = "chat_id" if msg.chat_id.startswith("oc_") else "open_id"
            loop = asyncio.get_running_loop()
            metadata = msg.metadata or {}
            origin_message_id = str(metadata.get("message_id") or "").strip() or None
            reply_to_message_id = str(msg.reply_to or origin_message_id or "").strip() or None

            picker_message_id = str(metadata.get("_feishu_model_picker_message_id") or "")
            if picker_message_id:
                completed = bool(metadata.get("_feishu_model_switch_success"))
                content = msg.content if completed else f"⚠️ {msg.content}"
                card = self._model_status_card(content)
                picker_id = str(metadata.get("_feishu_model_picker_id") or "")
                with self._model_picker_lock:
                    picker = self._model_pickers.get(picker_id)
                    if (
                        picker is not None
                        and picker.sender_id == msg.chat_id
                        and picker.pending_index is not None
                    ):
                        index = picker.pending_index
                        option = picker.options[index]
                        if completed:
                            picker.current = {
                                "profile_id": str(option["profile_id"]),
                                "model_id": str(option["model_id"]),
                            }
                        picker.pending = False
                        picker.pending_index = None
                        provider_index = next(
                            (
                                i
                                for i, provider in enumerate(picker.providers)
                                if provider["profile_id"] == option["profile_id"]
                            ),
                            None,
                        )
                        if provider_index is not None:
                            option_indices = self._provider_option_indices(picker, provider_index)
                            page = option_indices.index(index) // self._MODEL_PAGE_SIZE
                            card = self._model_picker_card(
                                picker_id, picker, provider_index, page, status=content
                            )
                patched = await loop.run_in_executor(
                    None, self._patch_model_card_sync, picker_message_id, card
                )
                if not patched:
                    await loop.run_in_executor(
                        None,
                        self._send_message_sync,
                        "open_id",
                        msg.chat_id,
                        "text",
                        json.dumps({"text": content}, ensure_ascii=False),
                    )
                return

            raw_options = metadata.get("_feishu_model_options")
            picker_options = (
                [
                    option
                    for option in raw_options
                    if isinstance(option, dict)
                    and option.get("profile_id")
                    and option.get("model_id")
                    and option.get("model")
                ]
                if isinstance(raw_options, list)
                else []
            )
            if picker_options and msg.chat_id.startswith("ou_"):
                listed_providers = {
                    str(row.get("profile_id")): row
                    for row in (metadata.get("_feishu_model_providers") or [])
                    if isinstance(row, dict) and row.get("profile_id")
                }
                providers: list[dict[str, Any]] = []
                seen_profiles: set[str] = set()
                for option in picker_options:
                    profile_id = str(option["profile_id"])
                    if profile_id in seen_profiles:
                        continue
                    seen_profiles.add(profile_id)
                    listed = listed_providers.get(profile_id) or {}
                    providers.append(
                        {
                            "profile_id": profile_id,
                            "profile_name": listed.get("profile_name")
                            or option.get("profile_name"),
                            "provider_label": listed.get("provider_label")
                            or option.get("provider_label"),
                        }
                    )
                picker_id = uuid.uuid4().hex[:16]
                picker = _ModelPicker(
                    sender_id=msg.chat_id,
                    providers=providers,
                    options=picker_options,
                    current=dict(metadata.get("_feishu_model_current") or {}),
                    created_at=time.monotonic(),
                )
                with self._model_picker_lock:
                    self._model_pickers[picker_id] = picker
                    self._prune_model_pickers()
                sent = await loop.run_in_executor(
                    None,
                    self._send_message_sync,
                    "open_id",
                    msg.chat_id,
                    "interactive",
                    json.dumps(self._provider_picker_card(picker_id, picker), ensure_ascii=False),
                    reply_to_message_id,
                )
                if sent:
                    if origin_message_id:
                        await self._finish_reaction(origin_message_id)
                    return
                with self._model_picker_lock:
                    self._model_pickers.pop(picker_id, None)

            delivered = True
            sent_any = False

            async def send_payload(msg_type: str, content: str) -> None:
                nonlocal delivered, sent_any
                sent_any = True
                sent = await loop.run_in_executor(
                    None,
                    self._send_message_sync,
                    receive_id_type,
                    msg.chat_id,
                    msg_type,
                    content,
                    reply_to_message_id,
                )
                delivered = delivered and sent

            for file_path in msg.media:
                if not os.path.isfile(file_path):
                    logger.warning("Media file not found: {}", file_path)
                    delivered = False
                    continue
                ext = os.path.splitext(file_path)[1].lower()
                if ext in self._IMAGE_EXTS:
                    key = await loop.run_in_executor(None, self._upload_image_sync, file_path)
                    if key:
                        await send_payload(
                            "image",
                            json.dumps({"image_key": key}, ensure_ascii=False),
                        )
                    else:
                        delivered = False
                else:
                    key = await loop.run_in_executor(None, self._upload_file_sync, file_path)
                    if key:
                        # Use msg_type "media" for audio/video so users can play inline;
                        # "file" for everything else (documents, archives, etc.)
                        if ext in self._AUDIO_EXTS or ext in self._VIDEO_EXTS:
                            media_type = "media"
                        else:
                            media_type = "file"
                        await send_payload(
                            media_type,
                            json.dumps({"file_key": key}, ensure_ascii=False),
                        )
                    else:
                        delivered = False

            if msg.content and msg.content.strip():
                fmt = self._detect_msg_format(msg.content)

                if fmt == "text":
                    # Short plain text – send as simple text message
                    text_body = json.dumps({"text": msg.content.strip()}, ensure_ascii=False)
                    await send_payload("text", text_body)

                elif fmt == "post":
                    # Medium content with links – send as rich-text post
                    post_body = self._markdown_to_post(msg.content)
                    await send_payload("post", post_body)

                else:
                    # Complex / long content – send as interactive card
                    elements = self._build_card_elements(msg.content)
                    for chunk in self._split_elements_by_table_limit(elements):
                        card = {"config": {"wide_screen_mode": True}, "elements": chunk}
                        await send_payload(
                            "interactive",
                            json.dumps(card, ensure_ascii=False),
                        )

            if sent_any and delivered and origin_message_id and not metadata.get("_progress"):
                await self._finish_reaction(origin_message_id)

        except Exception as e:
            logger.error("Error sending Feishu message: {}", e)

    def _on_message_sync(self, data: Any) -> None:
        """
        Sync handler for incoming messages (called from WebSocket thread).
        Schedules async handling in the main event loop.
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)

    async def _on_message(self, data: Any) -> None:
        """Handle incoming message from Feishu."""
        try:
            event = data.event
            message = event.message
            sender = event.sender

            # Deduplication check
            message_id = message.message_id
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None

            # Trim cache
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # Skip bot messages
            if sender.sender_type == "bot":
                return

            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type
            msg_type = message.message_type

            if chat_type == "group" and not self._is_group_message_for_bot(message):
                logger.debug("Feishu: skipping group message (not mentioned)")
                return
            if not self.is_allowed(sender_id):
                return

            # Parse content
            content_parts = []
            media_paths = []

            try:
                content_json = json.loads(message.content) if message.content else {}
            except json.JSONDecodeError:
                content_json = {}

            if msg_type == "text":
                text = content_json.get("text", "")
                if text:
                    content_parts.append(text)

            elif msg_type == "post":
                text, image_keys = _extract_post_content(content_json)
                if text:
                    content_parts.append(text)
                # Download images embedded in post
                for img_key in image_keys:
                    file_path, content_text = await self._download_and_save_media(
                        "image", {"image_key": img_key}, message_id
                    )
                    if file_path:
                        media_paths.append(file_path)
                    content_parts.append(content_text)

            elif msg_type in ("image", "audio", "file", "media"):
                file_path, content_text = await self._download_and_save_media(
                    msg_type, content_json, message_id
                )
                if file_path:
                    media_paths.append(file_path)

                if msg_type == "audio" and file_path:
                    transcription = await self.transcribe_audio(file_path)
                    if transcription:
                        content_text = f"[transcription: {transcription}]"

                content_parts.append(content_text)

            elif msg_type in (
                "share_chat",
                "share_user",
                "interactive",
                "share_calendar_event",
                "system",
                "merge_forward",
            ):
                # Handle share cards and interactive messages
                text = _extract_share_card_content(content_json, msg_type)
                if text:
                    content_parts.append(text)

            else:
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            content = "\n".join(content_parts) if content_parts else ""

            if not content and not media_paths:
                return

            # Only acknowledge a message that can reach the partner runner;
            # unsupported empty events have no final reply to clear the badge.
            await self._add_reaction(message_id, self.config.react_emoji)

            # Forward to message bus
            reply_to = chat_id if chat_type == "group" else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                media=media_paths,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                },
            )

        except Exception as e:
            logger.error("Error processing Feishu message: {}", e)

    def _on_reaction_created(self, data: Any) -> None:
        """Ignore reaction events so they do not generate SDK noise."""
        pass

    def _on_message_read(self, data: Any) -> None:
        """Ignore read events so they do not generate SDK noise."""
        pass

    def _on_bot_p2p_chat_entered(self, data: Any) -> None:
        """Ignore p2p-enter events when a user opens a bot chat."""
        logger.debug("Bot entered p2p chat (user opened chat window)")
        pass
