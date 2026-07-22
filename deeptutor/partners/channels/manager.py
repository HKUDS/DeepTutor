"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import hashlib
from typing import Any

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import BaseChannel
from deeptutor.partners.config.schema import ChannelsConfig


def _logger():
    from loguru import logger as _log

    return _log


# Retry delays for message sending (exponential backoff: 1s, 2s, 4s)
_SEND_RETRY_DELAYS = (1, 2, 4)

_BOOL_CAMEL_ALIASES: dict[str, str] = {
    "send_progress": "sendProgress",
    "send_tool_hints": "sendToolHints",
}


class ChannelManager:
    """
    Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages with retry, duplicate suppression and
      stream-delta coalescing
    """

    def __init__(
        self,
        channels_config: ChannelsConfig,
        bus: MessageBus,
        groq_api_key: str = "",
    ):
        self.channels_config = channels_config
        self.bus = bus
        self._groq_api_key = groq_api_key
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._origin_reply_fingerprints: dict[tuple[str, str, str], str] = {}

        self._init_channels()

    def _init_channels(self) -> None:
        """Initialize channels discovered via pkgutil scan + entry_points plugins."""
        from deeptutor.partners.channels.registry import discover_all

        for name, cls in discover_all().items():
            section = getattr(self.channels_config, name, None)
            if section is None:
                continue
            enabled = (
                section.get("enabled", False)
                if isinstance(section, dict)
                else getattr(section, "enabled", False)
            )
            if not enabled:
                continue
            try:
                channel = cls(section, self.bus)
                channel.transcription_api_key = self._groq_api_key
                # Effective delivery flags are per-channel only. Historical
                # top-level channel config keys are ignored at runtime.
                channel.send_progress = self._resolve_bool_override(
                    section, "send_progress", default=True
                )
                channel.send_tool_hints = self._resolve_bool_override(
                    section, "send_tool_hints", default=True
                )
                self.channels[name] = channel
                _logger().info("{} channel enabled", cls.display_name)
            except Exception as e:
                _logger().warning("{} channel not available: {}", name, e)

        self._validate_allow_from()

    @staticmethod
    def _resolve_bool_override(section: Any, key: str, *, default: bool) -> bool:
        """Return *key* from *section* if it is a bool, otherwise *default*.

        For dict configs also checks the camelCase alias (e.g. ``sendProgress``
        for ``send_progress``) so raw JSON configs work alongside Pydantic
        models.
        """
        if isinstance(section, dict):
            value = section.get(key)
            if value is None:
                camel = _BOOL_CAMEL_ALIASES.get(key)
                if camel:
                    value = section.get(camel)
            return value if isinstance(value, bool) else default
        value = getattr(section, key, None)
        return value if isinstance(value, bool) else default

    def _validate_allow_from(self) -> None:
        for name, ch in self.channels.items():
            if getattr(ch.config, "allow_from", None) == []:
                raise SystemExit(
                    f'Error: "{name}" has empty allowFrom (denies all). '
                    f'Set ["*"] to allow everyone, or add specific user IDs.'
                )

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        try:
            await channel.start()
        except Exception as e:
            _logger().error("Failed to start channel {}: {}", name, e)

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            _logger().warning("No channels enabled")
            return

        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        tasks = []
        for name, channel in self.channels.items():
            _logger().info("Starting {} channel...", name)
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        _logger().info("Stopping all channels...")

        if self._dispatch_task:
            self._dispatch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._dispatch_task

        for name, channel in self.channels.items():
            try:
                await channel.stop()
                _logger().info("Stopped {} channel", name)
            except Exception as e:
                _logger().error("Error stopping {}: {}", name, e)

    @staticmethod
    def _fingerprint_content(content: str) -> str:
        normalized = " ".join(content.split())
        if not normalized:
            return ""
        return hashlib.sha1(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()

    def _should_suppress_outbound(self, msg: OutboundMessage) -> bool:
        """Suppress an exact-duplicate reply to the same source message.

        Duplicate suppression is scoped to a known origin message id so
        repeated content from separate turns is still delivered.
        """
        metadata = msg.metadata or {}
        if metadata.get("_progress"):
            return False
        fingerprint = self._fingerprint_content(msg.content)
        if not fingerprint:
            return False

        origin_message_id = metadata.get("origin_message_id")
        if isinstance(origin_message_id, str) and origin_message_id:
            key = (msg.channel, msg.chat_id, origin_message_id)
            if self._origin_reply_fingerprints.get(key) == fingerprint:
                return True
            self._origin_reply_fingerprints[key] = fingerprint

        message_id = metadata.get("message_id")
        if isinstance(message_id, str) and message_id:
            key = (msg.channel, msg.chat_id, message_id)
            self._origin_reply_fingerprints[key] = fingerprint

        return False

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        _logger().info("Outbound dispatcher started")

        # Buffer for messages that couldn't be processed during delta
        # coalescing (asyncio.Queue doesn't support push_front).
        pending: list[OutboundMessage] = []

        while True:
            try:
                if pending:
                    msg = pending.pop(0)
                else:
                    msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)

                channel = self.channels.get(msg.channel)
                if not channel:
                    _logger().warning("Unknown channel: {}", msg.channel)
                    continue

                if msg.metadata.get("_progress"):
                    if msg.metadata.get("_tool_hint") and not channel.send_tool_hints:
                        continue
                    if not msg.metadata.get("_tool_hint") and not channel.send_progress:
                        continue

                # Coalesce consecutive _stream_delta messages for the same
                # (channel, chat_id) to reduce edit-API calls when the LLM
                # generates faster than the channel can process.
                if msg.metadata.get("_stream_delta") and not msg.metadata.get("_stream_end"):
                    msg, extra_pending = self._coalesce_stream_deltas(msg)
                    pending.extend(extra_pending)

                if (
                    not msg.metadata.get("_stream_delta")
                    and not msg.metadata.get("_stream_end")
                    and not msg.metadata.get("_streamed")
                ):
                    if self._should_suppress_outbound(msg):
                        _logger().info(
                            "Suppressing duplicate outbound message to {}:{}",
                            msg.channel,
                            msg.chat_id,
                        )
                        continue
                await self._send_with_retry(channel, msg)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    @staticmethod
    async def _send_once(channel: BaseChannel, msg: OutboundMessage) -> None:
        """Send one outbound message without retry policy."""
        if msg.metadata.get("_stream_delta") or msg.metadata.get("_stream_end"):
            await channel.send_delta(msg.chat_id, msg.content, msg.metadata)
        elif not msg.metadata.get("_streamed"):
            # ``_streamed`` marks a final reply already delivered live via
            # send_delta — skip the plain send to avoid a duplicate message.
            await channel.send(msg)

    def _coalesce_stream_deltas(
        self, first_msg: OutboundMessage
    ) -> tuple[OutboundMessage, list[OutboundMessage]]:
        """Merge consecutive _stream_delta messages for the same (channel, chat_id).

        Returns:
            tuple of (merged_message, list_of_non_matching_messages)
        """
        target_key = (first_msg.channel, first_msg.chat_id)
        target_stream = (first_msg.metadata or {}).get("_stream_id")
        combined_content = first_msg.content
        final_metadata = dict(first_msg.metadata or {})
        non_matching: list[OutboundMessage] = []

        # Only merge consecutive deltas of the same stream segment. As soon
        # as we hit any other message, stop and hand that boundary back to
        # the dispatcher via `pending`.
        while True:
            try:
                next_msg = self.bus.outbound.get_nowait()
            except asyncio.QueueEmpty:
                break

            next_meta = next_msg.metadata or {}
            same_target = (next_msg.channel, next_msg.chat_id) == target_key
            same_stream = next_meta.get("_stream_id") == target_stream
            is_delta = bool(next_meta.get("_stream_delta"))
            is_end = bool(next_meta.get("_stream_end"))

            if same_target and same_stream and is_delta:
                combined_content += next_msg.content
                if is_end:
                    final_metadata["_stream_end"] = True
                    break
            else:
                # First non-matching message defines the coalescing boundary.
                non_matching.append(next_msg)
                break

        merged = OutboundMessage(
            channel=first_msg.channel,
            chat_id=first_msg.chat_id,
            content=combined_content,
            metadata=final_metadata,
        )
        return merged, non_matching

    async def _send_with_retry(self, channel: BaseChannel, msg: OutboundMessage) -> None:
        """Send a message with retry on failure using exponential backoff.

        Note: CancelledError is re-raised to allow graceful shutdown.
        """
        max_attempts = max(getattr(self.channels_config, "send_max_retries", 3), 1)

        for attempt in range(max_attempts):
            try:
                await self._send_once(channel, msg)
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if attempt == max_attempts - 1:
                    _logger().exception(
                        "Failed to send to {} after {} attempts", msg.channel, max_attempts
                    )
                    return
                delay = _SEND_RETRY_DELAYS[min(attempt, len(_SEND_RETRY_DELAYS) - 1)]
                _logger().warning(
                    "Send to {} failed (attempt {}/{}): {}, retrying in {}s",
                    msg.channel,
                    attempt + 1,
                    max_attempts,
                    type(e).__name__,
                    delay,
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    raise

    def get_channel(self, name: str) -> BaseChannel | None:
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        return {
            name: {"enabled": True, "running": channel.is_running}
            for name, channel in self.channels.items()
        }

    @property
    def enabled_channels(self) -> list[str]:
        return list(self.channels.keys())
