"""Tests for the schema-driven channels endpoint helpers.

Covers:
* ``resolve_config_model``: maps each ``XxxChannel`` to its ``XxxConfig``.
* ``inline_refs``: flattens nested model ``$ref``s (slack ``dm`` subtree).
* ``collect_secret_fields``: only flags **string-typed** secret-looking keys
  (so e.g. ``user_token_read_only: bool`` is excluded).
* ``GET /api/v1/partners/channels/schema`` integration: shape, snake_case
  property names, and that telegram/slack/discord schemas survive the trip.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers._partners_channel_schema import (
    all_channel_schemas,
    channel_schema_payload,
    collect_secret_fields,
    inline_refs,
    resolve_config_model,
)


class TestResolveConfigModel:
    def test_telegram_pairs_with_telegram_config(self) -> None:
        from deeptutor.partners.channels.telegram import TelegramChannel, TelegramConfig

        assert resolve_config_model(TelegramChannel) is TelegramConfig

    def test_slack_pairs_with_slack_config(self) -> None:
        from deeptutor.partners.channels.slack import SlackChannel, SlackConfig

        assert resolve_config_model(SlackChannel) is SlackConfig

    def test_discord_pairs_with_discord_config(self) -> None:
        from deeptutor.partners.channels.discord import DiscordChannel, DiscordConfig

        assert resolve_config_model(DiscordChannel) is DiscordConfig


class TestInlineRefs:
    def test_inlines_simple_def(self) -> None:
        schema = {
            "type": "object",
            "properties": {"dm": {"$ref": "#/$defs/SlackDMConfig"}},
            "$defs": {
                "SlackDMConfig": {
                    "type": "object",
                    "properties": {"enabled": {"type": "boolean"}},
                }
            },
        }
        out = inline_refs(schema)
        assert "$defs" not in out
        assert out["properties"]["dm"]["type"] == "object"
        assert out["properties"]["dm"]["properties"]["enabled"]["type"] == "boolean"

    def test_per_field_overrides_take_precedence(self) -> None:
        # Pydantic sometimes emits {"$ref": "...", "description": "..."}; the
        # description should override the referenced model's description.
        schema = {
            "type": "object",
            "properties": {
                "child": {"$ref": "#/$defs/Foo", "description": "override"},
            },
            "$defs": {
                "Foo": {"type": "object", "description": "original"},
            },
        }
        out = inline_refs(schema)
        assert out["properties"]["child"]["description"] == "override"


class TestCollectSecretFields:
    def test_flags_string_token_field(self) -> None:
        schema = {
            "properties": {
                "token": {"type": "string"},
                "enabled": {"type": "boolean"},
            }
        }
        assert collect_secret_fields(schema) == ["token"]

    def test_skips_boolean_with_secret_substring(self) -> None:
        # Slack's ``user_token_read_only`` is a flag, not a secret.
        schema = {
            "properties": {
                "user_token_read_only": {"type": "boolean"},
                "bot_token": {"type": "string"},
            }
        }
        assert collect_secret_fields(schema) == ["bot_token"]

    def test_walks_nested_objects(self) -> None:
        schema = {
            "properties": {
                "dm": {
                    "type": "object",
                    "properties": {"webhook_secret": {"type": "string"}},
                },
            }
        }
        assert collect_secret_fields(schema) == ["dm.webhook_secret"]

    def test_handles_nullable_strings(self) -> None:
        # Pydantic's ``Optional[str]`` becomes ``anyOf: [{type: string}, {type: null}]``.
        schema = {
            "properties": {
                "encrypt_key": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            }
        }
        assert collect_secret_fields(schema) == ["encrypt_key"]


class TestChannelSchemaPayload:
    def test_telegram_payload_shape(self) -> None:
        from deeptutor.partners.channels.telegram import TelegramChannel

        payload = channel_schema_payload(TelegramChannel)
        assert payload is not None
        assert payload["name"] == "telegram"
        assert payload["display_name"] == "Telegram"
        assert payload["secret_fields"] == ["token"]
        # Snake_case wire format (matches the storage form).
        props = payload["json_schema"]["properties"]
        assert "allow_from" in props and "allowFrom" not in props
        assert payload["default_config"]["enabled"] is False

    def test_slack_dm_subtree_inlined(self) -> None:
        from deeptutor.partners.channels.slack import SlackChannel

        payload = channel_schema_payload(SlackChannel)
        assert payload is not None
        dm = payload["json_schema"]["properties"]["dm"]
        assert dm["type"] == "object"
        assert "enabled" in dm["properties"]
        # Bool flags whose names contain "token" must NOT be flagged secret.
        assert "user_token_read_only" not in payload["secret_fields"]
        assert "bot_token" in payload["secret_fields"]


class TestEndpoint:
    @pytest.fixture
    def client(self) -> TestClient:
        # Build a minimal FastAPI app with just the partners router; the
        # ``/channels/schema`` endpoint doesn't touch the manager so no
        # fixturing of ``get_partner_manager`` is needed.
        from fastapi import FastAPI

        from deeptutor.api.routers import partners as partners_router

        app = FastAPI()
        app.include_router(partners_router.router, prefix="/api/v1/partners")
        return TestClient(app)

    def test_returns_channels_only(self, client: TestClient) -> None:
        res = client.get("/api/v1/partners/channels/schema")
        assert res.status_code == 200
        body = res.json()
        assert set(body.keys()) == {"channels"}
        # Telegram is always installed (no extra deps).
        assert "telegram" in body["channels"]

    def test_telegram_entry_has_secret_fields(self, client: TestClient) -> None:
        res = client.get("/api/v1/partners/channels/schema")
        tg = res.json()["channels"]["telegram"]
        assert tg["secret_fields"] == ["token"]
        assert "token" in tg["json_schema"]["properties"]

    def test_delivery_flags_are_per_channel(self, client: TestClient) -> None:
        res = client.get("/api/v1/partners/channels/schema")
        props = res.json()["channels"]["telegram"]["json_schema"]["properties"]
        assert "send_progress" in props
        assert "send_tool_hints" in props


class TestAllChannelSchemas:
    def test_returns_at_least_telegram(self) -> None:
        out = all_channel_schemas()
        assert "telegram" in out
        # Every payload has the four documented keys.
        for entry in out.values():
            assert {
                "name",
                "display_name",
                "default_config",
                "secret_fields",
                "json_schema",
            } <= entry.keys()
