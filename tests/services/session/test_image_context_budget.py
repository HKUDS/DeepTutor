"""Offline regressions: vision budgeting must not rewrite or drop history."""

import base64
import copy
import json
import random
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from deeptutor.services.llm.image_replay import deduplicate_user_images
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


def distinct_image(index):
    return image("data:image/png;base64," + base64.b64encode(bytes([index])).decode())


class ImageTokenTests(unittest.TestCase):
    def setUp(self):
        self.builder = ContextBuilder(None)

    def test_image_encoding_size_does_not_change_budget(self):
        small = self.builder._model_tokens(rows_with_parts([image("data:image/png;base64,AA==")]))
        large = self.builder._model_tokens(rows_with_parts([image()]))
        # Stable image labels also consume a small amount of text; their
        # token counts need not match for two different image identities.
        for tokens in (small, large):
            self.assertGreaterEqual(tokens, IMAGE_ALLOWANCE)
            self.assertLess(tokens, IMAGE_ALLOWANCE + 200)

    def test_reader_three_screenshots_fit_history_budget(self):
        rows = rows_with_parts(
            [{"type": "text", "text": "继续解释贝叶斯"}, *[distinct_image(i) for i in range(3)]]
        )
        tokens = self.builder._model_tokens(rows)
        self.assertGreaterEqual(tokens, 3 * IMAGE_ALLOWANCE)
        self.assertLess(tokens, self.builder._history_budget(CONFIG))

    def test_remote_image_url_is_not_language_text(self):
        local = self.builder._model_tokens(rows_with_parts([image()]))
        remote = self.builder._model_tokens(
            rows_with_parts([image("https://example.test/image.png")])
        )
        for tokens in (local, remote):
            self.assertGreaterEqual(tokens, IMAGE_ALLOWANCE)
            self.assertLess(tokens, IMAGE_ALLOWANCE + 200)

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

    def test_identical_images_share_allowance_but_references_still_count(self):
        one = self.builder._model_tokens(rows_with_parts([image()]))
        two = self.builder._model_tokens(rows_with_parts([image(), image()]))
        self.assertGreater(two, one)
        self.assertLess(two - one, 200)

    def test_budget_diagnostics_distinguish_raw_and_projected_replay(self):
        rows = rows_with_parts([distinct_image(1), distinct_image(1)])
        with self.assertLogs("deeptutor.services.session.context_builder", level="DEBUG") as logs:
            effective = self.builder._model_tokens(rows)

        raw_tokens = logs.records[0].args[0]
        projected_tokens = logs.records[0].args[1]
        self.assertGreater(raw_tokens, 2 * IMAGE_ALLOWANCE)
        self.assertEqual(projected_tokens, effective)
        self.assertLess(effective, IMAGE_ALLOWANCE + 200)

    def test_distinct_options_and_mutable_urls_each_keep_an_image_allowance(self):
        low = distinct_image(1)
        low["image_url"]["detail"] = "low"
        high = distinct_image(1)
        high["image_url"]["detail"] = "high"
        jpeg = image("data:image/jpeg;base64,AQ==")
        cropped = {**low, "crop": [0, 0, 10, 10]}
        remote = image("https://example.test/changing.png")
        parts = [low, high, jpeg, cropped, remote, remote]
        tokens = self.builder._model_tokens(rows_with_parts(parts))
        self.assertGreaterEqual(tokens, 6 * IMAGE_ALLOWANCE)
        self.assertLess(tokens, 6 * IMAGE_ALLOWANCE + 500)

    def test_recent_selection_keeps_the_longest_whole_turn_suffix(self):
        rows = []
        for i in range(4):
            rows += rows_with_parts([distinct_image(i)], start=2 * i + 1)
        for budget, retained_turns in [(0, 1), (5000, 1), (9000, 2), (13000, 3), (18000, 4)]:
            with self.subTest(budget=budget):
                older, recent = self.builder._select_recent_messages(rows, budget)
                self.assertEqual(recent, rows[-2 * retained_turns :])
                self.assertEqual(older + recent, rows)

    def test_mixed_history_selection_uses_replay_for_every_candidate(self):
        rows = rows_with_parts([distinct_image(1)])
        rows += [
            {"id": 3, "role": "user", "content": "earlier question"},
            {
                "id": 4,
                "role": "assistant",
                "content": "",
                "metadata": {"provider_response_state": {"reasoning_content": "private " * 7000}},
            },
            {"id": 5, "role": "user", "content": "recent question"},
        ]
        # Empty legacy display rows are omitted from replay. Switching to
        # transcript accounting for a legacy-only candidate would count its
        # unused state and incorrectly discard the earlier model turn.
        self.assertGreater(self.builder._model_tokens(rows[2:]), 5000)
        older, recent = self.builder._select_recent_messages(rows, 5000)
        self.assertEqual(older, [])
        self.assertEqual(recent, rows)


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
            rows += rows_with_parts([distinct_image(i)], start=i * 2 + 1)
        builder, store = self.builder(rows)
        result = await builder.build(session_id="test", llm_config=CONFIG)
        builder._summarize.assert_awaited_once()
        self.assertLess(result.token_count, result.budget)

    async def test_repeated_images_fit_without_summarizing_or_changing_durable_history(self):
        rows = []
        for i in range(4):
            rows += rows_with_parts([distinct_image(j) for j in range(4)], start=2 * i + 1)
        before = copy.deepcopy(rows)
        builder, store = self.builder(rows)
        config = SimpleNamespace(model="test", context_window=60000, max_tokens=4096)

        result = await builder.build(session_id="test", llm_config=config)

        builder._summarize.assert_not_awaited()
        store.update_summary.assert_not_awaited()
        self.assertGreaterEqual(result.token_count, 4 * IMAGE_ALLOWANCE)
        self.assertLess(result.token_count, result.budget)
        self.assertEqual(result.model_history, replay_history(rows))
        self.assertEqual(rows, before)

    async def test_recent_selection_budgets_repeated_images_together(self):
        old = rows_with_parts("old evidence " * 60000)
        recent = []
        for i in range(3):
            recent += rows_with_parts([distinct_image(1)], start=3 + 2 * i)
        builder, store = self.builder(old + recent)
        config = SimpleNamespace(model="test", context_window=24000, max_tokens=1024)

        result = await builder.build(session_id="test", llm_config=config)

        # The three retained turns share one image, fitting the 5040-token
        # recent budget. Counting them separately wrongly summarizes two.
        store.update_summary.assert_awaited_once_with("test", "compact summary", 2)
        self.assertEqual(result.model_history[1:], replay_history(recent))

    async def test_failed_summary_reprojects_images_after_removing_canonical_turn(self):
        rows = rows_with_parts([distinct_image(1), {"type": "text", "text": "old " * 20000}])
        recent = rows_with_parts([distinct_image(1)], start=3, tools=True)
        recent += rows_with_parts([distinct_image(1)], start=5)
        rows += recent
        before = copy.deepcopy(rows)
        builder, store = self.builder(rows)
        builder._summarize.side_effect = RuntimeError("offline simulated failure")
        config = SimpleNamespace(model="test", context_window=16000, max_tokens=1024)

        result = await builder.build(session_id="test", llm_config=config)

        store.update_summary.assert_not_awaited()
        self.assertEqual(result.model_history, replay_history(recent))
        projected = deduplicate_user_images(result.model_history)
        self.assertEqual(projected[0]["content"][-1], distinct_image(1))
        self.assertIn("Repeated image", projected[-2]["content"][-1]["text"])
        self.assertTrue(any(message["role"] == "tool" for message in projected))
        self.assertEqual(rows, before)

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
