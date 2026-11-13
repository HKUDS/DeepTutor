"""Issue #2621: the workspace system note must be byte-stable across turns.

The chat loop replays the workspace note as the ``workspace`` runtime
snapshot, which sits inside the cached prompt prefix. While the note carried
the per-turn output folder (``outputs/chat/<session>/<turn>/``), every turn
rewrote that snapshot: the old copy was cut out of the middle of the rebuilt
history and a new copy appended, so the provider-side prefix cache missed on
every multi-turn request (single-turn tool loops were unaffected).

These tests replay real turns into each other the way the session store and
``ContextBuilder`` do, then require the strongest observable guarantee: each
turn's request is an exact byte-prefix extension of the previous one.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext, WorkspaceRuntimeContext
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.services.session.model_history import normalize_model_turn, replay_history


class _Registry:
    def deferred_tools(self):
        return []

    def build_prompt_text(self, _enabled, **_kwargs):
        return "- `web_search` - Search the web"

    async def execute(self, name: str, **kwargs):
        return ToolResult(content="tool answer", success=True)


@pytest.fixture(autouse=True)
def _isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from deeptutor.capabilities.setup.binding import mark_intro_shown
    from deeptutor.services.path_service import PathService

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(PathService, "_instance", paths)
    paths.ensure_all_directories()
    # First-run onboarding legitimately changes the next turn's system prompt.
    # Replay tests require stable configuration; setup owns onboarding tests.
    mark_intro_shown()
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai",
            model="gpt-test",
            api_key="k",
            base_url="u",
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
        ),
    )


def _pipeline(language: str) -> AgenticChatPipeline:
    pipeline = AgenticChatPipeline(language=language)
    pipeline.registry = _Registry()
    return pipeline


def _context(
    turn: str,
    *,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
    session_id: str = "cache-session",
) -> UnifiedContext:
    return UnifiedContext(
        session_id=session_id,
        user_message=user_message,
        runtime=TurnRuntimeContext(
            workspace=WorkspaceRuntimeContext(
                workspace_id="ws_test",
                root="/private/host/learning-files",
                output_dir=f"/private/host/learning-files/outputs/chat/{session_id}/{turn}",
                logical_output_dir=f"outputs/chat/{session_id}/{turn}",
            ),
            model_history=history,
        ),
    )


def _persisted_record(
    messages: list[dict[str, Any]], *, start: int
) -> dict[str, Any] | None:
    """What ``AgentLoop`` stores on the assistant row for one finished turn."""
    return normalize_model_turn(
        {
            "version": 1,
            "messages": messages[start:],
            "system": messages[0]["content"],
        }
    )


def _workspace_snapshot(messages: list[dict[str, Any]]) -> dict[str, Any]:
    return next(message for message in messages if message.get("_context_snapshot") == "workspace")


@pytest.mark.parametrize("language", ["en", "zh"])
def test_workspace_note_is_byte_identical_across_consecutive_turns(language: str) -> None:
    first = _pipeline(language)
    first_messages = first._build_loop_messages(
        context=_context("turn-1", user_message="Question"), enabled_tools=[]
    )
    note_first = first._runtime_snapshots.get("workspace", "")
    assert note_first

    # Persist turn one, then rebuild the model history exactly as
    # ``ContextBuilder`` does for the next turn of the same session.
    record = _persisted_record(first_messages, start=1)
    assert record is not None
    rows = [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "A1", "metadata": {"model_turn": record}},
    ]
    history = replay_history(rows)

    second = _pipeline(language)
    second_messages = second._build_loop_messages(
        context=_context("turn-2", user_message="Follow-up", history=history), enabled_tools=[]
    )
    note_second = second._runtime_snapshots.get("workspace", "")

    # The workspace system note is byte-identical across turns.
    assert note_second == note_first
    # ...and no turn-scoped path leaked into it.
    assert "turn-1" not in note_second
    assert "turn-2" not in note_second


@pytest.mark.parametrize("language", ["en", "zh"])
def test_every_next_turn_request_extends_the_previous_prefix(language: str) -> None:
    """Nothing moves inside the cached prefix when the next turn starts."""
    messages: list[list[dict[str, Any]]] = []
    rows: list[dict[str, Any]] = []
    starts: list[int] = [1]
    for index, turn in enumerate(("turn-1", "turn-2", "turn-3"), start=1):
        history = replay_history(rows) if rows else None
        pipeline = _pipeline(language)
        turn_messages = pipeline._build_loop_messages(
            context=_context(
                turn,
                user_message=f"Question {index}",
                history=history,
            ),
            enabled_tools=[],
        )
        if messages:
            # Every byte of the previous request reappears unchanged at the
            # head of this one: system prompt, workspace snapshot, and the
            # replayed dialogue all stay a prompt-cache hit.
            assert turn_messages[: len(messages[-1])] == messages[-1]
        messages.append(turn_messages)
        # The workspace snapshot keeps its position (and bytes) across turns.
        assert _workspace_snapshot(turn_messages) == _workspace_snapshot(messages[0])
        # Turn-level state lives only in the trailing user message, past the
        # cached prefix.
        assert f"outputs/chat/cache-session/{turn}" in turn_messages[-1]["content"]
        assert f"outputs/chat/cache-session/{turn}" not in turn_messages[0]["content"]
        assert f"outputs/chat/cache-session/{turn}" not in _workspace_snapshot(
            turn_messages
        )["content"]
        # Persist this turn the way the store does, then let the next
        # iteration replay it.
        record = _persisted_record(turn_messages, start=starts[-1])
        assert record is not None
        rows.extend(
            [
                {"role": "user", "content": f"Question {index}"},
                {"role": "assistant", "content": f"A{index}", "metadata": {"model_turn": record}},
            ]
        )
        starts.append(1 + len(replay_history(rows)))
