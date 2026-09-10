"""A raising tool must tell the model *why*, not just that it failed.

#1356: a learner stops their local Ollama and asks a question against a vector
KB. The embedding adapter raises a fully-formed diagnosis — the address it
tried and the command that starts the server — the dispatcher catches it, and
then the chat capability's ``unknown_error_message_factory`` rebuilt the
message from the tool name alone: "An unknown error occurred while executing
rag." The model, told only that something unknown happened, cannot tell the
learner to start Ollama; it retries, works around, or apologises.

The factory could not do better, because the cause was never passed to it.
That is what these tests pin: the contract carries the cause, and each
capability's own bundle spends it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.runtime.agentic.tool_dispatch import (
    dispatch_tool_calls,
    tool_error_message_factory,
)
from deeptutor.runtime.stream_bus import StreamBus

# What ``deeptutor/services/embedding/adapters/ollama.py`` actually raises.
OLLAMA_DOWN = ConnectionError(
    "Cannot connect to Ollama at http://localhost:11434. "
    "Make sure Ollama is running. Start it with: ollama serve"
)


class _UnreachableEmbedding:
    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        raise OLLAMA_DOWN


async def _rag_failure_text(**dispatch_kwargs: Any) -> str:
    """The ``role=tool`` content a failed ``rag`` call puts in front of the model."""
    bus = StreamBus()
    outcome = await dispatch_tool_calls(
        tool_calls=[
            {
                "id": "c1",
                "name": "rag",
                "arguments": json.dumps({"query": "q", "kb_name": "kb"}),
            }
        ],
        context=UnifiedContext(session_id="s1", user_message="hi"),
        stream=bus,
        source="chat",
        stage="responding",
        iteration_index=0,
        registry=_UnreachableEmbedding(),
        **dispatch_kwargs,
    )
    await bus.close()
    return str(outcome.tool_messages[0]["content"])


@pytest.mark.asyncio
async def test_stopped_embedding_server_tells_the_model_where_and_how() -> None:
    """The reporter's turn: the remediation survives all the way to the model."""
    content = await _rag_failure_text(
        tool_error_message_factory=tool_error_message_factory(
            # A capability whose bundle carries the key, as all three now do.
            lambda _key, tool="", error="", default="": f"{tool} failed: {error}"
        )
    )
    assert "http://localhost:11434" in content
    assert "ollama serve" in content
    assert "unknown" not in content.lower()


@pytest.mark.asyncio
async def test_a_capability_that_passes_no_factory_still_names_the_cause() -> None:
    """The dispatcher's own default is the floor, not a bare tool name.

    ``pageindex`` used to override this with a message that dropped the cause;
    it now passes nothing, so this is the message it gets.
    """
    content = await _rag_failure_text()
    assert "ollama serve" in content


def test_a_bundle_without_the_key_falls_back_to_english_with_the_cause() -> None:
    """An older or user-edited prompt bundle loses the wording, never the cause."""

    def _stale_bundle(_key: str, default: str = "", **kwargs: Any) -> str:
        return default.format(**kwargs)

    message = tool_error_message_factory(_stale_bundle)("rag", str(OLLAMA_DOWN))
    assert message == f"rag failed: {OLLAMA_DOWN}"


def test_a_translated_bundle_spends_the_cause_it_is_given() -> None:
    """zh keeps its own phrasing and still shows the endpoint and the fix."""

    def _zh_bundle(_key: str, default: str = "", **kwargs: Any) -> str:
        return "{tool} 执行失败：{error}".format(**kwargs)

    message = tool_error_message_factory(_zh_bundle)("rag", str(OLLAMA_DOWN))
    assert message.startswith("rag 执行失败：")
    assert "ollama serve" in message
