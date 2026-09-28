"""Opt-in provider proof: DEEPTUTOR_CACHE_E2E=1 pytest -s <this file>.

Uses the configured model with synthetic prompts and a local lookup tool.
No user conversations are changed; the session database lives in tmp_path.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext, WorkspaceRuntimeContext
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.llm.metrics import TurnUsage, current_usage
from deeptutor.services.session.context_builder import ContextBuilder
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_llm_resolver,
    pytest.mark.skipif(
        os.getenv("DEEPTUTOR_CACHE_E2E") != "1", reason="explicit real API opt-in required"
    ),
]


class Lookup(BaseTool):
    def get_definition(self):
        return ToolDefinition(
            name="cache_lookup",
            description="Return the stored deployment color. Call once when asked to look it up.",
        )

    async def execute(self, **kwargs):
        return ToolResult(content="The stored deployment color is azure-falcon-42.")


@pytest.mark.asyncio
async def test_real_provider_cache_survives_tool_turn_and_database_resume(monkeypatch, tmp_path):
    from deeptutor.runtime.agentic.client import close_agentic_client_pool
    from deeptutor.services.llm.config import get_llm_config

    config = get_llm_config()
    registry = ToolRegistry()
    registry.register(Lookup())
    requests = []
    usage = TurnUsage()
    token = current_usage.set(usage)

    async def run(context, force_tool=False):
        pipeline = AgenticChatPipeline(language="en", max_tokens=1024, max_rounds=3)
        pipeline.initial_tool_choice = "cache_lookup" if force_tool else None
        pipeline.registry = registry
        monkeypatch.setattr(pipeline, "_prepare_deferred_tools", AsyncMock())
        monkeypatch.setattr(pipeline, "_prepare_kb_manifests", AsyncMock())
        monkeypatch.setattr(pipeline, "_build_notebook_manifest", lambda: "")
        monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _: ["cache_lookup"])
        original = pipeline._build_openai_client()

        async def create(**kwargs):
            requests.append(
                deepcopy({"messages": kwargs["messages"], "tools": kwargs.get("tools")})
            )
            return await original.chat.completions.create(**kwargs)

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)
        bus = StreamBus()

        async def consume():
            async for _ in bus.subscribe():
                pass

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        try:
            await asyncio.wait_for(pipeline.run(context, bus), 120)
            return pipeline.last_result
        finally:
            await bus.close()
            await consumer

    try:
        store = SQLiteSessionStore(db_path=tmp_path / "session.db")
        sid = (await store.create_session())["id"]
        first = UnifiedContext(
            session_id=sid,
            user_message="Look up the deployment color with cache_lookup, then repeat the exact value in one short sentence.",
            runtime=TurnRuntimeContext(
                workspace=WorkspaceRuntimeContext(logical_output_dir="outputs/cache-test/turn-1")
            ),
        )
        result = await run(first, force_tool=True)
        assert "azure-falcon-42" in result["response"]
        await store.add_message(sid, "user", first.user_message)
        await store.add_message(
            sid, "assistant", result["response"], metadata={"model_turn": first.runtime.model_turn}
        )
        first_turn_calls = len(requests)
        assert first_turn_calls >= 2
        restored = await ContextBuilder(SQLiteSessionStore(db_path=tmp_path / "session.db")).build(
            session_id=sid, llm_config=config
        )
        second = UnifiedContext(
            session_id=sid,
            user_message="Repeat that stored color once. Do not call any tools.",
            runtime=TurnRuntimeContext(
                model_history=restored.model_history,
                previous_model_turn=restored.previous_model_turn,
                workspace=WorkspaceRuntimeContext(logical_output_dir="outputs/cache-test/turn-2"),
            ),
        )
        result = await run(second)
        assert "azure-falcon-42" in result["response"]
        before, after = requests[first_turn_calls - 1], requests[first_turn_calls]
        assert after["tools"] == before["tools"]
        assert after["messages"][: len(before["messages"])] == before["messages"]
        summary, _ = await ContextBuilder(store)._summarize(
            session_id=sid,
            language="en",
            source_text="fallback",
            summary_budget=512,
            replay_request={"messages": before["messages"], "tools": before["tools"]},
        )
        assert "azure-falcon-42" in summary
        counts = [
            {k: call.get(k) for k in ("prompt_tokens", "cache_read_input_tokens", "cache_hit_rate")}
            for call in usage.calls
        ]
        print(json.dumps({"provider": config.binding, "model": config.model, "calls": counts}))
        assert usage.calls[first_turn_calls].get("cache_read_input_tokens", 0) > 0
    finally:
        current_usage.reset(token)
        await close_agentic_client_pool()
