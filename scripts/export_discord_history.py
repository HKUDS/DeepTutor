#!/usr/bin/env python
"""Export recent Discord server history with a read-only bot token.

The exporter only performs Discord HTTP ``GET`` requests.  It walks every
message-bearing channel visible to the bot, plus accessible active and archived
threads, and writes one local JSON file.  Attachments are represented by their
metadata and URLs; their binary contents are not downloaded.

Example::

    read -s "DISCORD_BOT_TOKEN?Discord bot token: "
    export DISCORD_BOT_TOKEN
    python scripts/export_discord_history.py --guild-id 123456789 --days 90
    unset DISCORD_BOT_TOKEN
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import httpx

DISCORD_API_BASE = "https://discord.com/api/v10"
TOKEN_ENV_VAR = "DISCORD_BOT_TOKEN"
DEFAULT_DAYS = 90
DEFAULT_OUTPUT_DIR = Path("data/user/discord_exports")
MAX_PAGE_SIZE = 100
MAX_RATE_LIMIT_RETRIES = 8

CHANNEL_TYPE_NAMES = {
    0: "GUILD_TEXT",
    1: "DM",
    2: "GUILD_VOICE",
    3: "GROUP_DM",
    4: "GUILD_CATEGORY",
    5: "GUILD_ANNOUNCEMENT",
    10: "ANNOUNCEMENT_THREAD",
    11: "PUBLIC_THREAD",
    12: "PRIVATE_THREAD",
    13: "GUILD_STAGE_VOICE",
    14: "GUILD_DIRECTORY",
    15: "GUILD_FORUM",
    16: "GUILD_MEDIA",
}
MESSAGE_CHANNEL_TYPES = {0, 2, 5, 13}
THREAD_TYPES = {10, 11, 12}
THREAD_PARENT_TYPES = {0, 5, 15, 16}


class DiscordAPIError(RuntimeError):
    """A Discord API response that could not be recovered."""

    def __init__(self, status_code: int, path: str, detail: str):
        super().__init__(f"Discord API {status_code} for {path}: {detail}")
        self.status_code = status_code
        self.path = path
        self.detail = detail


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a Discord ISO-8601 timestamp into an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _selected_fields(source: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    return {name: source[name] for name in names if name in source}


def normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    """Keep analysis-relevant message data without storing unrelated API fields."""
    author = message.get("author") or {}
    member = message.get("member") or {}
    username = author.get("username") or ""
    display_name = member.get("nick") or author.get("global_name") or username

    attachments = []
    for attachment in message.get("attachments") or []:
        attachments.append(
            _selected_fields(
                attachment,
                (
                    "id",
                    "filename",
                    "title",
                    "description",
                    "content_type",
                    "size",
                    "url",
                    "proxy_url",
                    "height",
                    "width",
                    "duration_secs",
                    "ephemeral",
                    "flags",
                ),
            )
        )

    reactions = []
    for reaction in message.get("reactions") or []:
        emoji = reaction.get("emoji") or {}
        reactions.append(
            {
                "count": reaction.get("count", 0),
                "count_details": reaction.get("count_details"),
                "emoji": _selected_fields(emoji, ("id", "name", "animated")),
            }
        )

    reference = message.get("message_reference") or None
    result: dict[str, Any] = {
        "id": str(message.get("id") or ""),
        "channel_id": str(message.get("channel_id") or ""),
        "timestamp": message.get("timestamp"),
        "edited_timestamp": message.get("edited_timestamp"),
        "author": {
            "id": str(author.get("id") or ""),
            "username": username,
            "global_name": author.get("global_name"),
            "display_name": display_name,
            "bot": bool(author.get("bot", False)),
        },
        "content": message.get("content") or "",
        "type": message.get("type", 0),
        "flags": message.get("flags", 0),
        "pinned": bool(message.get("pinned", False)),
        "tts": bool(message.get("tts", False)),
        "attachments": attachments,
        "embeds": message.get("embeds") or [],
        "components": message.get("components") or [],
        "sticker_items": message.get("sticker_items") or [],
        "reactions": reactions,
        "mentions": [
            {
                "id": str(mention.get("id") or ""),
                "username": mention.get("username") or "",
                "global_name": mention.get("global_name"),
            }
            for mention in (message.get("mentions") or [])
        ],
        "mention_roles": [str(role_id) for role_id in (message.get("mention_roles") or [])],
        "mention_everyone": bool(message.get("mention_everyone", False)),
        "message_reference": (
            _selected_fields(reference, ("message_id", "channel_id", "guild_id", "type"))
            if isinstance(reference, dict)
            else None
        ),
    }
    if "poll" in message:
        result["poll"] = message["poll"]
    return result


class DiscordHistoryExporter:
    """Read-only Discord API client for bounded history exports."""

    def __init__(
        self,
        token: str,
        guild_id: str,
        since: datetime,
        until: datetime,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        progress: Callable[[str], None] = print,
    ) -> None:
        self.token = token.removeprefix("Bot ").strip()
        self.guild_id = str(guild_id)
        self.since = since.astimezone(timezone.utc)
        self.until = until.astimezone(timezone.utc)
        self._sleep = sleep
        self._progress = progress
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=DISCORD_API_BASE,
            headers={
                "Authorization": f"Bot {self.token}",
                "User-Agent": "DiscordBot (https://github.com/HKUDS/DeepTutor, 1.0)",
            },
            timeout=30.0,
            follow_redirects=False,
        )
        self.warnings: list[str] = []

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> DiscordHistoryExporter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue one GET request and honor Discord's response rate-limit data."""
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            response = self.client.request("GET", path, params=params)
            if response.status_code == 429:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                retry_after = payload.get("retry_after") or response.headers.get("Retry-After") or 1
                try:
                    delay = max(float(retry_after), 0.0)
                except (TypeError, ValueError):
                    delay = 1.0
                if attempt >= MAX_RATE_LIMIT_RETRIES:
                    raise DiscordAPIError(429, path, "rate-limit retries exhausted")
                self._progress(f"Discord rate limit reached; retrying in {delay:.2f}s")
                self._sleep(delay)
                continue

            if response.status_code >= 400:
                try:
                    payload = response.json()
                    detail = str(payload.get("message") or payload)
                except ValueError:
                    detail = response.text[:300] or response.reason_phrase
                raise DiscordAPIError(response.status_code, path, detail)

            try:
                payload = response.json()
            except ValueError as exc:
                raise DiscordAPIError(response.status_code, path, "response was not JSON") from exc

            remaining = response.headers.get("X-RateLimit-Remaining")
            reset_after = response.headers.get("X-RateLimit-Reset-After")
            if remaining == "0" and reset_after:
                try:
                    self._sleep(max(float(reset_after), 0.0))
                except ValueError:
                    pass
            return payload

        raise AssertionError("unreachable")

    def fetch_messages(self, channel_id: str) -> list[dict[str, Any]]:
        """Fetch messages newest-to-oldest until the configured lower bound."""
        messages: list[dict[str, Any]] = []
        seen: set[str] = set()
        before: str | None = None

        while True:
            params: dict[str, Any] = {"limit": MAX_PAGE_SIZE}
            if before:
                params["before"] = before
            page = self._request_json(f"/channels/{channel_id}/messages", params=params)
            if not isinstance(page, list) or not page:
                break

            oldest_timestamp: datetime | None = None
            for message in page:
                timestamp = parse_timestamp(message.get("timestamp"))
                if timestamp is None:
                    continue
                if oldest_timestamp is None or timestamp < oldest_timestamp:
                    oldest_timestamp = timestamp
                message_id = str(message.get("id") or "")
                if self.since <= timestamp <= self.until and message_id not in seen:
                    messages.append(normalize_message(message))
                    seen.add(message_id)

            next_before = str(page[-1].get("id") or "")
            if (
                len(page) < MAX_PAGE_SIZE
                or oldest_timestamp is None
                or oldest_timestamp < self.since
                or not next_before
                or next_before == before
            ):
                break
            before = next_before

        messages.sort(key=lambda item: (item.get("timestamp") or "", item.get("id") or ""))
        return messages

    def _list_public_archived_threads(self, parent_id: str) -> list[dict[str, Any]]:
        threads: list[dict[str, Any]] = []
        before: str | None = None
        while True:
            params: dict[str, Any] = {"limit": MAX_PAGE_SIZE}
            if before:
                params["before"] = before
            payload = self._request_json(
                f"/channels/{parent_id}/threads/archived/public",
                params=params,
            )
            page = payload.get("threads") or []
            if not page:
                break

            reached_cutoff = False
            for thread in page:
                archived_at = parse_timestamp(
                    (thread.get("thread_metadata") or {}).get("archive_timestamp")
                )
                if archived_at is None or archived_at >= self.since:
                    threads.append(thread)
                else:
                    reached_cutoff = True

            archive_value = (page[-1].get("thread_metadata") or {}).get("archive_timestamp")
            if reached_cutoff or not payload.get("has_more") or not archive_value:
                break
            if archive_value == before:
                break
            before = archive_value
        return threads

    def _list_joined_private_archived_threads(self, parent_id: str) -> list[dict[str, Any]]:
        threads: list[dict[str, Any]] = []
        before: str | None = None
        while True:
            params: dict[str, Any] = {"limit": MAX_PAGE_SIZE}
            if before:
                params["before"] = before
            payload = self._request_json(
                f"/channels/{parent_id}/users/@me/threads/archived/private",
                params=params,
            )
            page = payload.get("threads") or []
            if not page:
                break
            for thread in page:
                archived_at = parse_timestamp(
                    (thread.get("thread_metadata") or {}).get("archive_timestamp")
                )
                if archived_at is None or archived_at >= self.since:
                    threads.append(thread)
            next_before = str(page[-1].get("id") or "")
            if not payload.get("has_more") or not next_before or next_before == before:
                break
            before = next_before
        return threads

    def discover_threads(self, channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Discover every active/public archived/joined private thread the bot can access."""
        by_id: dict[str, dict[str, Any]] = {}
        try:
            active = self._request_json(f"/guilds/{self.guild_id}/threads/active")
            for thread in active.get("threads") or []:
                by_id[str(thread.get("id"))] = thread
        except DiscordAPIError as exc:
            self.warnings.append(f"Could not enumerate active threads: {exc}")

        for channel in channels:
            channel_id = str(channel.get("id") or "")
            channel_type = channel.get("type")
            if not channel_id or channel_type not in THREAD_PARENT_TYPES:
                continue
            try:
                for thread in self._list_public_archived_threads(channel_id):
                    by_id[str(thread.get("id"))] = thread
            except DiscordAPIError as exc:
                if exc.status_code not in {403, 404}:
                    raise
                self.warnings.append(
                    f"Could not enumerate public archived threads under {channel_id}: {exc.detail}"
                )

            if channel_type != 0:
                continue
            try:
                for thread in self._list_joined_private_archived_threads(channel_id):
                    by_id[str(thread.get("id"))] = thread
            except DiscordAPIError as exc:
                if exc.status_code not in {403, 404}:
                    raise
                self.warnings.append(
                    f"Could not enumerate joined private threads under {channel_id}: {exc.detail}"
                )

        return list(by_id.values())

    @staticmethod
    def _channel_record(
        channel: dict[str, Any],
        channels_by_id: dict[str, dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        channel_id = str(channel.get("id") or "")
        channel_type = int(channel.get("type", -1))
        is_thread = channel_type in THREAD_TYPES
        parent_id = str(channel.get("parent_id") or "") or None
        parent = channels_by_id.get(parent_id or "")

        category: dict[str, Any] | None = None
        parent_channel_name: str | None = None
        if is_thread and parent:
            parent_channel_name = parent.get("name")
            category = channels_by_id.get(str(parent.get("parent_id") or ""))
        elif parent and parent.get("type") == 4:
            category = parent

        parts = []
        if category and category.get("name"):
            parts.append(str(category["name"]))
        if parent_channel_name:
            parts.append(parent_channel_name)
        if channel.get("name"):
            parts.append(str(channel["name"]))

        thread_metadata = channel.get("thread_metadata") or {}
        return {
            "id": channel_id,
            "name": channel.get("name") or channel_id,
            "path": " / ".join(parts) or channel_id,
            "type": channel_type,
            "type_name": CHANNEL_TYPE_NAMES.get(channel_type, f"UNKNOWN_{channel_type}"),
            "parent_id": parent_id,
            "parent_name": parent_channel_name,
            "category_id": str(category.get("id")) if category else None,
            "category_name": category.get("name") if category else None,
            "is_thread": is_thread,
            "thread_archived": thread_metadata.get("archived") if is_thread else None,
            "message_count": len(messages),
            "messages": messages,
        }

    def export(self, *, include_threads: bool = True) -> dict[str, Any]:
        bot = self._request_json("/users/@me")
        guild = self._request_json(f"/guilds/{self.guild_id}")
        raw_channels = self._request_json(f"/guilds/{self.guild_id}/channels")
        if not isinstance(raw_channels, list):
            raise DiscordAPIError(200, f"/guilds/{self.guild_id}/channels", "unexpected body")

        threads = self.discover_threads(raw_channels) if include_threads else []
        channels_by_id = {str(channel.get("id")): channel for channel in raw_channels}
        channels_by_id.update({str(thread.get("id")): thread for thread in threads})

        sources = [c for c in raw_channels if c.get("type") in MESSAGE_CHANNEL_TYPES]
        sources.extend(thread for thread in threads if thread.get("type") in THREAD_TYPES)
        sources.sort(key=lambda item: (int(item.get("position", 0)), str(item.get("id") or "")))

        exported_channels: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for index, channel in enumerate(sources, start=1):
            channel_id = str(channel.get("id") or "")
            channel_name = str(channel.get("name") or channel_id)
            try:
                messages = self.fetch_messages(channel_id)
            except DiscordAPIError as exc:
                if exc.status_code not in {403, 404}:
                    raise
                skipped.append(
                    {
                        "id": channel_id,
                        "name": channel_name,
                        "status_code": exc.status_code,
                        "reason": exc.detail,
                    }
                )
                self._progress(
                    f"[{index}/{len(sources)}] skipped #{channel_name}: {exc.status_code} {exc.detail}"
                )
                continue

            record = self._channel_record(channel, channels_by_id, messages)
            exported_channels.append(record)
            self._progress(f"[{index}/{len(sources)}] {record['path']}: {len(messages)} messages")

        exported_channels.sort(key=lambda item: (item["path"].casefold(), item["id"]))
        message_count = sum(channel["message_count"] for channel in exported_channels)
        human_messages = [
            message
            for channel in exported_channels
            for message in channel["messages"]
            if not message["author"]["bot"]
        ]
        if len(human_messages) >= 5 and all(
            not message["content"]
            and not message["attachments"]
            and not message["embeds"]
            and not message["components"]
            and not message["sticker_items"]
            for message in human_messages
        ):
            self.warnings.append(
                "All sampled human messages have empty content fields. "
                "Check that Message Content Intent is enabled for the bot."
            )

        return {
            "schema_version": 1,
            "source": "Discord HTTP API v10",
            "exported_at": isoformat_utc(utc_now()),
            "range": {
                "from": isoformat_utc(self.since),
                "to": isoformat_utc(self.until),
            },
            "guild": {
                "id": self.guild_id,
                "name": guild.get("name"),
            },
            "bot": {
                "id": str(bot.get("id") or ""),
                "username": bot.get("username"),
            },
            "privacy": {
                "usernames_anonymized": False,
                "attachment_files_downloaded": False,
                "bot_token_stored": False,
            },
            "coverage": {
                "public_channels": "all message-bearing channels visible to the bot",
                "threads": (
                    "active, public archived, and joined private archived threads"
                    if include_threads
                    else "not requested"
                ),
                "private_archived_threads": (
                    "joined threads only; unjoined private threads require elevated permissions"
                    if include_threads
                    else "not requested"
                ),
            },
            "summary": {
                "server_channels_discovered": len(raw_channels),
                "threads_discovered": len(threads),
                "message_channels_exported": len(exported_channels),
                "message_channels_skipped": len(skipped),
                "messages_exported": message_count,
            },
            "warnings": self.warnings,
            "skipped_channels": skipped,
            "channels": exported_channels,
        }


def default_output_path(guild_id: str, since: datetime, until: datetime) -> Path:
    stamp = until.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    start = since.astimezone(timezone.utc).strftime("%Y%m%d")
    return DEFAULT_OUTPUT_DIR / f"discord_{guild_id}_{start}_{stamp}.json"


def write_export(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary_path.replace(output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guild-id", required=True, help="Discord server (guild) ID.")
    parser.add_argument(
        "--days",
        type=positive_int,
        default=DEFAULT_DAYS,
        help=f"Number of recent days to export (default: {DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON file. Defaults under data/user/discord_exports/.",
    )
    parser.add_argument(
        "--no-threads",
        action="store_true",
        help="Skip active and archived Discord threads/forum posts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        parser.error(
            f"{TOKEN_ENV_VAR} is not set. Keep the token local and pass it through the environment."
        )

    until = utc_now()
    since = until - timedelta(days=args.days)
    output_path = args.output or default_output_path(args.guild_id, since, until)
    print(f"Exporting Discord guild {args.guild_id}")
    print(f"Range: {isoformat_utc(since)} to {isoformat_utc(until)}")

    try:
        with DiscordHistoryExporter(token, args.guild_id, since, until) as exporter:
            payload = exporter.export(include_threads=not args.no_threads)
        write_export(payload, output_path)
    except (DiscordAPIError, httpx.HTTPError) as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1

    summary = payload["summary"]
    print(
        f"Done: {summary['messages_exported']} messages from "
        f"{summary['message_channels_exported']} channels/threads"
    )
    if summary["message_channels_skipped"]:
        print(f"Skipped: {summary['message_channels_skipped']} inaccessible channels/threads")
    for warning in payload["warnings"]:
        print(f"Warning: {warning}")
    print(f"Output: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
