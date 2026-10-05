"""Offline regressions: vision budgeting must not rewrite or drop history."""

import base64
import copy
import json
import random
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from deeptutor.services.session.context_builder import ContextBuilder, count_tokens
from deeptutor.services.session.model_history import replay_history

CONFIG = SimpleNamespace(model="test", context_window=272000, max_tokens=4096, binding="openai")
IMAGE_ALLOWANCE = 4096
RANDOM_IMAGE = (
    "data:image/png;base64," + base64.b64encode(random.Random(17).randbytes(340000)).decode()
)


def rows_with_parts(parts, *, start=1, answer="answer", tools=False):
    messages = [{"role": "user", "content": parts}]
    if tools:
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "read_material", "arguments": '{"page":147}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-1", "content": "source evidence"},
            ]
        )
    messages.append({"role": "assistant", "content": answer})
    return [
        {"id": start, "role": "user", "content": "continue"},
        {
            "id": start + 1,
            "role": "assistant",
            "content": answer,
            "metadata": {"model_turn": {"version": 1, "messages": messages}},
        },
    ]


def image(url=RANDOM_IMAGE):
    return {"type": "image_url", "image_url": {"url": url, "detail": "auto"}}


class ImageTokenTests(unittest.TestCase):
    def setUp(self):
        self.builder = ContextBuilder(None)

    def test_image_encoding_size_does_not_change_budget(self):
        small = self.builder._model_tokens(rows_with_parts([image("data:image/png;base64,AA==")]))
        large = self.builder._model_tokens(rows_with_parts([image()]))
        self.assertEqual(small, large)
        self.assertGreaterEqual(large, IMAGE_ALLOWANCE)

    def test_reader_three_screenshots_fit_history_budget(self):
        rows = rows_with_parts(
            [{"type": "text", "text": "继续解释贝叶斯"}, *[image() for _ in range(3)]]
        )
        tokens = self.builder._model_tokens(rows)
        self.assertGreaterEqual(tokens, 3 * IMAGE_ALLOWANCE)
        self.assertLess(tokens, self.builder._history_budget(CONFIG))

    def test_remote_image_url_is_not_language_text(self):
        local = self.builder._model_tokens(rows_with_parts([image()]))
        remote = self.builder._model_tokens(
            rows_with_parts([image("https://example.test/image.png")])
        )
        self.assertEqual(local, remote)

    def test_responses_and_anthropic_images_have_nonzero_allowance(self):
        parts = [
            {"type": "input_image", "image_url": RANDOM_IMAGE},
            {"type": "input_image", "file_id": "file-test"},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": RANDOM_IMAGE},
            },
        ]
        n = self.builder._model_tokens(rows_with_parts(parts))
        self.assertGreaterEqual(n, 3 * IMAGE_ALLOWANCE)
        self.assertLess(n, 3 * IMAGE_ALLOWANCE + 200)

    def test_text_tool_and_reasoning_accounting_unchanged(self):
        rows = rows_with_parts([{"type": "text", "text": "some text"}], tools=True)
        record = rows[-1]["metadata"]["model_turn"]
        record["messages"][-1]["_provider_response_state"] = {
            "reasoning_content": "retained reasoning"
        }
        record["messages"][-1]["thinking_blocks"] = [
            {"type": "thinking", "thinking": "reasoning", "signature": "sig"}
        ]
        expected = count_tokens(json.dumps(replay_history(rows, "summary"), ensure_ascii=False))
        self.assertEqual(self.builder._model_tokens(rows, "summary"), expected)

    def test_encoding_in_user_text_is_still_text(self):
        rows = rows_with_parts([{"type": "text", "text": RANDOM_IMAGE}])
        self.assertGreater(self.builder._model_tokens(rows), self.builder._history_budget(CONFIG))

    def test_never_mutates_images_tools_or_saved_rows(self):
        rows = rows_with_parts([image(), {"type": "text", "text": "keep"}], tools=True)
        original = copy.deepcopy(rows)
        replay_before = replay_history(rows)
        self.builder._model_tokens(rows)
        self.assertEqual(rows, original)
        self.assertEqual(replay_history(rows), replay_before)

    def test_each_image_occurrence_is_counted(self):
        one = self.builder._model_tokens(rows_with_parts([image()]))
        two = self.builder._model_tokens(rows_with_parts([image(), image()]))
        self.assertGreaterEqual(two - one, IMAGE_ALLOWANCE)


class BuilderTests(unittest.IsolatedAsyncioTestCase):
    def builder(self, rows):
        store = SimpleNamespace(
            get_session=AsyncMock(
                return_value={"compressed_summary": "", "summary_up_to_msg_id": 0}
            ),
            get_messages_for_context=AsyncMock(return_value=rows),
            update_summary=AsyncMock(),
        )
        builder = ContextBuilder(store)
        builder._summarize = AsyncMock(return_value=("compact summary", []))
        return builder, store

    async def test_screenshots_do_not_trigger_summary_or_write(self):
        rows = rows_with_parts([image(), image(), image()], tools=True)
        builder, store = self.builder(rows)
        result = await builder.build(session_id="test", llm_config=CONFIG)
        builder._summarize.assert_not_awaited()
        store.update_summary.assert_not_awaited()
        self.assertEqual(result.model_history, replay_history(rows))

    async def test_real_text_overflow_still_summarizes_and_preserves_latest(self):
        rows = rows_with_parts("long text " * 60000)
        latest = rows_with_parts([image(), {"type": "text", "text": "latest"}], start=3, tools=True)
        rows += latest
        builder, store = self.builder(rows)
        result = await builder.build(session_id="test", llm_config=CONFIG)
        builder._summarize.assert_awaited_once()
        store.update_summary.assert_awaited_once_with("test", "compact summary", 2)
        self.assertEqual(result.model_history[1:], replay_history(latest))

    async def test_many_images_still_consume_finite_budget(self):
        rows = []
        for i in range(25):
            rows += rows_with_parts([image("data:image/png;base64,AA==")], start=i * 2 + 1)
        builder, store = self.builder(rows)
        result = await builder.build(session_id="test", llm_config=CONFIG)
        builder._summarize.assert_awaited_once()
        self.assertLess(result.token_count, result.budget)

    async def test_summary_failure_keeps_existing_watermark(self):
        rows = rows_with_parts("long text " * 60000)
        rows += rows_with_parts([image()], start=3)
        builder, store = self.builder(rows)
        builder._summarize.side_effect = RuntimeError("offline simulated failure")
        result = await builder.build(session_id="test", llm_config=CONFIG)
        builder._summarize.assert_awaited_once()
        store.update_summary.assert_not_awaited()
        self.assertEqual(result.model_history, replay_history(rows[-2:]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
