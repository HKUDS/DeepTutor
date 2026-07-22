"""Tests for the ContextBuilder and its helper functions."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deeptutor.services.session.context_builder import (
    ContextBuilder,
    ContextBuildResult,
    build_history_text,
    count_tokens,
    format_messages_as_transcript,
    trim_incomplete_tail,
)

# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_empty_string(self) -> None:
        assert count_tokens("") == 0

    def test_none_string(self) -> None:
        assert count_tokens(None) == 0  # type: ignore[arg-type]

    def test_nonempty_returns_positive(self) -> None:
        result = count_tokens("Hello, world!")
        assert result > 0

    def test_longer_text_more_tokens(self) -> None:
        short = count_tokens("Hi")
        long = count_tokens("Hello, this is a longer sentence with many words in it.")
        assert long > short


# ---------------------------------------------------------------------------
# format_messages_as_transcript
# ---------------------------------------------------------------------------


class TestFormatMessagesAsTranscript:
    def test_basic_transcript(self) -> None:
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        result = format_messages_as_transcript(messages)
        assert "User: Hi" in result
        assert "Assistant: Hello!" in result

    def test_system_role_mapped(self) -> None:
        messages = [{"role": "system", "content": "You are helpful."}]
        result = format_messages_as_transcript(messages)
        assert "System: You are helpful." in result

    def test_empty_content_skipped(self) -> None:
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "Again"},
        ]
        result = format_messages_as_transcript(messages)
        assert "User: Hi" in result
        assert "User: Again" in result
        assert "Assistant:" not in result

    def test_empty_list(self) -> None:
        assert format_messages_as_transcript([]) == ""

    def test_unknown_role_defaults_to_user(self) -> None:
        messages = [{"role": "tool", "content": "data"}]
        result = format_messages_as_transcript(messages)
        assert "User: data" in result


# ---------------------------------------------------------------------------
# build_history_text
# ---------------------------------------------------------------------------


class TestBuildHistoryText:
    def test_system_becomes_summary(self) -> None:
        messages = [{"role": "system", "content": "Summary here"}]
        result = build_history_text(messages)
        assert "Conversation summary:" in result
        assert "Summary here" in result

    def test_user_and_assistant_roles(self) -> None:
        messages = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
        ]
        result = build_history_text(messages)
        assert "User: Q" in result
        assert "Assistant: A" in result

    def test_empty_content_skipped(self) -> None:
        messages = [{"role": "user", "content": ""}]
        assert build_history_text(messages) == ""


# ---------------------------------------------------------------------------
# ContextBuildResult
# ---------------------------------------------------------------------------


class TestContextBuildResult:
    def test_dataclass_fields(self) -> None:
        r = ContextBuildResult(
            conversation_history=[],
            conversation_summary="",
            context_text="",
            events=[],
            token_count=0,
            budget=1024,
        )
        assert r.budget == 1024
        assert r.token_count == 0


# ---------------------------------------------------------------------------
# ContextBuilder budget helpers
# ---------------------------------------------------------------------------


class TestContextBuilderBudgets:
    def _make_llm_config(
        self,
        max_tokens: int,
        *,
        model: str = "test-model",
        context_window: int | None = None,
    ) -> MagicMock:
        cfg = MagicMock()
        cfg.max_tokens = max_tokens
        cfg.model = model
        cfg.context_window = context_window
        return cfg

    def test_history_budget_uses_explicit_context_window(self) -> None:
        builder = ContextBuilder(store=MagicMock(), history_budget_ratio=0.35)
        budget = builder._history_budget(self._make_llm_config(4096, context_window=128000))
        assert budget == int(128000 * 0.35)

    def test_history_budget_uses_large_context_model_heuristic(self) -> None:
        builder = ContextBuilder(store=MagicMock(), history_budget_ratio=0.35)
        budget = builder._history_budget(self._make_llm_config(4096, model="gpt-4o-mini"))
        assert budget == int(65536 * 0.35)

    def test_history_budget_minimum(self) -> None:
        builder = ContextBuilder(store=MagicMock(), history_budget_ratio=0.01)
        budget = builder._history_budget(self._make_llm_config(100, model="unknown-local-model"))
        assert budget >= 256

    def test_summary_budget(self) -> None:
        builder = ContextBuilder(store=MagicMock(), summary_target_ratio=0.40)
        assert builder._summary_budget(1000) == 400

    def test_summary_budget_minimum(self) -> None:
        builder = ContextBuilder(store=MagicMock(), summary_target_ratio=0.01)
        assert builder._summary_budget(100) >= 96

    def test_recent_budget(self) -> None:
        builder = ContextBuilder(store=MagicMock(), summary_target_ratio=0.40)
        recent = builder._recent_budget(1000)
        assert recent == 1000 - 400

    def test_recent_budget_minimum(self) -> None:
        builder = ContextBuilder(store=MagicMock(), summary_target_ratio=0.99)
        assert builder._recent_budget(200) >= 128


# ---------------------------------------------------------------------------
# ContextBuilder._build_history
# ---------------------------------------------------------------------------


class TestBuildHistory:
    def test_with_summary(self) -> None:
        builder = ContextBuilder(store=MagicMock())
        history = builder._build_history(
            "A summary",
            [{"role": "user", "content": "Q"}],
        )
        assert history[0] == {"role": "system", "content": "A summary"}
        assert history[1] == {"role": "user", "content": "Q"}

    def test_empty_summary_skipped(self) -> None:
        builder = ContextBuilder(store=MagicMock())
        history = builder._build_history(
            "",
            [{"role": "user", "content": "Q"}],
        )
        assert len(history) == 1
        assert history[0]["role"] == "user"

    def test_system_messages_filtered(self) -> None:
        builder = ContextBuilder(store=MagicMock())
        history = builder._build_history(
            "",
            [
                {"role": "system", "content": "Instructions"},
                {"role": "user", "content": "Hello"},
            ],
        )
        assert len(history) == 1
        assert history[0]["role"] == "user"

    def test_empty_content_filtered(self) -> None:
        builder = ContextBuilder(store=MagicMock())
        history = builder._build_history(
            "",
            [
                {"role": "user", "content": ""},
                {"role": "assistant", "content": "answer"},
            ],
        )
        assert len(history) == 1


# ---------------------------------------------------------------------------
# ContextBuilder._select_recent_messages
# ---------------------------------------------------------------------------


class TestSelectRecentMessages:
    def test_selects_from_end(self) -> None:
        builder = ContextBuilder(store=MagicMock())
        messages = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old reply"},
            {"role": "user", "content": "new"},
        ]
        older, recent = builder._select_recent_messages(messages, recent_budget=9999)
        assert len(recent) == 3
        assert len(older) == 0

    def test_budget_limits_selection(self) -> None:
        builder = ContextBuilder(store=MagicMock())
        messages = [
            {"role": "user", "content": "A" * 200},
            {"role": "user", "content": "B" * 200},
            {"role": "user", "content": "C" * 200},
        ]
        older, recent = builder._select_recent_messages(messages, recent_budget=10)
        assert len(recent) >= 1
        assert len(older) + len(recent) == len(messages)


# ---------------------------------------------------------------------------
# ContextBuilder.build — with mocked store
# ---------------------------------------------------------------------------


class TestContextBuilderBuild:
    @pytest.mark.asyncio
    async def test_missing_session_returns_empty(self) -> None:
        store = AsyncMock()
        store.get_session = AsyncMock(return_value=None)
        store.get_messages_for_context = AsyncMock(return_value=[])

        builder = ContextBuilder(store=store)
        cfg = MagicMock()
        cfg.max_tokens = 4096

        result = await builder.build(session_id="missing", llm_config=cfg)
        assert result.conversation_history == []
        assert result.context_text == ""

    @pytest.mark.asyncio
    async def test_within_budget_no_summarize(self) -> None:
        store = AsyncMock()
        store.get_session = AsyncMock(
            return_value={
                "id": "s1",
                "compressed_summary": "",
                "summary_up_to_msg_id": 0,
            }
        )
        store.get_messages_for_context = AsyncMock(
            return_value=[
                {"id": 1, "role": "user", "content": "Hi"},
                {"id": 2, "role": "assistant", "content": "Hello!"},
            ]
        )

        builder = ContextBuilder(store=store)
        cfg = MagicMock()
        cfg.max_tokens = 4096

        result = await builder.build(session_id="s1", llm_config=cfg)
        assert len(result.conversation_history) == 2
        assert result.events == []
        assert result.token_count > 0

    @pytest.mark.asyncio
    async def test_large_context_model_avoids_premature_summarize(self) -> None:
        long_user = "user says " + ("alpha " * 1400)
        long_assistant = "assistant says " + ("beta " * 1400)
        store = AsyncMock()
        store.get_session = AsyncMock(
            return_value={
                "id": "s1",
                "compressed_summary": "",
                "summary_up_to_msg_id": 0,
            }
        )
        store.get_messages_for_context = AsyncMock(
            return_value=[
                {"id": 1, "role": "user", "content": long_user},
                {"id": 2, "role": "assistant", "content": long_assistant},
            ]
        )

        builder = ContextBuilder(store=store)
        cfg = MagicMock()
        cfg.max_tokens = 4096
        cfg.model = "gpt-4o-mini"
        cfg.context_window = None

        result = await builder.build(session_id="s1", llm_config=cfg)
        assert len(result.conversation_history) == 2
        assert result.events == []
        store.update_summary.assert_not_called()


# ---------------------------------------------------------------------------
# trim_incomplete_tail
# ---------------------------------------------------------------------------


class TestTrimIncompleteTail:
    def test_drops_trailing_partial_line(self) -> None:
        assert trim_incomplete_tail("- done line\n- cut mid sent") == "- done line"

    def test_single_line_kept(self) -> None:
        assert trim_incomplete_tail("only one line, keep it") == "only one line, keep it"


# ---------------------------------------------------------------------------
# ContextBuilder.build — summarize paths (rebuild / fold-in / failure / branch)
# ---------------------------------------------------------------------------


def _make_store(
    messages: list[dict[str, Any]],
    *,
    summary: str = "",
    up_to: int = 0,
) -> AsyncMock:
    store = AsyncMock()
    store.get_session = AsyncMock(
        return_value={
            "id": "s1",
            "compressed_summary": summary,
            "summary_up_to_msg_id": up_to,
        }
    )
    store.get_messages_for_context = AsyncMock(return_value=messages)
    return store


def _small_window_cfg() -> MagicMock:
    # context_window=1000 -> history budget 350, summary budget 140,
    # recent budget 210, raw-rebuild budget floor 1024.
    cfg = MagicMock()
    cfg.max_tokens = 512
    cfg.model = "test-model"
    cfg.context_window = 1000
    return cfg


class TestContextBuilderSummarizePaths:
    @pytest.mark.asyncio
    async def test_rebuilds_from_raw_when_prefix_fits(self) -> None:
        messages = [
            {"id": 1, "role": "user", "content": "RAW_OLDEST_MARKER " + "alpha " * 90},
            {"id": 2, "role": "assistant", "content": "beta " * 90},
            {"id": 3, "role": "user", "content": "gamma " * 200},
            {"id": 4, "role": "assistant", "content": "delta " * 400},
            {"id": 5, "role": "user", "content": "recent question"},
            {"id": 6, "role": "assistant", "content": "recent answer"},
        ]
        store = _make_store(messages, summary="OLD SUMMARY", up_to=2)
        builder = ContextBuilder(store=store)
        builder._summarize = AsyncMock(return_value=("NEW SUMMARY", []))

        result = await builder.build(session_id="s1", llm_config=_small_window_cfg())

        source = builder._summarize.call_args.kwargs["source_text"]
        # Raw prefix fits the rebuild budget: source is the original
        # transcript (anti-drift), not summary-of-summary fold-in.
        assert "Conversation history to summarize:" in source
        assert "RAW_OLDEST_MARKER" in source
        assert "Existing summary:" not in source
        store.update_summary.assert_awaited_once_with("s1", "NEW SUMMARY", 4)
        assert result.conversation_summary == "NEW SUMMARY"
        assert result.conversation_history[0] == {
            "role": "system",
            "content": "NEW SUMMARY",
        }

    @pytest.mark.asyncio
    async def test_folds_in_when_prefix_exceeds_rebuild_budget(self) -> None:
        messages = [
            {"id": 1, "role": "user", "content": "RAW_OLDEST_MARKER " + "w1 " * 600},
            {"id": 2, "role": "assistant", "content": "w2 " * 600},
            {"id": 3, "role": "user", "content": "FOLD_MARKER " + "w3 " * 400},
            {"id": 4, "role": "assistant", "content": "recent answer"},
        ]
        store = _make_store(messages, summary="OLD SUMMARY", up_to=2)
        builder = ContextBuilder(store=store)
        builder._summarize = AsyncMock(return_value=("NEW SUMMARY", []))

        await builder.build(session_id="s1", llm_config=_small_window_cfg())

        source = builder._summarize.call_args.kwargs["source_text"]
        # Prefix transcript (>1024 tokens) exceeds the rebuild budget:
        # degrade to folding the stored summary plus older turns only.
        assert "Existing summary:\nOLD SUMMARY" in source
        assert "FOLD_MARKER" in source
        assert "RAW_OLDEST_MARKER" not in source
        store.update_summary.assert_awaited_once_with("s1", "NEW SUMMARY", 3)

    @pytest.mark.asyncio
    async def test_failure_keeps_watermark_and_degrades_for_turn(self) -> None:
        messages = [
            {"id": 1, "role": "user", "content": "old " * 100},
            {"id": 2, "role": "assistant", "content": "older reply " * 100},
            {"id": 3, "role": "user", "content": "mid " * 400},
            {"id": 4, "role": "assistant", "content": "recent answer"},
        ]
        store = _make_store(messages, summary="OLD SUMMARY", up_to=2)
        builder = ContextBuilder(store=store)
        builder._summarize = AsyncMock(side_effect=RuntimeError("llm down"))

        result = await builder.build(session_id="s1", llm_config=_small_window_cfg())

        # Nothing may be marked as summarized on failure — otherwise the
        # unfolded turns are dropped from every future context build.
        store.update_summary.assert_not_called()
        assert result.conversation_summary == "OLD SUMMARY"
        assert result.conversation_history[0] == {
            "role": "system",
            "content": "OLD SUMMARY",
        }
        contents = [m["content"] for m in result.conversation_history]
        assert "recent answer" in contents

    @pytest.mark.asyncio
    async def test_branch_switch_discards_sibling_summary(self) -> None:
        # Watermark 99 is not on this branch's ancestor chain: the stored
        # summary was folded from a sibling branch and must not leak in.
        messages = [
            {"id": 1, "role": "user", "content": "Hi"},
            {"id": 2, "role": "assistant", "content": "Hello!"},
        ]
        store = _make_store(messages, summary="SIBLING SUMMARY", up_to=99)
        builder = ContextBuilder(store=store)
        builder._summarize = AsyncMock(return_value=("", []))

        result = await builder.build(session_id="s1", llm_config=_small_window_cfg())

        assert result.conversation_summary == ""
        assert all(m["role"] != "system" for m in result.conversation_history)
        store.update_summary.assert_not_called()
