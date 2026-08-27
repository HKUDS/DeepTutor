from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import httpx


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "export_discord_history.py"
    module_name = "export_discord_history_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


exporter_module = _load_module()


def _message(message_id: int, timestamp: datetime, *, content: str = "hello") -> dict[str, Any]:
    return {
        "id": str(message_id),
        "channel_id": "10",
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "author": {
            "id": "99",
            "username": "alice",
            "global_name": "Alice",
            "bot": False,
        },
        "member": {"nick": "Alice in Server"},
        "content": content,
        "attachments": [],
        "embeds": [],
        "components": [],
        "mentions": [],
        "mention_roles": [],
    }


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url=exporter_module.DISCORD_API_BASE,
        transport=httpx.MockTransport(handler),
    )


def test_fetch_messages_stops_at_cutoff_and_sorts_chronologically() -> None:
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    recent = [_message(index, now - timedelta(hours=index)) for index in range(1, 101)]
    old = _message(101, now - timedelta(days=91), content="too old")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        assert request.method == "GET"
        calls += 1
        return httpx.Response(200, json=recent if calls == 1 else [old])

    with _client(handler) as client:
        exporter = exporter_module.DiscordHistoryExporter(
            "secret",
            "1",
            now - timedelta(days=90),
            now,
            client=client,
            progress=lambda _message: None,
        )
        messages = exporter.fetch_messages("10")

    assert calls == 2
    assert len(messages) == 100
    assert messages[0]["id"] == "100"
    assert messages[-1]["id"] == "1"
    assert messages[-1]["author"]["display_name"] == "Alice in Server"


def test_export_covers_text_channels_and_active_threads() -> None:
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    routes: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        routes.append((request.method, request.url.path))
        responses: dict[str, Any] = {
            "/api/v10/users/@me": {"id": "7", "username": "reader"},
            "/api/v10/guilds/1": {"id": "1", "name": "Community"},
            "/api/v10/guilds/1/channels": [
                {"id": "9", "name": "COMMUNITY", "type": 4, "position": 0},
                {
                    "id": "10",
                    "name": "general",
                    "type": 0,
                    "position": 1,
                    "parent_id": "9",
                },
            ],
            "/api/v10/guilds/1/threads/active": {
                "threads": [
                    {
                        "id": "20",
                        "name": "topic",
                        "type": 11,
                        "parent_id": "10",
                        "thread_metadata": {"archived": False},
                    }
                ]
            },
            "/api/v10/channels/10/threads/archived/public": {
                "threads": [],
                "has_more": False,
            },
            "/api/v10/channels/10/users/@me/threads/archived/private": {
                "threads": [],
                "has_more": False,
            },
            "/api/v10/channels/10/messages": [_message(1, now)],
            "/api/v10/channels/20/messages": [
                {**_message(2, now), "channel_id": "20", "content": "thread message"}
            ],
        }
        return httpx.Response(200, json=responses[request.url.path])

    with _client(handler) as client:
        exporter = exporter_module.DiscordHistoryExporter(
            "secret",
            "1",
            now - timedelta(days=90),
            now,
            client=client,
            progress=lambda _message: None,
        )
        payload = exporter.export()

    assert payload["summary"] == {
        "server_channels_discovered": 2,
        "threads_discovered": 1,
        "message_channels_exported": 2,
        "message_channels_skipped": 0,
        "messages_exported": 2,
    }
    assert [channel["path"] for channel in payload["channels"]] == [
        "COMMUNITY / general",
        "COMMUNITY / general / topic",
    ]
    assert payload["privacy"]["bot_token_stored"] is False
    assert all("secret" not in json.dumps(value) for value in payload.values())
    assert all(method == "GET" for method, _path in routes)
    assert {
        "/api/v10/channels/10/messages",
        "/api/v10/channels/20/messages",
        "/api/v10/guilds/1/threads/active",
    } <= {path for _method, path in routes}


def test_fetch_messages_reports_permission_error() -> None:
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(403, json={"message": "Missing Access"})
        raise AssertionError(request.url)

    with _client(handler) as client:
        exporter = exporter_module.DiscordHistoryExporter(
            "secret",
            "1",
            now - timedelta(days=90),
            now,
            client=client,
            progress=lambda _message: None,
        )
        try:
            exporter.fetch_messages("10")
        except exporter_module.DiscordAPIError as exc:
            assert exc.status_code == 403
            assert exc.detail == "Missing Access"
        else:
            raise AssertionError("expected DiscordAPIError")


def test_public_archived_threads_stop_after_time_cutoff() -> None:
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    recent_archive = (now - timedelta(days=2)).isoformat()
    old_archive = (now - timedelta(days=100)).isoformat()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "threads": [
                    {
                        "id": "20",
                        "name": "recent",
                        "type": 11,
                        "thread_metadata": {"archive_timestamp": recent_archive},
                    },
                    {
                        "id": "19",
                        "name": "old",
                        "type": 11,
                        "thread_metadata": {"archive_timestamp": old_archive},
                    },
                ],
                "has_more": True,
            },
        )

    with _client(handler) as client:
        exporter = exporter_module.DiscordHistoryExporter(
            "secret",
            "1",
            now - timedelta(days=90),
            now,
            client=client,
            progress=lambda _message: None,
        )
        threads = exporter._list_public_archived_threads("10")

    assert calls == 1
    assert [thread["id"] for thread in threads] == ["20"]


def test_rate_limit_uses_retry_after_then_retries() -> None:
    calls = 0
    sleeps: list[float] = []
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"retry_after": 0.25})
        return httpx.Response(200, json=[])

    with _client(handler) as client:
        exporter = exporter_module.DiscordHistoryExporter(
            "secret",
            "1",
            now - timedelta(days=90),
            now,
            client=client,
            sleep=sleeps.append,
            progress=lambda _message: None,
        )
        assert exporter.fetch_messages("10") == []

    assert calls == 2
    assert sleeps == [0.25]


def test_default_output_is_under_ignored_user_data() -> None:
    until = datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)
    since = until - timedelta(days=90)

    output = exporter_module.default_output_path("123456789", since, until)

    assert output.parent == Path("data/user/discord_exports")
    assert output.name.startswith("discord_123456789_")
