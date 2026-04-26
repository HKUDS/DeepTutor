"""Matrix (Element) channel — inbound sync + outbound message/media delivery."""

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any, Literal, TypeAlias

from loguru import logger
from pydantic import Field

try:
    from mistune import create_markdown
    import nh3
    from nio import (
        AsyncClient,
        AsyncClientConfig,
        DownloadError,
        InviteEvent,
        JoinError,
        MatrixRoom,
        MemoryDownloadResponse,
        RoomEncryptedMedia,
        RoomMessage,
        RoomMessageMedia,
        RoomMessageText,
        RoomSendError,
        RoomTypingError,
        SyncError,
        UploadError,
    )
    from nio.crypto.attachments import decrypt_attachment
    from nio.exceptions import EncryptionError
except ImportError as e:
    raise ImportError(
        "Matrix dependencies not installed. Run: pip install deeptutor[matrix]"
    ) from e

from deeptutor.tutorbot.bus.events import OutboundMessage
from deeptutor.tutorbot.bus.queue import MessageBus
from deeptutor.tutorbot.channels.base import BaseChannel
from deeptutor.tutorbot.config.paths import get_data_dir, get_media_dir
from deeptutor.tutorbot.config.schema import Base
from deeptutor.tutorbot.utils.helpers import safe_filename

TYPING_NOTICE_TIMEOUT_MS = 30_000
# Must stay below TYPING_NOTICE_TIMEOUT_MS so the indicator doesn't expire mid-processing.
TYPING_KEEPALIVE_INTERVAL_MS = 20_000
MATRIX_HTML_FORMAT = "org.matrix.custom.html"
_ATTACH_MARKER = "[attachment: {}]"
_ATTACH_TOO_LARGE = "[attachment: {} - too large]"
_ATTACH_FAILED = "[attachment: {} - download failed]"
_ATTACH_UPLOAD_FAILED = "[attachment: {} - upload failed]"
_DEFAULT_ATTACH_NAME = "attachment"
_MSGTYPE_MAP = {"m.image": "image", "m.audio": "audio", "m.video": "video", "m.file": "file"}

MATRIX_MEDIA_EVENT_FILTER = (RoomMessageMedia, RoomEncryptedMedia)
MatrixMediaEvent: TypeAlias = RoomMessageMedia | RoomEncryptedMedia

MATRIX_MARKDOWN = create_markdown(
    escape=True,
    plugins=["table", "strikethrough", "url", "superscript", "subscript"],
)

MATRIX_ALLOWED_HTML_TAGS = {
    "p",
    "a",
    "strong",
    "em",
    "del",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "br",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "caption",
    "sup",
    "sub",
    "img",
}
MATRIX_ALLOWED_HTML_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href"},
    "code": {"class"},
    "ol": {"start"},
    "img": {"src", "alt", "title", "width", "height"},
}
MATRIX_ALLOWED_URL_SCHEMES = {"https", "http", "matrix", "mailto", "mxc"}


def _filter_matrix_html_attribute(tag: str, attr: str, value: str) -> str | None:
    """Filter attribute values to a safe Matrix-compatible subset."""
    if tag == "a" and attr == "href":
        return (
            value
            if value.lower().startswith(("https://", "http://", "matrix:", "mailto:"))
            else None
        )
    if tag == "img" and attr == "src":
        return value if value.lower().startswith("mxc://") else None
    if tag == "code" and attr == "class":
        classes = [
            c for c in value.split() if c.startswith("language-") and not c.startswith("language-_")
        ]
        return " ".join(classes) if classes else None
    return value


MATRIX_HTML_CLEANER = nh3.Cleaner(
    tags=MATRIX_ALLOWED_HTML_TAGS,
    attributes=MATRIX_ALLOWED_HTML_ATTRIBUTES,
    attribute_filter=_filter_matrix_html_attribute,
    url_schemes=MATRIX_ALLOWED_URL_SCHEMES,
    strip_comments=True,
    link_rel="noopener noreferrer",
)


def _render_markdown_html(text: str) -> str | None:
    """Render markdown to sanitized HTML; returns None for plain text."""
    try:
        formatted = MATRIX_HTML_CLEANER.clean(MATRIX_MARKDOWN(text)).strip()
    except Exception:
        return None
    if not formatted:
        return None
    # Skip formatted_body for plain <p>text</p> to keep payload minimal.
    if formatted.startswith("<p>") and formatted.endswith("</p>"):
        inner = formatted[3:-4]
        if "<" not in inner and ">" not in inner:
            return None
    return formatted


def _build_matrix_text_content(text: str) -> dict[str, object]:
    """Build Matrix m.text payload with optional HTML formatted_body."""
    content: dict[str, object] = {"msgtype": "m.text", "body": text, "m.mentions": {}}
    if html := _render_markdown_html(text):
        content["format"] = MATRIX_HTML_FORMAT
        content["formatted_body"] = html
    return content


class _NioLoguruHandler(logging.Handler):
    """Route matrix-nio stdlib logs into Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame, depth = frame.f_back, depth + 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _configure_nio_logging_bridge() -> None:
    """Bridge matrix-nio logs to Loguru (idempotent)."""
    nio_logger = logging.getLogger("nio")
    if not any(isinstance(h, _NioLoguruHandler) for h in nio_logger.handlers):
        nio_logger.handlers = [_NioLoguruHandler()]
        nio_logger.propagate = False


class MatrixConfig(Base):
    """Matrix (Element) channel configuration."""

    enabled: bool = False
    homeserver: str = "https://matrix.org"
    access_token: str = ""
    user_id: str = ""
    device_id: str = ""
    e2ee_enabled: bool = True
    sync_stop_grace_seconds: int = 2
    max_media_bytes: int = 20 * 1024 * 1024
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["open", "mention", "allowlist"] = "open"
    group_allow_from: list[str] = Field(default_factory=list)
    allow_room_mentions: bool = False


class MatrixChannel(BaseChannel):
    """Matrix (Element) channel using long-polling sync."""

    name = "matrix"
    display_name = "Matrix"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return MatrixConfig().model_dump(by_alias=True)

    def __init__(
        self,
        config: Any,
        bus: MessageBus,
        *,
        restrict_to_workspace: bool = False,
        workspace: str | Path | None = None,
    ):
        if isinstance(config, dict):
            config = MatrixConfig.model_validate(config)
        super().__init__(config, bus)
        self.client: AsyncClient | None = None
        self._sync_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._restrict_to_workspace = bool(restrict_to_workspace)
        self._workspace = (
            Path(workspace).expanduser().resolve(strict=False) if workspace is not None else None
        )
        self._server_upload_limit_bytes: int | None = None
        self._server_upload_limit_checked = False

    async def start(self) -> None:
        """Start Matrix client and begin sync loop."""
        self._running = True
        _configure_nio_logging_bridge()

        store_path = get_data_dir() / "matrix-store"
        store_path.mkdir(parents=True, exist_ok=True)

        self.client = AsyncClient(
            homeserver=self.config.homeserver,
            user=self.config.user_id,
            store_path=store_path,
            config=AsyncClientConfig(
                store_sync_tokens=True, encryption_enabled=self.config.e2ee_enabled
            ),
        )
        self.client.user_id = self.config.user_id
        self.client.access_token = self.config.access_token
        self.client.device_id = self.config.device_id

        self._register_event_callbacks()
        self._register_response_callbacks()

        if not self.config.e2ee_enabled:
            logger.warning("Matrix E2EE disabled; encrypted rooms may be undecryptable.")

        if self.config.device_id:
            try:
                self.client.load_store()
            except Exception:
                logger.exception("Matrix store load failed; restart may replay recent messages.")
        else:
            logger.warning("Matrix device_id empty; restart may replay recent messages.")

        self._sync_task = asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        """Stop the Matrix channel with graceful sync shutdown."""
        self._running = False
        for room_id in list(self._typing_tasks):
            await self._stop_typing_keepalive(room_id, clear_typing=False)
        if self.client:
            self.client.stop_sync_forever()
        if self._sync_task:
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._sync_task), timeout=self.config.sync_stop_grace_seconds
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._sync_task.cancel()
                try:
                    await self._sync_task
                except asyncio.CancelledError:
                    pass
        if self.client:
            await self.client.close()

    def _is_workspace_path_allowed(self, path: Path) -> bool:
        """Check path is inside workspace (when restriction enabled)."""
        if not self._restrict_to_workspace or not self._workspace:
            return True
        try:
            path.resolve(strict=False).relative_to(self._workspace)
            return True
        except ValueError:
            return False

    def _collect_outbound_media_candidates(self, media: list[str]) -> list[Path]:
        """Deduplicate and resolve outbound attachment paths."""
        seen: set[str] = set()
        candidates: list[Path] = []
        for raw in media:
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = Path(raw.strip()).expanduser()
            try:
                key = str(path.resolve(strict=False))
            except OSError:
                key = str(path)
            if key not in seen:
                seen.add(key)
                candidates.append(path)
        return candidates

    @staticmethod
    def _build_outbound_attachment_content(
        *,
        filename: str,
        mime: str,
        size_bytes: int,
        mxc_url: str,
        encryption_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build Matrix content payload for an uploaded file/image/audio/video."""
        prefix = mime.split("/")[0]
        msgtype = {"image": "m.image", "audio": "m.audio", "video": "m.video"}.get(prefix, "m.file")
        content: dict[str, Any] = {
            "msgtype": msgtype,
            "body": filename,
            "filename": filename,
            "info": {"mimetype": mime, "size": size_bytes},
            "m.mentions": {},
        }
        if encryption_info:
            content["file"] = {**encryption_info, "url": mxc_url}
        else:
            content["url"] = mxc_url
        return content

    def _is_encrypted_room(self, room_id: str) -> bool:
        if not self.client:
            return False
        room = getattr(self.client, "rooms", {}).get(room_id)
        return bool(getattr(room, "encrypted", False))

    async def _send_room_content(self, room_id: str, content: dict[str, Any]) -> None:
        """Send m.room.message with E2EE options."""
        if not self.client:
            return
        kwargs: dict[str, Any] = {
            "room_id": room_id,
            "message_type": "m.room.message",
            "content": content,
        }
        if self.config.e2ee_enabled:
            kwargs["ignore_unverified_devices"] = True
        await self.client.room_send(**kwargs)

    async def _resolve_server_upload_limit_bytes(self) -> int | None:
        """Query homeserver upload limit once per channel lifecycle."""
        if self._server_upload_limit_checked:
            return self._server_upload_limit_bytes
        self._server_upload_limit_checked = True
        if not self.client:
            return None
        try:
            response = await self.client.content_repository_config()
        except Exception:
            return None
        upload_size = getattr(response, "upload_size", None)
        if isinstance(upload_size, int) and upload_size > 0:
            self._server_upload_limit_bytes = upload_size
            return upload_size
        return None

    async def _effective_media_limit_bytes(self) -> int:
        """min(local config, server advertised) — 0 blocks all uploads."""
        local_limit = max(int(self.config.max_media_bytes), 0)
        server_limit = await self._resolve_server_upload_limit_bytes()
        if server_limit is None:
            return local_limit
        return min(local_limit, server_limit) if local_limit else 0

    async def _upload_and_send_attachment(
        self,
        room_id: str,
        path: Path,
        limit_bytes: int,
        relates_to: dict[str, Any] | None = None,
    ) -> str | None:
        """Upload one local file to Matrix and send it as a media message. Returns failure marker or None."""
        if not self.client:
            return _ATTACH_UPLOAD_FAILED.format(path.name or _DEFAULT_ATTACH_NAME)

        resolved = path.expanduser().resolve(strict=False)
        filename = safe_filename(resolved.name) or _DEFAULT_ATTACH_NAME
        fail = _ATTACH_UPLOAD_FAILED.format(filename)

        if not resolved.is_file() or not self._is_workspace_path_allowed(resolved):
            return fail
        try:
            size_bytes = resolved.stat().st_size
        except OSError:
            return fail
        if limit_bytes <= 0 or size_bytes > limit_bytes:
            return _ATTACH_TOO_LARGE.format(filename)

        mime = mimetypes.guess_type(filename, strict=False)[0] or "application/octet-stream"
        try:
            with resolved.open("rb") as f:
                upload_result = await self.client.upload(
                    f,
                    content_type=mime,
                    filename=filename,
                    encrypt=self.config.e2ee_enabled and self._is_encrypted_room(room_id),
                    filesize=size_bytes,
                )
        except Exception:
            return fail

        upload_response = upload_result[0] if isinstance(upload_result, tuple) else upload_result
        encryption_info = (
            upload_result[1]
            if isinstance(upload_result, tuple) and isinstance(upload_result[1], dict)
            else None
        )
        if isinstance(upload_response, UploadError):
            return fail
        mxc_url = getattr(upload_response, "content_uri", None)
        if not isinstance(mxc_url, str) or not mxc_url.startswith("mxc://"):
            return fail

        content = self._build_outbound_attachment_content(
            filename=filename,
            mime=mime,
            size_bytes=size_bytes,
            mxc_url=mxc_url,
            encryption_info=encryption_info,
        )
        if relates_to:
            content["m.relates_to"] = relates_to
        try:
            await self._send_room_content(room_id, content)
        except Exception:
            return fail
        return None

    async def send(self, msg: OutboundMessage) -> None:
        """Send outbound content; clear typing for non-progress messages."""
        if not self.client:
            return
        text = msg.content or ""
        candidates = self._collect_outbound_media_candidates(msg.media)
        relates_to = self._build_thread_relates_to(msg.metadata)
        is_progress = bool((msg.metadata or {}).get("_progress"))
        try:
            failures: list[str] = []
            if candidates:
                limit_bytes = await self._effective_media_limit_bytes()
                for path in candidates:
                    if fail := await self._upload_and_send_attachment(
                        room_id=msg.chat_id,
                        path=path,
                        limit_bytes=limit_bytes,
                        relates_to=relates_to,
                    ):
                        failures.append(fail)
            if failures:
                text = (
                    f"{text.rstrip()}\n{chr(10).join(failures)}"
                    if text.strip()
                    else "\n".join(failures)
                )
            if text or not candidates:
                content = _build_matrix_text_content(text)
                if relates_to:
                    content["m.relates_to"] = relates_to
                await self._send_room_content(msg.chat_id, content)
        finally:
            if not is_progress:
                await self._stop_typing_keepalive(msg.chat_id, clear_typing=True)

    def _register_event_callbacks(self) -> None:
        self.client.add_event_callback(self._on_message, RoomMessageText)
        self.client.add_event_callback(self._on_media_message, MATRIX_MEDIA_EVENT_FILTER)
        self.client.add_event_callback(self._on_room_invite, InviteEvent)

    def _register_response_callbacks(self) -> None:
        self.client.add_response_callback(self._on_sync_error, SyncError)
        self.client.add_response_callback(self._on_join_error, JoinError)
        self.client.add_response_callback(self._on_send_error, RoomSendError)

    def _log_response_error(self, label: str, response: Any) -> None:
        """Log Matrix response errors — auth errors at ERROR level, rest at WARNING."""
        code = getattr(response, "status_code", None)
        is_auth = code in {"M_UNKNOWN_TOKEN", "M_FORBIDDEN", "M_UNAUTHORIZED"}
        is_fatal = is_auth or getattr(response, "soft_logout", False)
        (logger.error if is_fatal else logger.warning)("Matrix {} failed: {}", label, response)

    async def _on_sync_error(self, response: SyncError) -> None:
        self._log_response_error("sync", response)

    async def _on_join_error(self, response: JoinError) -> None:
        self._log_response_error("join", response)

    async def _on_send_error(self, response: RoomSendError) -> None:
        self._log_response_error("send", response)

    async def _set_typing(self, room_id: str, typing: bool) -> None:
        """Best-effort typing indicator update."""
        if not self.client:
            return
        try:
            response = await self.client.room_typing(
                room_id=room_id, typing_state=typing, timeout=TYPING_NOTICE_TIMEOUT_MS
            )
            if isinstance(response, RoomTypingError):
                logger.debug("Matrix typing failed for {}: {}", room_id, response)
        except Exception:
            pass

    async def _start_typing_keepalive(self, room_id: str) -> None:
        """Start periodic typing refresh (spec-recommended keepalive)."""
        await self._stop_typing_keepalive(room_id, clear_typing=False)
        await self._set_typing(room_id, True)
        if not self._running:
            return

        async def loop() -> None:
            try:
                while self._running:
                    await asyncio.sleep(TYPING_KEEPALIVE_INTERVAL_MS / 1000)
                    await self._set_typing(room_id, True)
            except asyncio.CancelledError:
                pass

        self._typing_tasks[room_id] = asyncio.create_task(loop())

    async def _stop_typing_keepalive(self, room_id: str, *, clear_typing: bool) -> None:
        if task := self._typing_tasks.pop(room_id, None):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if clear_typing:
            await self._set_typing(room_id, False)

    async def _sync_loop(self) -> None:
        while self._running:
            try:
                await self.client.sync_forever(timeout=30000, full_state=True)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2)

    async def _on_room_invite(self, room: MatrixRoom, event: InviteEvent) -> None:
        if self.is_allowed(event.sender):
            await self.client.join(room.room_id)

    def _is_direct_room(self, room: MatrixRoom) -> bool:
        count = getattr(room, "member_count", None)
        return isinstance(count, int) and count <= 2

    def _is_bot_mentioned(self, event: RoomMessage) -> bool:
        """Check m.mentions payload for bot mention."""
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return False
        mentions = (source.get("content") or {}).get("m.mentions")
        if not isinstance(mentions, dict):
            return False
        user_ids = mentions.get("user_ids")
        if isinstance(user_ids, list) and self.config.user_id in user_ids:
            return True
        return bool(self.config.allow_room_mentions and mentions.get("room") is True)

    def _should_process_message(self, room: MatrixRoom, event: RoomMessage) -> bool:
        """Apply sender and room policy checks."""
        if not self.is_allowed(event.sender):
            return False
        if self._is_direct_room(room):
            return True
        policy = self.config.group_policy
        if policy == "open":
            return True
        if policy == "allowlist":
            return room.room_id in (self.config.group_allow_from or [])
        if policy == "mention":
            return self._is_bot_mentioned(event)
        return False

    def _media_dir(self) -> Path:
        return get_media_dir("matrix")

    @staticmethod
    def _event_source_content(event: RoomMessage) -> dict[str, Any]:
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return {}
        content = source.get("content")
        return content if isinstance(content, dict) else {}

    def _event_thread_root_id(self, event: RoomMessage) -> str | None:
        relates_to = self._event_source_content(event).get("m.relates_to")
        if not isinstance(relates_to, dict) or relates_to.get("rel_type") != "m.thread":
            return None
        root_id = relates_to.get("event_id")
        return root_id if isinstance(root_id, str) and root_id else None

    def _thread_metadata(self, event: RoomMessage) -> dict[str, str] | None:
        if not (root_id := self._event_thread_root_id(event)):
            return None
        meta: dict[str, str] = {"thread_root_event_id": root_id}
        if isinstance(reply_to := getattr(event, "event_id", None), str) and reply_to:
            meta["thread_reply_to_event_id"] = reply_to
        return meta

    @staticmethod
    def _build_thread_relates_to(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
        if not metadata:
            return None
        root_id = metadata.get("thread_root_event_id")
        if not isinstance(root_id, str) or not root_id:
            return None
        reply_to = metadata.get("thread_reply_to_event_id") or metadata.get("event_id")
        if not isinstance(reply_to, str) or not reply_to:
            return None
        return {
            "rel_type": "m.thread",
            "event_id": root_id,
            "m.in_reply_to": {"event_id": reply_to},
            "is_falling_back": True,
        }

    def _event_attachment_type(self, event: MatrixMediaEvent) -> str:
        msgtype = self._event_source_content(event).get("msgtype")
        return _MSGTYPE_MAP.get(msgtype, "file")

    @staticmethod
    def _is_encrypted_media_event(event: MatrixMediaEvent) -> bool:
        return (
            isinstance(getattr(event, "key", None), dict)
            and isinstance(getattr(event, "hashes", None), dict)
            and isinstance(getattr(event, "iv", None), str)
        )

    def _event_declared_size_bytes(self, event: MatrixMediaEvent) -> int | None:
        info = self._event_source_content(event).get("info")
        size = info.get("size") if isinstance(info, dict) else None
        return size if isinstance(size, int) and size >= 0 else None

    def _event_mime(self, event: MatrixMediaEvent) -> str | None:
        info = self._event_source_content(event).get("info")
        if isinstance(info, dict) and isinstance(m := info.get("mimetype"), str) and m:
            return m
        m = getattr(event, "mimetype", None)
        return m if isinstance(m, str) and m else None

    def _event_filename(self, event: MatrixMediaEvent, attachment_type: str) -> str:
        body = getattr(event, "body", None)
        if isinstance(body, str) and body.strip():
            if candidate := safe_filename(Path(body).name):
                return candidate
        return _DEFAULT_ATTACH_NAME if attachment_type == "file" else attachment_type

    def _build_attachment_path(
        self, event: MatrixMediaEvent, attachment_type: str, filename: str, mime: str | None
    ) -> Path:
        safe_name = safe_filename(Path(filename).name) or _DEFAULT_ATTACH_NAME
        suffix = Path(safe_name).suffix
        if not suffix and mime:
            if guessed := mimetypes.guess_extension(mime, strict=False):
                safe_name, suffix = f"{safe_name}{guessed}", guessed
        stem = (Path(safe_name).stem or attachment_type)[:72]
        suffix = suffix[:16]
        event_id = safe_filename(str(getattr(event, "event_id", "") or "evt").lstrip("$"))
        event_prefix = (event_id[:24] or "evt").strip("_")
        return self._media_dir() / f"{event_prefix}_{stem}{suffix}"

    async def _download_media_bytes(self, mxc_url: str) -> bytes | None:
        if not self.client:
            return None
        response = await self.client.download(mxc=mxc_url)
        if isinstance(response, DownloadError):
            logger.warning("Matrix download failed for {}: {}", mxc_url, response)
            return None
        body = getattr(response, "body", None)
        if isinstance(body, (bytes, bytearray)):
            return bytes(body)
        if isinstance(response, MemoryDownloadResponse):
            return bytes(response.body)
        if isinstance(body, (str, Path)):
            path = Path(body)
            if path.is_file():
                try:
                    return path.read_bytes()
                except OSError:
                    return None
        return None

    def _decrypt_media_bytes(self, event: MatrixMediaEvent, ciphertext: bytes) -> bytes | None:
        key_obj, hashes, iv = (
            getattr(event, "key", None),
            getattr(event, "hashes", None),
            getattr(event, "iv", None),
        )
        key = key_obj.get("k") if isinstance(key_obj, dict) else None
        sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
        if not all(isinstance(v, str) for v in (key, sha256, iv)):
            return None
        try:
            return decrypt_attachment(ciphertext, key, sha256, iv)
        except (EncryptionError, ValueError, TypeError):
            logger.warning("Matrix decrypt failed for event {}", getattr(event, "event_id", ""))
            return None

    async def _fetch_media_attachment(
        self,
        room: MatrixRoom,
        event: MatrixMediaEvent,
    ) -> tuple[dict[str, Any] | None, str]:
        """Download, decrypt if needed, and persist a Matrix attachment."""
        atype = self._event_attachment_type(event)
        mime = self._event_mime(event)
        filename = self._event_filename(event, atype)
        mxc_url = getattr(event, "url", None)
        fail = _ATTACH_FAILED.format(filename)

        if not isinstance(mxc_url, str) or not mxc_url.startswith("mxc://"):
            return None, fail

        limit_bytes = await self._effective_media_limit_bytes()
        declared = self._event_declared_size_bytes(event)
        if declared is not None and declared > limit_bytes:
            return None, _ATTACH_TOO_LARGE.format(filename)

        downloaded = await self._download_media_bytes(mxc_url)
        if downloaded is None:
            return None, fail

        encrypted = self._is_encrypted_media_event(event)
        data = downloaded
        if encrypted:
            if (data := self._decrypt_media_bytes(event, downloaded)) is None:
                return None, fail

        if len(data) > limit_bytes:
            return None, _ATTACH_TOO_LARGE.format(filename)

        path = self._build_attachment_path(event, atype, filename, mime)
        try:
            path.write_bytes(data)
        except OSError:
            return None, fail

        attachment = {
            "type": atype,
            "mime": mime,
            "filename": filename,
            "event_id": str(getattr(event, "event_id", "") or ""),
            "encrypted": encrypted,
            "size_bytes": len(data),
            "path": str(path),
            "mxc_url": mxc_url,
        }
        return attachment, _ATTACH_MARKER.format(path)

    def _base_metadata(self, room: MatrixRoom, event: RoomMessage) -> dict[str, Any]:
        """Build common metadata for text and media handlers."""
        meta: dict[str, Any] = {"room": getattr(room, "display_name", room.room_id)}
        if isinstance(eid := getattr(event, "event_id", None), str) and eid:
            meta["event_id"] = eid
        if thread := self._thread_metadata(event):
            meta.update(thread)
        return meta

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if event.sender == self.config.user_id or not self._should_process_message(room, event):
            return
        await self._start_typing_keepalive(room.room_id)
        try:
            await self._handle_message(
                sender_id=event.sender,
                chat_id=room.room_id,
                content=event.body,
                metadata=self._base_metadata(room, event),
            )
        except Exception:
            await self._stop_typing_keepalive(room.room_id, clear_typing=True)
            raise

    async def _on_media_message(self, room: MatrixRoom, event: MatrixMediaEvent) -> None:
        if event.sender == self.config.user_id or not self._should_process_message(room, event):
            return
        attachment, marker = await self._fetch_media_attachment(room, event)
        parts: list[str] = []
        if isinstance(body := getattr(event, "body", None), str) and body.strip():
            parts.append(body.strip())

        if attachment and attachment.get("type") == "audio":
            transcription = await self.transcribe_audio(attachment["path"])
            if transcription:
                parts.append(f"[transcription: {transcription}]")
            else:
                parts.append(marker)
        elif marker:
            parts.append(marker)

        await self._start_typing_keepalive(room.room_id)
        try:
            meta = self._base_metadata(room, event)
            meta["attachments"] = []
            if attachment:
                meta["attachments"] = [attachment]
            await self._handle_message(
                sender_id=event.sender,
                chat_id=room.room_id,
                content="\n".join(parts),
                media=[attachment["path"]] if attachment else [],
                metadata=meta,
            )
        except Exception:
            await self._stop_typing_keepalive(room.room_id, clear_typing=True)
            raise
