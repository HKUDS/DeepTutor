"""Internal retrieval evidence never enters replayable public stream events."""
import asyncio
import json

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.runtime.agentic.tool_dispatch import dispatch_tool_calls
from deeptutor.runtime.stream_bus import StreamBus


@pytest.mark.asyncio
async def test_public_projection_preserves_private_model_evidence_and_replay(tmp_path):
    class Registry:
        async def execute(self, name, **kwargs):
            return ToolResult(
                content="SECRET_KEY: C", metadata={"answer": "SECRET_KEY"},
                sources=[{"url": "/SECRET_KEY.pdf"}],
                model_message={"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,SECRET_PIXELS"}}
                ]},
                public_result={"content": "Sources inspected privately."},
            )

    bus = StreamBus()
    events = []
    async def consume():
        async for event in bus.subscribe():
            events.append(event.to_dict())
    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)
    outcome = await dispatch_tool_calls(
        tool_calls=[{"id": "inspect", "name": "rag", "arguments": '{"query":"SECRET_QUERY"}'}],
        context=UnifiedContext(session_id="synthetic", user_message="Quiz me"),
        stream=bus, source="mastery_path", stage="responding", iteration_index=0,
        registry=Registry(),
        kwarg_augmenter=lambda name, args, context: {**args, "_mastery_source_context": True},
        retrieve_meta_factory=lambda meta, name, args: {**meta, "query": args.get("query", "")},
    )
    await bus.close()
    await consumer
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(tmp_path / "synthetic-source-replay.db")
    session = await store.create_session("Synthetic source replay")
    turn = await store.begin_turn(session["session_id"], "mastery_path")
    await store.append_turn_events(turn["id"], events)
    reopened = SQLiteSessionStore(store.db_path)
    replay = await reopened.get_turn_events(turn["id"])
    assert "SECRET" not in json.dumps(replay)
    assert "Sources inspected privately." in json.dumps(replay)
    assert outcome.sources == []
    assert "SECRET_KEY" in json.dumps(outcome.tool_messages)
    assert "SECRET_PIXELS" in json.dumps(outcome.model_messages)


@pytest.mark.asyncio
async def test_read_source_uses_private_projection_for_mastery():
    from deeptutor.tools.builtin import ReadSourceTool

    result = await ReadSourceTool().execute(source_id="qb-example",
        source_index={"qb-example": "SECRET_BANK_ANSWER"}, _mastery_source_context=True)
    assert result.content == "SECRET_BANK_ANSWER"
    assert result.public_result == {"content": "Attached source inspected privately."}
    ordinary = await ReadSourceTool().execute(source_id="qb-example",
        source_index={"qb-example": "Attached source"})
    assert ordinary.public_result is None
