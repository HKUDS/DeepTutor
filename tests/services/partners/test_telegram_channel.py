"""Unit tests for the Telegram inbound chat and topic response policy."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pydantic import ValidationError
import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.telegram import TelegramChannel, TelegramConfig


def _make_channel(**overrides) -> TelegramChannel:
    defaults = {
        "enabled": True,
        "token": "secret-token-123",
        "allow_from": ["*"],
        "group_policy": "mention",
    }
    defaults.update(overrides)
    config = TelegramConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    channel = TelegramChannel(config, bus)
    channel._bot_user_id = 999
    channel._bot_username = "tutorbot"
    return channel


def _group_message(
    *,
    chat_id: int = -1003921765626,
    topic_id: int | None = None,
    text: str = "hello",
    reply_to_bot: bool = False,
) -> SimpleNamespace:
    reply_from = SimpleNamespace(id=999) if reply_to_bot else SimpleNamespace(id=42)
    return SimpleNamespace(
        chat=SimpleNamespace(type="supergroup"),
        chat_id=chat_id,
        message_thread_id=topic_id,
        message_id=1000,
        text=text,
        caption=None,
        entities=None,
        caption_entities=None,
        reply_to_message=SimpleNamespace(message_id=900, from_user=reply_from),
    )


class TestTelegramConfig:
    def test_chat_policies_default_to_empty(self) -> None:
        config = TelegramConfig()

        assert config.group_policy == "mention"
        assert config.chat_policies == []

    def test_accepts_chat_policy_rules(self) -> None:
        config = TelegramConfig.model_validate(
            {
                "groupPolicy": "mention",
                "chatPolicies": [
                    {
                        "chatId": -1003921765626,
                        "policy": "topics_only",
                        "allowedTopics": [1, 44, 115],
                    }
                ],
            }
        )

        assert config.chat_policies[0].chat_id == -1003921765626
        assert config.chat_policies[0].policy == "topics_only"
        assert config.chat_policies[0].allowed_topics == [1, 44, 115]

    def test_topics_only_requires_topics(self) -> None:
        with pytest.raises(ValidationError, match="at least one allowed topic"):
            TelegramConfig(chat_policies=[{"chat_id": -100, "policy": "topics_only"}])

    def test_policy_values_are_not_camel_case(self) -> None:
        with pytest.raises(ValidationError, match="topics_only"):
            TelegramConfig.model_validate(
                {"chat_policies": [{"chat_id": -100, "policy": "topicsOnly"}]}
            )

    def test_default_config_exposes_chat_policies(self) -> None:
        default = TelegramChannel.default_config()

        assert default["chatPolicies"] == []


class TestGroupMessagePolicy:
    def test_default_mention_policy_ignores_plain_message(self) -> None:
        channel = _make_channel()

        assert asyncio.run(channel._is_group_message_for_bot(_group_message())) is False

    def test_global_open_still_applies_to_unlisted_chat(self) -> None:
        channel = _make_channel(
            group_policy="open",
            chat_policies=[{"chat_id": -100, "policy": "mention"}],
        )

        assert asyncio.run(channel._is_group_message_for_bot(_group_message())) is True

    def test_chat_open_overrides_global_mention(self) -> None:
        channel = _make_channel(chat_policies=[{"chat_id": -1003921765626, "policy": "open"}])

        assert asyncio.run(channel._is_group_message_for_bot(_group_message())) is True

    def test_chat_mention_overrides_global_open(self) -> None:
        channel = _make_channel(
            group_policy="open",
            chat_policies=[{"chat_id": -1003921765626, "policy": "mention"}],
        )

        assert asyncio.run(channel._is_group_message_for_bot(_group_message())) is False

    def test_first_matching_chat_policy_wins(self) -> None:
        channel = _make_channel(
            chat_policies=[
                {"chat_id": -1003921765626, "policy": "mention"},
                {"chat_id": -1003921765626, "policy": "open"},
            ]
        )

        assert asyncio.run(channel._is_group_message_for_bot(_group_message())) is False

    def test_topics_only_allows_allowlisted_topic_without_mention(self) -> None:
        channel = _make_channel(
            chat_policies=[
                {
                    "chat_id": -1003921765626,
                    "policy": "topics_only",
                    "allowed_topics": [1, 44, 115],
                }
            ]
        )

        assert asyncio.run(channel._is_group_message_for_bot(_group_message(topic_id=44))) is True

    def test_topics_only_ignores_general_topic(self) -> None:
        channel = _make_channel(
            chat_policies=[
                {
                    "chat_id": -1003921765626,
                    "policy": "topics_only",
                    "allowed_topics": [1, 44, 115],
                }
            ]
        )

        assert (
            asyncio.run(channel._is_group_message_for_bot(_group_message(topic_id=None))) is False
        )

    def test_topics_only_ignores_unlisted_topic(self) -> None:
        channel = _make_channel(
            chat_policies=[
                {
                    "chat_id": -1003921765626,
                    "policy": "topics_only",
                    "allowed_topics": [1, 44, 115],
                }
            ]
        )

        assert asyncio.run(channel._is_group_message_for_bot(_group_message(topic_id=116))) is False

    def test_topics_only_still_accepts_mention_in_nonallowed_topic(self) -> None:
        channel = _make_channel(
            chat_policies=[
                {
                    "chat_id": -1003921765626,
                    "policy": "topics_only",
                    "allowed_topics": [44],
                }
            ]
        )
        message = _group_message(topic_id=116, text="@tutorbot please answer")

        assert asyncio.run(channel._is_group_message_for_bot(message)) is True

    def test_mention_policy_accepts_reply_to_bot(self) -> None:
        channel = _make_channel()

        assert (
            asyncio.run(channel._is_group_message_for_bot(_group_message(reply_to_bot=True)))
            is True
        )

    def test_private_chat_ignores_chat_policy(self) -> None:
        channel = _make_channel(chat_policies=[{"chat_id": 42, "policy": "mention"}])
        message = _group_message(chat_id=42)
        message.chat.type = "private"

        assert asyncio.run(channel._is_group_message_for_bot(message)) is True

    def test_allow_from_remains_orthogonal(self) -> None:
        channel = _make_channel(
            allow_from=[],
            chat_policies=[{"chat_id": -1003921765626, "policy": "open"}],
        )

        assert channel.is_allowed("42") is False


def test_channel_schema_inlines_chat_policy_items() -> None:
    from deeptutor.api.routers._partners_channel_schema import channel_schema_payload

    payload = channel_schema_payload(TelegramChannel)
    rule_schema = payload["json_schema"]["properties"]["chat_policies"]["items"]

    assert rule_schema["type"] == "object"
    assert {"chat_id", "policy", "allowed_topics"} <= set(rule_schema["properties"])
