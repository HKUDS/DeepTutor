"""Native rich-message delivery, with no network or real bot credentials."""

import json
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from telegram import Bot, ReplyParameters, Update
from telegram.error import BadRequest, EndPointNotFound, Forbidden, RetryAfter, TimedOut
from telegram.request import BaseRequest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import deliver_outbound
from deeptutor.partners.channels.manager import send_with_retry
from deeptutor.partners.channels.telegram import TELEGRAM_REPLY_CONTEXT_MAX_LEN, TelegramChannel

MARKDOWN = "# Progress\n\n**Summary**\n\n| Area | Action |\n|---|---|\n| Journal | Save goals |\n\n```python\nprint('**literal**')\n```"


class CaptureRequest(BaseRequest):
    """Exercise real SDK serialization while keeping all requests in memory."""

    def __init__(self):
        self.calls = []

    @property
    def read_timeout(self):
        return 5

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append((endpoint, request_data.json_parameters if request_data else {}))
        result = {"message_id": 99, "date": 1, "chat": {"id": 123, "type": "private"}}
        if endpoint == "getMe":
            result = {"id": 99, "is_bot": True, "first_name": "Synthetic"}
        return 200, json.dumps({"ok": True, "result": result}).encode()


class RichMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.channel = TelegramChannel({"token": "test-token"}, MessageBus())
        self.bot = SimpleNamespace(
            do_api_request=AsyncMock(return_value={"message_id": 99}),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
            edit_message_text=AsyncMock(),
            send_message_draft=AsyncMock(),
        )
        self.channel._app = SimpleNamespace(bot=self.bot)

    async def test_public_sdk_serializes_native_payload_without_private_hooks(self):
        request = CaptureRequest()
        async with Bot("123456:SYNTHETIC_TOKEN", request=request) as bot:
            self.channel._app = SimpleNamespace(bot=bot)
            await self.channel._send_text(
                123, MARKDOWN, ReplyParameters(message_id=7), {"message_thread_id": 4}
            )
        endpoint, payload = request.calls[-1]
        self.assertEqual(endpoint, "sendRichMessage")
        self.assertEqual(json.loads(payload["rich_message"]), {"markdown": MARKDOWN})
        self.assertEqual(json.loads(payload["reply_parameters"])["message_id"], 7)
        self.assertEqual(payload["message_thread_id"], "4")

    async def test_final_reply_sends_original_markdown_as_native_rich_message(self):
        reply = ReplyParameters(message_id=7)
        await self.channel._send_text(123, MARKDOWN, reply, {"message_thread_id": 4})
        self.bot.do_api_request.assert_awaited_once_with(
            "sendRichMessage",
            api_kwargs={
                "chat_id": 123,
                "rich_message": {"markdown": MARKDOWN},
                "reply_parameters": reply,
                "message_thread_id": 4,
            },
        )
        self.bot.send_message.assert_not_awaited()

    async def test_normal_send_does_not_cut_a_table_at_4000_characters(self):
        markdown = "| Area | Notes |\n|---|---|\n" + "| A | " + "long note " * 650 + " |"
        await self.channel.send(
            OutboundMessage(channel="telegram", chat_id="123", content=markdown)
        )
        calls = self.bot.do_api_request.await_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs["api_kwargs"]["rich_message"]["markdown"], markdown)
        self.bot.send_message_draft.assert_not_awaited()

    async def test_completed_stream_edits_same_message_to_native_rich_format(self):
        await self.channel.send_delta("123", MARKDOWN, {"_stream_id": "s1"})
        await self.channel.send_delta("123", "", {"_stream_id": "s1", "_stream_end": True})
        self.bot.do_api_request.assert_awaited_once_with(
            "editMessageText",
            api_kwargs={"chat_id": 123, "message_id": 99, "rich_message": {"markdown": MARKDOWN}},
        )
        self.assertNotIn("123", self.channel._stream_bufs)

    async def test_long_stream_keeps_preview_bounded_and_final_markdown_whole(self):
        markdown = MARKDOWN + "\n\n" + "x" * 6000
        await self.channel.send_delta("123", markdown, {"_stream_id": "s1"})
        self.assertLessEqual(len(self.bot.send_message.await_args.kwargs["text"]), 4000)
        await self.channel.send_delta("123", "", {"_stream_id": "s1", "_stream_end": True})
        self.assertEqual(
            self.bot.do_api_request.await_args.kwargs["api_kwargs"]["rich_message"]["markdown"],
            markdown,
        )

    async def test_missing_endpoint_falls_back_and_remembers_capability(self):
        self.bot.do_api_request.side_effect = EndPointNotFound("Endpoint not found")
        await self.channel._send_text(123, "**first**")
        await self.channel._send_text(123, "**second**")
        self.assertEqual(self.bot.do_api_request.await_count, 1)
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.assertEqual(self.bot.send_message.await_args.kwargs["text"], "<b>second</b>")

    async def test_format_rejection_falls_back_only_for_this_message(self):
        self.bot.do_api_request.side_effect = [
            BadRequest("can't parse rich message"),
            {"message_id": 100},
        ]
        await self.channel._send_text(123, "**first**")
        await self.channel._send_text(123, "**second**")
        self.assertEqual(self.bot.do_api_request.await_count, 2)
        self.bot.send_message.assert_awaited_once()

    async def test_timeout_and_permission_errors_never_trigger_another_send(self):
        for error in (
            TimedOut(),
            Forbidden("Forbidden"),
            BadRequest("Chat not found"),
            BadRequest("Message text is empty"),
        ):
            with self.subTest(error=type(error).__name__):
                self.bot.do_api_request.reset_mock(side_effect=True)
                self.bot.do_api_request.side_effect = error
                with self.assertRaises(type(error)):
                    await self.channel._send_text(123, MARKDOWN)
                self.bot.do_api_request.assert_awaited_once()
                self.bot.send_message.assert_not_awaited()

    async def test_rich_edit_not_modified_does_not_create_duplicate(self):
        await self.channel.send_delta("123", MARKDOWN, {"_stream_id": "s1"})
        self.bot.do_api_request.side_effect = BadRequest("Message is not modified")
        await self.channel.send_delta("123", "", {"_stream_id": "s1", "_stream_end": True})
        self.bot.send_message.assert_awaited_once()
        self.bot.edit_message_text.assert_not_awaited()
        self.assertNotIn("123", self.channel._stream_bufs)

    async def test_final_edit_format_fallback_preserves_every_long_reply_word(self):
        async def reject_html(**kwargs):
            if kwargs.get("parse_mode") == "HTML":
                raise BadRequest("Can't parse entities")
            return SimpleNamespace(message_id=99)

        self.bot.send_message.side_effect = reject_html
        self.bot.edit_message_text.side_effect = reject_html
        self.bot.do_api_request.side_effect = BadRequest("Can't parse rich message")
        words = [f"w{i}" for i in range(1800)]
        markdown = MARKDOWN + "\n\n" + " ".join(words)

        await self.channel.send_delta("123", markdown, {"_stream_id": "s1"})
        await self.channel.send_delta("123", "", {"_stream_id": "s1", "_stream_end": True})

        edits = [
            call.kwargs
            for call in self.bot.edit_message_text.await_args_list
            if "parse_mode" not in call.kwargs
        ]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["message_id"], 99)
        # The first plain send was the preview; only subsequent sends are final chunks.
        extra_chunks = [
            call.kwargs["text"]
            for call in self.bot.send_message.await_args_list
            if "parse_mode" not in call.kwargs
        ][1:]
        self.assertGreaterEqual(len(extra_chunks), 2)
        final_chunks = [edits[0]["text"], *extra_chunks]
        self.assertTrue(all(len(chunk) <= 4000 for chunk in final_chunks))
        self.assertEqual(re.findall(r"w\d+", " ".join(final_chunks)), words)
        self.assertNotIn("123", self.channel._stream_bufs)

    async def test_rich_reply_update_preserves_reference_context(self):
        self.channel.config.allow_from = ["123"]
        self.channel.bus.publish_inbound = AsyncMock()
        self.channel._start_typing = lambda chat_id: None
        # Official Message.rich_message / RichBlockParagraph / RichText shapes.
        update = Update.de_json(
            {
                "update_id": 1,
                "message": {
                    "message_id": 8,
                    "date": 2,
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 123, "is_bot": False, "first_name": "Alice"},
                    "text": "Explain that answer",
                    "reply_to_message": {
                        "message_id": 7,
                        "date": 1,
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 99, "is_bot": True, "first_name": "Synthetic"},
                        "rich_message": {
                            "blocks": [{"type": "paragraph", "text": "Previous answer: 42"}]
                        },
                    },
                },
            },
            None,
        )

        await self.channel._on_message(update, None)

        message = self.channel.bus.publish_inbound.await_args.args[0]
        self.assertEqual(message.content, "[Reply to: Previous answer: 42]\nExplain that answer")
        self.assertEqual(message.metadata["reply_to_message_id"], 7)

    def test_rich_reply_context_flattens_nested_blocks_and_inline_arrays(self):
        rich = {
            "blocks": [
                {"type": "heading", "text": ["Plan ", {"type": "bold", "text": "one"}]},
                {
                    "type": "list",
                    "items": [{"label": "1.", "blocks": [{"type": "paragraph", "text": "First"}]}],
                },
                {
                    "type": "blockquote",
                    "blocks": [{"type": "paragraph", "text": "Quoted"}],
                    "credit": "Author",
                },
                {
                    "type": "details",
                    "summary": "More",
                    "blocks": [
                        {
                            "type": "table",
                            "cells": [
                                [{"text": "Area"}, {"text": "Notes"}],
                                [
                                    {"text": {"type": "bold", "text": "Save"}},
                                    {"text": ["goals", {"type": "italic", "text": " today"}]},
                                ],
                            ],
                            "caption": "Table caption",
                        }
                    ],
                },
                {
                    "type": "photo",
                    "photo": [{"file_id": "not display text"}],
                    "caption": {"text": "Photo caption", "credit": "Photographer"},
                },
                {"type": "mathematical_expression", "expression": "x^2"},
                {
                    "type": "paragraph",
                    "text": [
                        {"type": "custom_emoji", "alternative_text": "🙂"},
                        {"type": "url", "text": " Link", "url": "https://example.com/hidden"},
                    ],
                },
            ]
        }
        expected = (
            "[Reply to: Plan one\nFirst\nQuoted\nAuthor\nMore\nArea\tNotes\n"
            "Save\tgoals today\nTable caption\nPhoto caption\nPhotographer\nx^2\n🙂 Link]"
        )
        for fields in (
            {"api_kwargs": {"rich_message": rich}},
            {"rich_message": SimpleNamespace(to_dict=lambda: rich)},
        ):
            with self.subTest(source=next(iter(fields))):
                reply = SimpleNamespace(text=None, caption=None, **fields)
                self.assertEqual(
                    self.channel._extract_reply_context(SimpleNamespace(reply_to_message=reply)),
                    expected,
                )

    def test_rich_reply_context_keeps_existing_character_limit(self):
        rich = {"blocks": [{"type": "paragraph", "text": "x" * 4100}]}
        reply = SimpleNamespace(text=None, caption=None, api_kwargs={"rich_message": rich})
        self.assertEqual(
            self.channel._extract_reply_context(SimpleNamespace(reply_to_message=reply)),
            f"[Reply to: {'x' * TELEGRAM_REPLY_CONTEXT_MAX_LEN}...]",
        )

    async def test_legacy_fallback_does_not_retry_unknown_timeout_delivery(self):
        for errors in (
            [TimedOut()],
            [BadRequest("Can't parse entities"), TimedOut()],
        ):
            with self.subTest(html_rejected=len(errors) > 1):
                self.bot.send_message.reset_mock()
                self.bot.send_message.side_effect = errors
                with self.assertRaises(TimedOut):
                    await self.channel._send_legacy_text(123, "**content**")
                self.assertEqual(self.bot.send_message.await_count, len(errors))

    async def test_legacy_plain_fallback_retries_explicit_rate_limit(self):
        self.bot.send_message.side_effect = [
            BadRequest("Can't parse entities"),
            RetryAfter(0),
            SimpleNamespace(message_id=99),
        ]
        await self.channel._send_legacy_text(123, "**content**")
        calls = self.bot.send_message.await_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1], calls[2])
        self.assertNotIn("parse_mode", calls[2].kwargs)

    async def test_stream_fallback_retries_rejected_tail_without_losing_or_repeating_text(self):
        self.channel.config.stream_edit_interval = 60
        self.bot.do_api_request.side_effect = EndPointNotFound("Endpoint not found")
        sent_texts = []
        edited_texts = []
        tail_rejected = False

        async def send_message(**kwargs):
            nonlocal tail_rejected
            if sent_texts and not tail_rejected:
                tail_rejected = True
                raise RetryAfter(0)
            sent_texts.append(kwargs["text"])
            return SimpleNamespace(message_id=99)

        async def edit_message_text(**kwargs):
            edited_texts.append(kwargs["text"])

        self.bot.send_message.side_effect = send_message
        self.bot.edit_message_text.side_effect = edit_message_text
        content = "A" * 2000 + "B" * 4000
        await self.channel.send_delta("123", content[:2000], {"_stream_id": "s1"})
        await self.channel.send_delta("123", content[2000:], {"_stream_id": "s1"})
        # PartnerManager uses one attempt for stream frames; the ordinary
        # _streamed final then follows the shared delivery contract.
        await send_with_retry(
            self.channel,
            OutboundMessage(
                channel="telegram",
                chat_id="123",
                content="",
                metadata={"_stream_id": "s1", "_stream_end": True, "_stream_final": True},
            ),
            max_attempts=1,
        )
        await deliver_outbound(
            self.channel,
            OutboundMessage(
                channel="telegram",
                chat_id="123",
                content=content,
                metadata={"_streamed": True, "_stream_id": "s1"},
            ),
        )

        self.assertEqual("".join([*edited_texts, *sent_texts[1:]]), content)
        self.assertEqual(self.bot.send_message.await_count, 3)
        self.assertEqual(len(edited_texts), 1)
        self.assertNotIn("123", self.channel._stream_bufs)

    async def test_stream_rich_tail_retries_only_the_rejected_chunk(self):
        self.channel.config.stream_edit_interval = 60
        delivered_chunks = []
        rejected_chunks = set()

        async def do_api_request(endpoint, *, api_kwargs):
            text = api_kwargs["rich_message"]["markdown"]
            if endpoint == "sendRichMessage" and text not in rejected_chunks:
                rejected_chunks.add(text)
                raise RetryAfter(0)
            delivered_chunks.append(text)
            return {"message_id": 99}

        self.bot.do_api_request.side_effect = do_api_request
        content = "A" * 32000 + "B" * 32000 + "C" * 2000
        await self.channel.send_delta("123", content[:2000], {"_stream_id": "s1"})
        await self.channel.send_delta("123", content[2000:], {"_stream_id": "s1"})
        await send_with_retry(
            self.channel,
            OutboundMessage(
                channel="telegram",
                chat_id="123",
                content="",
                metadata={"_stream_id": "s1", "_stream_end": True, "_stream_final": True},
            ),
            max_attempts=1,
        )
        await deliver_outbound(
            self.channel,
            OutboundMessage(
                channel="telegram",
                chat_id="123",
                content=content,
                metadata={"_streamed": True, "_stream_id": "s1"},
            ),
        )

        self.assertEqual(sum(map(len, delivered_chunks)), len(content))
        self.assertEqual("".join(delivered_chunks), content)
        calls = self.bot.do_api_request.await_args_list
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[1], calls[2])
        self.assertEqual(calls[3], calls[4])
        self.bot.send_message.assert_awaited_once()  # The initial preview only.
        self.assertNotIn("123", self.channel._stream_bufs)

    async def test_legacy_edit_endpoint_rejecting_rich_payload_finalizes_same_message(self):
        class LegacyEditRequest(CaptureRequest):
            async def do_request(self, url, method, request_data=None, **kwargs):
                endpoint = url.rsplit("/", 1)[-1]
                payload = request_data.json_parameters if request_data else {}
                if endpoint == "editMessageText" and "rich_message" in payload:
                    self.calls.append((endpoint, payload))
                    return 400, json.dumps(
                        {"ok": False, "error_code": 400, "description": "Message text is empty"}
                    ).encode()
                return await super().do_request(url, method, request_data, **kwargs)

        request = LegacyEditRequest()
        self.channel.config.stream_edit_interval = 60
        content = "A" * 2000 + "B" * 4000
        async with Bot("123456:SYNTHETIC_TOKEN", request=request) as bot:
            self.channel._app = SimpleNamespace(bot=bot)
            await self.channel.send_delta("123", content[:2000], {"_stream_id": "s1"})
            await self.channel.send_delta("123", content[2000:], {"_stream_id": "s1"})
            await self.channel.send_delta("123", "", {"_stream_id": "s1", "_stream_end": True})

        edits = [payload for endpoint, payload in request.calls if endpoint == "editMessageText"]
        self.assertEqual(len(edits), 2)
        self.assertIn("rich_message", edits[0])
        self.assertEqual(edits[1]["message_id"], edits[0]["message_id"])
        self.assertEqual(edits[1]["parse_mode"], "HTML")
        sends = [
            payload["text"] for endpoint, payload in request.calls if endpoint == "sendMessage"
        ]
        self.assertEqual(edits[1]["text"] + "".join(sends[1:]), content)
        self.assertNotIn("123", self.channel._stream_bufs)
        self.assertFalse(self.channel._rich_messages_unavailable)

    async def test_empty_text_error_does_not_downgrade_an_empty_rich_edit(self):
        self.bot.do_api_request.side_effect = BadRequest("Message text is empty")
        with self.assertRaises(BadRequest):
            await self.channel._try_rich(
                "editMessageText",
                {"chat_id": 123, "message_id": 99, "rich_message": {"markdown": ""}},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
