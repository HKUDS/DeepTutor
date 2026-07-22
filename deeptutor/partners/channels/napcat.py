"""NapCat (OneBot v11) channel for personal QQ accounts, over WebSocket.

Ported from nanobot's ``channels/napcat.py``. Coexists with the official
botpy-based ``qq`` channel — this one drives a *personal* QQ account through
a NapCat (OneBot v11) WebSocket endpoint, hence the distinct display name.
"""

from __future__ import annotations

import asyncio
import base64
from collections import deque
import json
import os
from pathlib import Path
import random
import time
from typing import Annotated, Any, Literal
import uuid

import aiohttp
from loguru import logger
from pydantic import Field
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import BaseChannel
from deeptutor.partners.config.paths import get_media_dir
from deeptutor.partners.config.schema import DeliveryOverrides
from deeptutor.partners.helpers import safe_filename
from deeptutor.partners.network import validate_url_target

_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60)
_ACTION_TIMEOUT = 20.0


# `"mention"` (only @mentions / replies) | `"open"` (every message) | float p
# in [0, 1]: mentions/replies always reply; other messages reply with probability
# p. 0.0 ≡ "mention", 1.0 ≡ "open".
GroupPolicy = Literal["mention", "open"] | Annotated[float, Field(ge=0.0, le=1.0)]


class NapcatConfig(DeliveryOverrides):
    """NapCat (OneBot v11) channel configuration."""

    enabled: bool = False
    ws_url: str = "ws://127.0.0.1:3001"
    access_token: str = Field(default="", repr=False)
    allow_from: list[str] = Field(default_factory=list)
    group_policy: GroupPolicy = "mention"
    # Per-group overrides keyed by stringified group_id, e.g. {"123456": "open"}.
    # Falls back to `group_policy` when a group_id isn't listed.
    group_policy_overrides: dict[str, GroupPolicy] = Field(default_factory=dict)
    welcome_new_members: bool = True
    # Hard cap for inbound image downloads. Bigger images are dropped.
    max_image_bytes: int = Field(default=20 * 1024 * 1024, ge=1)


class NapcatChannel(BaseChannel):
    """NapCat / OneBot v11 channel."""

    name = "napcat"
    display_name = "QQ (NapCat)"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return NapcatConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = NapcatConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: NapcatConfig = config

        self._ws: ClientConnection | None = None
        self._http: aiohttp.ClientSession | None = None
        self._self_id: int | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._processed_ids: deque[int] = deque(maxlen=2000)
        self._bot_outbound_ids: deque[int] = deque(maxlen=2000)
        self._background_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.config.ws_url:
            logger.error("napcat: ws_url not configured")
            return

        self._running = True
        self._http = aiohttp.ClientSession(timeout=_DOWNLOAD_TIMEOUT)

        backoff = iter((5, 10))  # then 30s forever
        while self._running:
            try:
                await self._run_once()
                backoff = iter((5, 10))  # reset after a clean session
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("napcat: connection lost: {}", e)
            if self._running:
                await asyncio.sleep(next(backoff, 30))

    async def _run_once(self) -> None:
        headers = []
        if self.config.access_token:
            headers.append(("Authorization", f"Bearer {self.config.access_token}"))

        logger.info("napcat: connecting to {}", self.config.ws_url)
        async with ws_connect(self.config.ws_url, additional_headers=headers) as ws:
            self._ws = ws
            logger.info("napcat: connected")
            try:
                # Validate the connection before entering the dispatch loop.
                # NapCat may interleave meta_event frames before our echo
                # response, so dispatch any non-matching frames as we go.
                echo = uuid.uuid4().hex
                await ws.send(
                    json.dumps(
                        {"action": "get_login_info", "params": {}, "echo": echo},
                        ensure_ascii=False,
                    )
                )
                deadline = asyncio.get_running_loop().time() + _ACTION_TIMEOUT
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError("get_login_info timed out")
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict) and payload.get("echo") == echo:
                        data = payload.get("data") or {}
                        logger.info(
                            "napcat: logged in as {} (user_id={})",
                            data.get("nickname"),
                            data.get("user_id"),
                        )
                        break
                    await self._dispatch_frame(raw)

                async for raw in ws:
                    await self._dispatch_frame(raw)
            finally:
                self._ws = None
                self._fail_pending(RuntimeError("napcat: websocket disconnected"))

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._http is not None:
            try:
                await self._http.close()
            except Exception:
                pass
            self._http = None
        self._fail_pending(RuntimeError("napcat: stopped"))
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()

    def _fail_pending(self, err: BaseException) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(err)
        self._pending.clear()

    # ------------------------------------------------------------------
    # Frame dispatch
    # ------------------------------------------------------------------

    async def _dispatch_frame(self, raw: str | bytes) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("napcat: dropping non-JSON frame")
            return
        if not isinstance(payload, dict):
            return

        # Action response: identified by `echo` and absence of post_type.
        if "echo" in payload and payload.get("post_type") is None:
            echo = payload.get("echo")
            fut = self._pending.pop(echo, None) if isinstance(echo, str) else None
            if fut and not fut.done():
                fut.set_result(payload)
            return

        if (sid := payload.get("self_id")) is not None:
            try:
                self._self_id = int(sid)
            except (TypeError, ValueError):
                pass

        post_type = payload.get("post_type")
        if post_type == "message":
            self._create_background_task(self._on_message(payload), "message")
        elif post_type == "notice":
            self._create_background_task(self._on_notice(payload), "notice")

    def _create_background_task(self, coro: Any, kind: str) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _done(done: asyncio.Task[None]) -> None:
            self._background_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("napcat: {} handler failed: {}", kind, e)

        task.add_done_callback(_done)

    # ------------------------------------------------------------------
    # Inbound: messages
    # ------------------------------------------------------------------

    async def _on_message(self, ev: dict[str, Any]) -> None:
        msg_id = ev.get("message_id")
        if isinstance(msg_id, int):
            if msg_id in self._processed_ids:
                return
            self._processed_ids.append(msg_id)

        message_type = ev.get("message_type")
        user_id = ev.get("user_id")
        if user_id is None or message_type not in ("group", "private"):
            return

        segments = self._normalize_segments(ev.get("message"))
        text, images, mentioned_self, reply_to_id = self._parse_segments(segments)

        media_paths: list[str] = []
        for info in images:
            if local := await self._download_image(info):
                media_paths.append(local)

        sender = ev.get("sender") or {}
        nickname = sender.get("card") or sender.get("nickname")

        if message_type == "group":
            group_id = ev.get("group_id")
            if group_id is None:
                return

            replying_to_bot = isinstance(reply_to_id, int) and reply_to_id in self._bot_outbound_ids
            if not self._should_reply_in_group(
                group_id=group_id,
                mentioned_self=mentioned_self,
                replying_to_bot=replying_to_bot,
            ):
                return

            chat_id = f"group:{group_id}"
            content = self._format_group_content(
                text=text,
                nickname=nickname,
                user_id=user_id,
            )
        else:
            chat_id = f"private:{user_id}"
            content = text

        if not content and not media_paths:
            return

        await self._handle_message(
            sender_id=str(user_id),
            chat_id=chat_id,
            content=content,
            media=media_paths or None,
            metadata={
                "message_id": msg_id,
                "is_group": message_type == "group",
                "nickname": nickname,
                "reply_to": reply_to_id,
            },
        )

    @staticmethod
    def _normalize_segments(message: Any) -> list[dict[str, Any]]:
        # NapCat defaults to array format. Treat raw strings as a single text
        # segment rather than parsing CQ codes — that path is fragile and
        # users can configure NapCat to emit arrays.
        if isinstance(message, list):
            return [seg for seg in message if isinstance(seg, dict)]
        if isinstance(message, str) and message:
            return [{"type": "text", "data": {"text": message}}]
        return []

    def _parse_segments(
        self, segments: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]], bool, int | None]:
        parts: list[str] = []
        images: list[dict[str, Any]] = []
        mentioned_self = False
        reply_to: int | None = None
        self_id_str = str(self._self_id) if self._self_id is not None else None

        for seg in segments:
            stype = seg.get("type")
            data = seg.get("data") or {}
            if stype == "text":
                if txt := data.get("text"):
                    parts.append(str(txt))
            elif stype == "image":
                # OneBot exposes the downloadable image at `url`. NapCat
                # additionally provides `file` (e.g. <md5>.png) and
                # `file_size` (bytes, sometimes a string).
                url = data.get("url")
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    images.append(
                        {
                            "url": url,
                            "file": data.get("file"),
                            "file_size": data.get("file_size"),
                        }
                    )
                else:
                    logger.warning("napcat: received invalid image url: {}", url)
            elif stype == "at":
                qq = str(data.get("qq", ""))
                if self_id_str and qq == self_id_str:
                    mentioned_self = True
                else:
                    parts.append(f"@{qq}")
            elif stype == "reply":
                rid = data.get("id")
                try:
                    reply_to = int(rid) if rid is not None else None
                except (TypeError, ValueError):
                    pass
            elif stype == "face":
                parts.append(f"[face:{data.get('id', '')}]")

        text = " ".join(p.strip() for p in parts if p.strip()).strip()
        return text, images, mentioned_self, reply_to

    def _should_reply_in_group(
        self, *, group_id: Any, mentioned_self: bool, replying_to_bot: bool
    ) -> bool:
        if mentioned_self or replying_to_bot:
            return True
        policy = self.config.group_policy_overrides.get(str(group_id), self.config.group_policy)
        if policy == "open":
            return True
        if policy == "mention":
            return False
        # Probability case: float in [0.0, 1.0].
        return random.random() < float(policy)

    @staticmethod
    def _format_group_content(
        *,
        text: str,
        nickname: str,
        user_id: Any,
    ) -> str:
        label = nickname or str(user_id)
        return f"{label}: {text}"

    # ------------------------------------------------------------------
    # Inbound: notices (member joined etc.)
    # ------------------------------------------------------------------

    async def _on_notice(self, ev: dict[str, Any]) -> None:
        if ev.get("notice_type") != "group_increase" or not self.config.welcome_new_members:
            return

        group_id = ev.get("group_id")
        user_id = ev.get("user_id")
        if group_id is None or user_id is None:
            return

        try:
            group_id_int = int(group_id)
            user_id_int = int(user_id)
        except (TypeError, ValueError):
            logger.warning(
                "napcat: invalid group_increase ids group_id={} user_id={}", group_id, user_id
            )
            return

        nickname = await self._lookup_member_name(group_id_int, user_id_int)

        # Note: this routes through is_allowed(). For group bots set
        # `allow_from: ["*"]` (or include the joining user's id) for welcomes
        # to fire — same trust model as a regular inbound message.
        await self._handle_message(
            sender_id=str(user_id),
            chat_id=f"group:{group_id}",
            content=f"[group event] new member {nickname} joined group {group_id}",
            metadata={
                "is_group": True,
                "event": "group_increase",
            },
        )

    async def _lookup_member_name(self, group_id: int, user_id: int) -> str:
        """Lookup group member nickname. Fallback to user id."""
        try:
            resp = await self._call_action(
                "get_group_member_info",
                {"group_id": group_id, "user_id": user_id, "no_cache": True},
            )
            data = resp.get("data", {})
            return data.get("card") or data.get("nickname") or str(user_id)
        except Exception as e:
            logger.warning("napcat: get_group_member_info failed: {}", e)
            return str(user_id)

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        if self._ws is None:
            # Raise so the channel manager's retry policy applies (send
            # contract: raise on delivery failure).
            raise RuntimeError("napcat: not connected")

        kind, _, target = msg.chat_id.partition(":")
        if kind not in ("private", "group") or not target:
            raise ValueError(f"napcat: invalid chat_id '{msg.chat_id}'")

        segments: list[dict[str, Any]] = []
        for ref in msg.media or []:
            if seg := await self._build_image_segment(ref):
                segments.append(seg)
        if text := (msg.content or "").strip():
            segments.append({"type": "text", "data": {"text": text}})
        if not segments:
            return

        params: dict[str, Any] = {"message": segments}
        if kind == "group":
            params["message_type"] = "group"
            params["group_id"] = int(target)
        else:
            params["message_type"] = "private"
            params["user_id"] = int(target)

        resp = await self._call_action("send_msg", params)
        data = resp.get("data") or {}
        if (mid := data.get("message_id")) is not None:
            self._bot_outbound_ids.append(int(mid))

    async def _build_image_segment(self, ref: str) -> dict[str, Any] | None:
        ref = (ref or "").strip()
        if not ref:
            return None
        if ref.startswith(("http://", "https://")):
            ok, err = validate_url_target(ref)
            if not ok:
                logger.warning("napcat: rejected remote image '{}': {}", ref, err)
                return None
            return {"type": "image", "data": {"file": ref}}
        # Local path → base64 so it works even when NapCat runs on a
        # different host/container than DeepTutor.
        path = Path(os.path.expanduser(ref)).resolve()
        if not path.is_file():
            logger.warning("napcat: local image not found: {}", path)
            return None
        data = await asyncio.to_thread(path.read_bytes)
        return {"type": "image", "data": {"file": "base64://" + base64.b64encode(data).decode()}}

    async def _call_action(
        self,
        action: str,
        params: dict[str, Any],
        timeout: float = _ACTION_TIMEOUT,
    ) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("napcat: not connected")
        echo = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[echo] = fut
        try:
            await self._ws.send(
                json.dumps({"action": action, "params": params, "echo": echo}, ensure_ascii=False)
            )
            resp = await asyncio.wait_for(fut, timeout=timeout)
            status = resp.get("status")
            retcode = resp.get("retcode")
            if (status and status != "ok") or (retcode not in (None, 0)):
                raise RuntimeError(
                    f"napcat: action {action} failed status={status!r} retcode={retcode!r}"
                )
            return resp
        finally:
            self._pending.pop(echo, None)

    # ------------------------------------------------------------------
    # Image download
    # ------------------------------------------------------------------

    async def _download_image(self, info: dict[str, Any]) -> str | None:
        url = info.get("url")
        if not isinstance(url, str):
            return None
        if self._http is None:
            return None
        ok, err = validate_url_target(url)
        if not ok:
            logger.warning("napcat: skip image '{}': {}", url, err)
            return None
        max_bytes = self.config.max_image_bytes

        # Reject upfront when NapCat tells us the size and it's too big.
        try:
            declared_size = int(info["file_size"])
            if declared_size > max_bytes:
                logger.warning(
                    "napcat: image declared size={} exceeds max_image_bytes={} url={}",
                    declared_size,
                    max_bytes,
                    url,
                )
                return None
        except (TypeError, KeyError):
            pass

        try:
            async with self._http.get(url, allow_redirects=False) as resp:
                if 300 <= resp.status < 400:
                    logger.warning("napcat: image download redirect rejected url={}", url)
                    return None
                if resp.status >= 400:
                    logger.warning("napcat: image download status={} url={}", resp.status, url)
                    return None
                # Stream until EOF, capping memory at max_bytes. Don't use
                # content.read(max_bytes+1) — it returns only what's currently
                # buffered, which truncates chunked responses mid-image.
                buf = bytearray()
                truncated = False
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        truncated = True
                        break
                if truncated:
                    logger.warning(
                        "napcat: image exceeds max_image_bytes={} url={}", max_bytes, url
                    )
                    return None
                data = bytes(buf)
        except Exception as e:
            logger.warning("napcat: image download error url={} err={}", url, e)
            return None

        filename_hint = info.get("file")
        if filename_hint:
            name = safe_filename(filename_hint)
        else:
            name = f"{int(time.time() * 1000)}.jpg"
        # Resolved lazily (not in __init__) so constructing the channel never
        # touches the partners data tree.
        path = get_media_dir("napcat") / name
        try:
            await asyncio.to_thread(path.write_bytes, data)
        except OSError as e:
            logger.warning("napcat: failed to save image: {}", e)
            return None
        return str(path)
