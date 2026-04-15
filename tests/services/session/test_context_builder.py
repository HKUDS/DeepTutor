"""Tests for the ContextBuilder and its helper functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deeptutor.services.session.context_builder import (
    ContextBuildResult,
    ContextBuilder,
    build_history_text,
    count_tokens,
    format_messages_as_transcript,
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
    def _make_llm_config(self, max_tokens: int) -> MagicMock:
        cfg = MagicMock()
        cfg.max_tokens = max_tokens
        return cfg

    def test_history_budget_ratio(self) -> None:
        builder = ContextBuilder(store=MagicMock(), history_budget_ratio=0.35)
        budget = builder._history_budget(self._make_llm_config(4096))
        assert budget == int(4096 * 0.35)

    def test_history_budget_minimum(self) -> None:
        builder = ContextBuilder(store=MagicMock(), history_budget_ratio=0.01)
        budget = builder._history_budget(self._make_llm_config(100))
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
        store.get_session = AsyncMock(return_value={
            "id": "s1",
            "compressed_summary": "",
            "summary_up_to_msg_id": 0,
        })
        store.get_messages_for_context = AsyncMock(return_value=[
            {"id": 1, "role": "user", "content": "Hi"},
            {"id": 2, "role": "assistant", "content": "Hello!"},
        ])

        builder = ContextBuilder(store=store)
        cfg = MagicMock()
        cfg.max_tokens = 4096

        result = await builder.build(session_id="s1", llm_config=cfg)
        assert len(result.conversation_history) == 2
        assert result.events == []
        assert result.token_count > 0
