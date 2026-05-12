"""Zulip channel implementation using event queue API."""

from __future__ import annotations

import asyncio
from collections import deque
import hashlib
from pathlib import Path
import re
import threading
import time
from typing import Any, Literal
from urllib.parse import unquote

from loguru import logger
from pydantic import Field
import requests

from deeptutor.tutorbot.bus.events import OutboundMessage
from deeptutor.tutorbot.bus.queue import MessageBus
from deeptutor.tutorbot.channels.base import BaseChannel
from deeptutor.tutorbot.config.paths import get_media_dir
from deeptutor.tutorbot.config.schema import Base
from deeptutor.tutorbot.utils.helpers import split_message

_UPLOAD_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((/user_uploads/[^)\s]+)\)"
    r"|!\[([^\]]*)\]\((/user_uploads/[^)\s]+)\)",
)

_DISPLAY_MATH_RE = re.compile(
    r"^\s*\$\$(.+?)\$\$\s*$",
    re.MULTILINE | re.DOTALL,
)
_INLINE_MATH_RE = re.compile(
    r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)",
)
_CODE_BLOCK_RE = re.compile(
    r"(```(?!math)[\s\S]*?```|`[^`\n]+`)",
)

ZULIP_MAX_MESSAGE_LEN = 10000


class ZulipConfig(Base):
    enabled: bool = False
    site: str = ""
    email: str = ""
    api_key: str = Field(default="", repr=False)
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["mention", "open"] = "mention"
    timeout: float = Field(default=60.0)


class ZulipChannel(BaseChannel):
    name = "zulip"
    display_name = "Zulip"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return ZulipConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = ZulipConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: ZulipConfig = config
        self._client: Any = None
        self._bot_email: str = ""
        self._bot_user_id: int | None = None
        self._queue_id: str | None = None
        self._last_event_id: int = -1
        self._max_message_id: int = 0
        self._seen_ids: deque[int] = deque(maxlen=5000)
        self._listener_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._recipient_map: dict[str, dict] = {}

    def is_allowed(self, sender_id: str) -> bool:
        if super().is_allowed(sender_id):
            return True
        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list or "*" in allow_list:
            return False
        sender_str = str(sender_id)
        if sender_str.count("|") != 1:
            return False
        sid, email = sender_str.split("|", 1)
        return sid in allow_list or email in allow_list

    async def start(self) -> None:
        if not self.config.site or not self.config.email or not self.config.api_key:
            logger.error("Zulip site/email/apiKey not configured")
            return

        self._running = True
        self._loop = asyncio.get_running_loop()

        try:
            import zulip

            self._client = zulip.Client(
                email=self.config.email,
                api_key=self.config.api_key,
                site=self.config.site,
            )
        except Exception as e:
            logger.error("Failed to create Zulip client: {}", e)
            self._running = False
            return

        profile = self._call_with_retry(self._client.get_profile)
        if not profile or profile.get("result") != "success":
            logger.error("Failed to get Zulip bot profile")
            self._running = False
            return

        self._bot_email = profile.get("email", self.config.email)
        self._bot_user_id = profile.get("user_id")
        logger.info(
            "Zulip bot connected: {} (user_id={})",
            self._bot_email,
            self._bot_user_id,
        )

        self._listener_thread = threading.Thread(
            target=self._run_listener, daemon=True, name="zulip-listener"
        )
        self._listener_thread.start()

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False

        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        if self._queue_id and self._client:
            try:
                self._client.deregister(self._queue_id)
            except Exception:
                pass

        self._queue_id = None
        self._client = None

        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=5)

        self._listener_thread = None

    async def send(self, msg: OutboundMessage) -> None:
        if not self._client:
            logger.warning("Zulip client not running")
            return

        if not msg.metadata.get("msg_type"):
            stored = self._recipient_map.get(msg.chat_id)
            if stored:
                msg.metadata = {**stored, **msg.metadata}

        if not msg.metadata.get("_progress", False):
            self._stop_typing(msg.chat_id)

        try:
            for media_path in msg.media or []:
                await self._upload_and_send(msg.chat_id, media_path, msg.metadata)

            if msg.content and msg.content != "[empty message]":
                converted = self._convert_latex_to_zulip(msg.content)
                for chunk in split_message(converted, ZULIP_MAX_MESSAGE_LEN):
                    await self._send_text(msg.chat_id, chunk, msg.metadata)
        except Exception as e:
            logger.error("Zulip send error: {}", e)

    def _call_with_retry(self, fn, *args, max_retries=3, **kwargs):
        for attempt in range(max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = 2**attempt
                    logger.warning(
                        "Zulip API call failed (attempt {}): {}, retrying in {}s",
                        attempt + 1,
                        e,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error("Zulip API call failed after {} retries: {}", max_retries, e)
                    raise

    def _run_listener(self) -> None:
        while self._running:
            try:
                self._register_queue()
                if not self._queue_id:
                    logger.error("Failed to register Zulip event queue, retrying in 10s...")
                    time.sleep(10)
                    continue

                while self._running:
                    try:
                        result = self._client.get_events(
                            queue_id=self._queue_id,
                            last_event_id=self._last_event_id,
                        )
                    except Exception as e:
                        logger.warning("Zulip get_events error: {}", e)
                        time.sleep(2)
                        break

                    if result.get("result") == "http-error":
                        logger.warning("Zulip HTTP error, retrying...")
                        time.sleep(2)
                        break

                    if result.get("code") == "BAD_EVENT_QUEUE_ID":
                        logger.warning("Zulip event queue expired, re-registering...")
                        self._queue_id = None
                        break

                    if result.get("result") != "success":
                        logger.warning(
                            "Zulip get_events unexpected result: {}",
                            result.get("msg", result.get("result")),
                        )
                        time.sleep(2)
                        continue

                    for event in result.get("events", []):
                        self._last_event_id = max(
                            self._last_event_id, event.get("id", self._last_event_id)
                        )
                        if event.get("type") == "message":
                            self._on_message(event.get("message", {}))

            except Exception as e:
                logger.error("Zulip listener error: {}", e)
                time.sleep(5)

        logger.info("Zulip listener stopped")

    def _register_queue(self) -> None:
        try:
            result = self._call_with_retry(
                self._client.register,
                event_types=["message"],
            )
            if result.get("result") == "success":
                self._queue_id = result["queue_id"]
                self._last_event_id = result.get("last_event_id", -1)
                self._max_message_id = result.get("max_message_id", 0)
                logger.info(
                    "Zulip event queue registered: queue_id={}, max_message_id={}",
                    self._queue_id,
                    self._max_message_id,
                )
            else:
                logger.error("Zulip register failed: {}", result.get("msg", "unknown"))
                self._queue_id = None
        except Exception as e:
            logger.error("Zulip register exception: {}", e)
            self._queue_id = None

    def _is_own_message(self, message: dict) -> bool:
        sender_email = message.get("sender_email", "")
        sender_id = message.get("sender_id")
        if sender_email and sender_email == self._bot_email:
            return True
        if self._bot_user_id is not None and sender_id == self._bot_user_id:
            return True
        return False

    def _is_duplicate(self, message: dict) -> bool:
        msg_id = message.get("id")
        if msg_id is None:
            return False
        if msg_id <= self._max_message_id:
            return True
        if msg_id in self._seen_ids:
            return True
        self._seen_ids.append(msg_id)
        return False

    def _on_message(self, message: dict) -> None:
        if self._is_own_message(message):
            return
        if self._is_duplicate(message):
            return

        msg_type = message.get("type", "")
        content = message.get("content", "")
        content_type = message.get("content_type", "text/x-markdown")
        if content_type == "text/x-markdown":
            content = self._convert_zulip_latex_to_standard(content)
        sender_id = message.get("sender_id", "")
        sender_email = message.get("sender_email", "")
        display_recipient = message.get("display_recipient", "")
        subject = message.get("subject", "")

        composite_sender = f"{sender_id}|{sender_email}" if sender_email else str(sender_id)

        if msg_type == "stream":
            if isinstance(display_recipient, dict):
                stream_name = display_recipient.get("name", str(display_recipient))
            else:
                stream_name = str(display_recipient)
            topic = self._topic_label(subject)
            chat_id = self._stream_chat_id(stream_name, topic)
            if self.config.group_policy == "mention":
                if not self._is_mentioned(message):
                    return
            content = f"**[{stream_name} > {topic}]** {content}"
        elif msg_type == "private":
            chat_id = f"pm:{sender_id}"
            topic = ""
        else:
            return

        metadata = {
            "message_id": message.get("id"),
            "msg_type": msg_type,
            "sender_email": sender_email,
            "sender_full_name": message.get("sender_full_name", ""),
            "display_recipient": display_recipient,
            "subject": subject,
        }

        if msg_type == "stream":
            if isinstance(display_recipient, dict):
                metadata["stream"] = display_recipient.get("name", str(display_recipient))
            else:
                metadata["stream"] = display_recipient
            metadata["topic"] = topic
        else:
            metadata["recipient_user_id"] = sender_id

        self._recipient_map[chat_id] = metadata

        media_paths = self._download_attachments(message)

        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._start_typing_async(chat_id), self._loop)
            asyncio.run_coroutine_threadsafe(
                self._handle_message(
                    sender_id=composite_sender,
                    chat_id=chat_id,
                    content=content,
                    media=media_paths,
                    metadata=metadata,
                    session_key=self._session_key_for(chat_id),
                ),
                self._loop,
            )

    @staticmethod
    def _topic_label(subject: Any) -> str:
        topic = str(subject or "").strip()
        return topic or "(no topic)"

    @classmethod
    def _stream_chat_id(cls, stream_name: str, topic: str) -> str:
        return f"stream:{stream_name}:{cls._topic_label(topic)}"

    def _session_key_for(self, chat_id: str) -> str | None:
        if chat_id.startswith("stream:"):
            return f"{self.name}:{chat_id}"
        return None

    def _is_mentioned(self, message: dict) -> bool:
        if self._bot_user_id is None:
            return False
        for flag in message.get("flags", []):
            if isinstance(flag, str) and flag == "mentioned":
                return True
        return False

    def _download_attachments(self, message: dict) -> list[str]:
        paths: list[str] = []
        content = message.get("content", "")
        content_type = message.get("content_type", "text/x-markdown")

        upload_links = self._extract_upload_links(content, content_type)
        if not upload_links:
            return paths

        media_dir = get_media_dir("zulip")

        for name, path_id in upload_links:
            url = f"{self.config.site.rstrip('/')}{path_id}"
            dest = self._attachment_destination(media_dir, name, path_id, len(paths))

            if dest.exists():
                paths.append(str(dest))
                continue

            try:
                resp = requests.get(
                    url,
                    auth=(self.config.email, self.config.api_key),
                    timeout=self.config.timeout,
                )
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                paths.append(str(dest))
                logger.debug("Downloaded Zulip attachment: {}", name or path_id)
            except Exception as e:
                logger.warning("Failed to download Zulip attachment {}: {}", name or path_id, e)

        return paths

    @staticmethod
    def _safe_attachment_name(name: str, fallback: str) -> str:
        raw_name = unquote(name or "").strip() or fallback
        safe_name = re.sub(r"[^\w.\-]", "_", raw_name).strip("._")
        return safe_name or fallback

    @classmethod
    def _attachment_destination(
        cls,
        media_dir: Path,
        name: str,
        path_id: str,
        index: int,
    ) -> Path:
        fallback = f"attachment_{index}"
        filename = cls._safe_attachment_name(name or Path(unquote(path_id)).name, fallback)
        digest = hashlib.sha256(path_id.encode("utf-8")).hexdigest()[:12]
        return media_dir / f"{digest}_{filename}"

    @staticmethod
    def _extract_upload_links(
        content: str, content_type: str = "text/x-markdown"
    ) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        seen: set[str] = set()

        if content_type == "text/html":
            for match in re.finditer(r'href="(/user_uploads/[^"]+)"', content):
                path_id = match.group(1)
                if path_id not in seen:
                    seen.add(path_id)
                    name = Path(unquote(path_id)).name
                    links.append((name, path_id))
            for match in re.finditer(r'src="(/user_uploads/[^"]+)"', content):
                path_id = match.group(1)
                if path_id not in seen:
                    seen.add(path_id)
                    name = Path(unquote(path_id)).name
                    links.append((name, path_id))
        else:
            for match in _UPLOAD_LINK_RE.finditer(content):
                md_name = match.group(1) or match.group(3) or ""
                path_id = match.group(2) or match.group(4) or ""
                if path_id and path_id not in seen:
                    seen.add(path_id)
                    name = md_name if md_name else Path(unquote(path_id)).name
                    links.append((name, path_id))

        return links

    @staticmethod
    def _convert_latex_to_zulip(text: str) -> str:
        placeholders: list[str] = []

        def _save_code(m: re.Match) -> str:
            placeholders.append(m.group(0))
            return f"\x00CODE{len(placeholders) - 1}\x00"

        text = _CODE_BLOCK_RE.sub(_save_code, text)

        def _display_math(m: re.Match) -> str:
            body = m.group(1).strip()
            return f"```math\n{body}\n```"

        text = _DISPLAY_MATH_RE.sub(_display_math, text)

        def _inline_math(m: re.Match) -> str:
            body = m.group(1)
            return f"$${body}$$"

        text = _INLINE_MATH_RE.sub(_inline_math, text)

        for i, code in enumerate(placeholders):
            text = text.replace(f"\x00CODE{i}\x00", code)

        return text

    @staticmethod
    def _convert_zulip_latex_to_standard(text: str) -> str:
        placeholders: list[str] = []

        def _save_code(m: re.Match) -> str:
            placeholders.append(m.group(0))
            return f"\x00CODE{len(placeholders) - 1}\x00"

        text = _CODE_BLOCK_RE.sub(_save_code, text)

        text = re.sub(
            r"```math\s*\n(.*?)\n\s*```",
            lambda m: f"$$\n{m.group(1).strip()}\n$$",
            text,
            flags=re.DOTALL,
        )

        text = re.sub(
            r"(?<!\$)\$\$(?!\$)(.+?)(?<!\$)\$\$(?!\$)",
            lambda m: f"${m.group(1)}$",
            text,
        )

        for i, code in enumerate(placeholders):
            text = text.replace(f"\x00CODE{i}\x00", code)

        return text

    async def _send_text(self, chat_id: str, text: str, metadata: dict) -> None:
        client = self._client
        if not client:
            return
        request = self._build_send_request(chat_id, text, metadata)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._call_with_retry(
                client.call_endpoint,
                url="messages",
                request=request,
                timeout=self.config.timeout,
            ),
        )
        if result.get("result") != "success":
            logger.error("Zulip send failed: {}", result.get("msg", "unknown"))

    def _resolve_media_path(self, media_path: str) -> str | None:
        if Path(media_path).exists():
            return media_path

        path_id: str | None = None
        if media_path.startswith("/user_uploads/"):
            path_id = media_path
        elif self.config.site and media_path.startswith(self.config.site):
            stripped = media_path[len(self.config.site.rstrip("/")):]
            if stripped.startswith("/user_uploads/"):
                path_id = stripped

        if not path_id:
            return None

        media_dir = get_media_dir("zulip")
        name = Path(unquote(path_id)).name
        dest = self._attachment_destination(media_dir, name, path_id, 0)

        if dest.exists():
            return str(dest)

        url = f"{self.config.site.rstrip('/')}{path_id}"
        try:
            resp = requests.get(
                url,
                auth=(self.config.email, self.config.api_key),
                timeout=self.config.timeout,
            )
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            logger.debug("Downloaded Zulip attachment for re-upload: {}", name)
            return str(dest)
        except Exception as e:
            logger.warning("Failed to download Zulip attachment {}: {}", name, e)
            return None

    async def _upload_and_send(self, chat_id: str, media_path: str, metadata: dict) -> None:
        client = self._client
        if not client:
            return

        local_path = self._resolve_media_path(media_path)
        if not local_path:
            logger.error("Cannot resolve media path: {}", media_path)
            return

        loop = asyncio.get_running_loop()
        with open(local_path, "rb") as f:
            result = await loop.run_in_executor(
                None,
                lambda: self._call_with_retry(
                    client.call_endpoint,
                    url="user_uploads",
                    files=[f],
                    timeout=self.config.timeout,
                ),
            )
        if result.get("result") != "success":
            logger.error("Zulip upload failed: {}", result.get("msg", "unknown"))
            return

        uri = result.get("uri", "")
        filename = Path(media_path).name
        content = f"[{filename}]({self.config.site}{uri})"
        await self._send_text(chat_id, content, metadata)

    def _build_send_request(self, chat_id: str, content: str, metadata: dict) -> dict:
        msg_type = metadata.get("msg_type", "private")

        if msg_type == "stream":
            stream = metadata.get("stream", metadata.get("display_recipient", ""))
            topic = metadata.get("topic", metadata.get("subject", ""))
            return {
                "type": "stream",
                "to": stream,
                "subject": topic or "(no topic)",
                "content": content,
            }
        else:
            recipient = metadata.get("recipient_user_id") or metadata.get("sender_email", "")
            return {
                "type": "private",
                "to": [recipient] if recipient else [],
                "content": content,
            }

    async def _start_typing_async(self, chat_id: str) -> None:
        self._start_typing(chat_id)

    def _start_typing(self, chat_id: str) -> None:
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        if not self._client or not self._bot_user_id:
            return

        if not chat_id.startswith("pm:"):
            return

        recipient_user_id = chat_id[3:]
        if not recipient_user_id.isdigit():
            return

        try:
            while self._running and self._client:
                try:
                    self._client.set_typing_status(
                        {
                            "op": "start",
                            "to": [int(recipient_user_id)],
                        }
                    )
                except Exception as e:
                    logger.debug("Zulip typing status error: {}", e)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        finally:
            if self._client:
                try:
                    self._client.set_typing_status(
                        {
                            "op": "stop",
                            "to": [int(recipient_user_id)],
                        }
                    )
                except Exception:
                    pass
