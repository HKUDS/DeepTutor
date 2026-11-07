"""A whole exchange must fit the returned history plan without corrupting replay."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.services.session.context_builder import ContextBuilder
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from tests.services.session.test_model_history import turn_record


@pytest.mark.asyncio
@pytest.mark.parametrize("summarizes", [False, True])
@pytest.mark.parametrize("recorded", [False, True])
@pytest.mark.parametrize("prior_summary", [False, True])
async def test_oversized_last_exchange_is_rejected_without_changing_durable_history(
    tmp_path, monkeypatch, summarizes, recorded, prior_summary
):
    monkeypatch.setenv("DEEPTUTOR_CHAT_ENGINE", "python")
    store = SQLiteSessionStore(tmp_path / "history.db")
    sid = (await store.create_session())["id"]
    for role, content in [
        ("user", "Earlier question"),
        ("assistant", "Earlier answer"),
        ("user", "Latest question"),
    ]:
        await store.add_message(sid, role, content)
    metadata = {"model_turn": turn_record("alpha " * 3000)} if recorded else None
    await store.add_message(
        sid, "assistant", "Display answer" if recorded else "alpha " * 3000, metadata=metadata
    )
    before = deepcopy(await store.get_messages_for_context(sid))
    watermark = before[1]["id"] if prior_summary else 0
    if prior_summary:
        await store.update_summary(sid, "Previous valid summary", watermark)
    builder = ContextBuilder(store)
    monkeypatch.setattr(builder, "_history_budget", lambda config: 1024)
    summary = (
        AsyncMock(return_value=("Small successful summary", []))
        if summarizes
        else AsyncMock(side_effect=ValueError("synthetic failure"))
    )
    config = SimpleNamespace(
        model="gpt-test", binding="openai", context_window=1048576, max_tokens=4096
    )
    with patch.object(builder, "_summarize", summary):
        with pytest.raises(ValueError, match="history.*budget") as raised:
            await builder.build(session_id=sid, llm_config=config)
    assert raised.value.error_code == "history_budget_exceeded"
    assert raised.value.retryable is False
    assert raised.value.token_count > raised.value.budget == 1024
    assert await store.get_messages_for_context(sid) == before
    state = await store.get_session(sid)
    assert (state.get("summary_up_to_msg_id") or 0) < before[-1]["id"]
    if not summarizes:
        assert (state.get("summary_up_to_msg_id") or 0) == watermark


@pytest.mark.asyncio
async def test_whole_small_tool_exchange_remains_replayable(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_CHAT_ENGINE", "python")
    store = SQLiteSessionStore(tmp_path / "history.db")
    sid = (await store.create_session())["id"]
    await store.add_message(sid, "user", "Question")
    record = turn_record("Short evidence")
    await store.add_message(sid, "assistant", "Display answer", metadata={"model_turn": record})
    config = SimpleNamespace(
        model="gpt-test", binding="openai", context_window=1048576, max_tokens=4096
    )
    result = await ContextBuilder(store).build(session_id=sid, llm_config=config)
    assert result.token_count <= result.budget
    assert result.model_history == record["messages"]


@pytest.mark.asyncio
async def test_large_window_does_not_bypass_the_real_history_plan(tmp_path, monkeypatch):
    from deeptutor.services.session.context_builder import (
        MAX_HISTORY_PLAN_TOKENS,
        HistoryBudgetExceeded,
    )

    monkeypatch.setenv("DEEPTUTOR_CHAT_ENGINE", "python")
    store = SQLiteSessionStore(tmp_path / "history.db")
    sid = (await store.create_session())["id"]
    await store.add_message(sid, "user", "Previous question")
    await store.add_message(sid, "assistant", "alpha " * 150000)
    builder = ContextBuilder(store)
    config = SimpleNamespace(
        model="gpt-test", binding="openai", context_window=1048576, max_tokens=4096
    )
    with patch.object(builder, "_summarize", AsyncMock(side_effect=ValueError("fixture"))):
        with pytest.raises(HistoryBudgetExceeded) as raised:
            await builder.build(session_id=sid, llm_config=config)
    assert raised.value.budget == MAX_HISTORY_PLAN_TOKENS
    assert raised.value.token_count > MAX_HISTORY_PLAN_TOKENS
    assert "alpha" not in str(raised.value)
