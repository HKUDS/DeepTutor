"""Outline schemas use the native loader while ordinary tutoring stays small."""

import json

import pytest

from deeptutor.agents.loop.pipeline import AgenticLoopPipeline
from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.providers.view import ProviderToolView


@pytest.mark.asyncio
async def test_outline_tools_remain_discoverable_and_load_in_the_same_live_surface(monkeypatch):
    async def providers(self, context):
        self._tool_view = ProviderToolView.empty(self.registry)
        self._deferred_loader = None
        self._deferred_pool = []

    monkeypatch.setattr(AgenticLoopPipeline, "_prepare_deferred_tools", providers)
    monkeypatch.setattr("deeptutor.services.mcp.load_loaded_tools", lambda _: set())
    monkeypatch.setattr("deeptutor.services.mcp.session_state.record_loaded_tools", lambda *_: None)
    pipeline = MasteryLoopPipeline(language="en")
    context = UnifiedContext(
        session_id="synthetic",
        metadata={"mastery_mode": True, "mastery_path_id": "p", "mastery_session_mode": "study"},
    )
    await pipeline._prepare_deferred_tools(context)
    names = pipeline._compose_enabled_tools(context)
    assert "mastery_build" not in names
    assert "mastery_revise" not in names
    assert "load_tools" in names and "mastery_profile" in names and "mastery_quiz" in names
    manifest = pipeline._deferred_tools_manifest()
    assert all(name in manifest for name in ("mastery_build", "mastery_revise"))
    schemas = pipeline._build_llm_tool_schemas(names, context)
    pipeline._tool_view.attach(schemas)
    initial_size = len(json.dumps(schemas))
    loaded = pipeline._deferred_loader.load(["mastery_revise"])
    assert loaded["loaded"] == ["mastery_revise"]
    assert sum(s["function"]["name"] == "mastery_revise" for s in schemas) == 1
    assert len(json.dumps(schemas)) > initial_size
    assert pipeline._deferred_loader.load(["mastery_revise"])["already_loaded"]
    assert not getattr(pipeline.registry.get("mastery_build"), "deferred", False)


@pytest.mark.asyncio
async def test_outline_mode_keeps_immediately_needed_schemas(monkeypatch):
    async def providers(self, context):
        self._tool_view = ProviderToolView.empty(self.registry)
        self._deferred_loader = None

    monkeypatch.setattr(AgenticLoopPipeline, "_prepare_deferred_tools", providers)
    pipeline = MasteryLoopPipeline(language="en")
    context = UnifiedContext(metadata={"mastery_mode": True, "mastery_session_mode": "outline"})
    await pipeline._prepare_deferred_tools(context)
    assert "mastery_build" in pipeline._compose_enabled_tools(context)
    context.metadata["mastery_session_mode"] = "study"
    context.allowed_builtin_tools = []
    await pipeline._prepare_deferred_tools(context)
    assert "mastery_build" in pipeline._compose_enabled_tools(context)


@pytest.mark.asyncio
async def test_loaded_outline_schema_survives_a_later_turn_with_provider_loader(monkeypatch):
    from deeptutor.runtime.registry.deferred_tools import DeferredToolLoader

    async def providers(self, context):
        # The external provider loader knows no capability names; the local
        # overlay must restore previously loaded outline tools from the session.
        loader = DeferredToolLoader(
            registry=self.registry, session_id="synthetic", loaded=set(), allowed=set()
        )
        self._tool_view = ProviderToolView(
            registry=self.registry, loader=loader, pool=(), manifest=""
        )
        self._deferred_loader = loader

    monkeypatch.setattr(AgenticLoopPipeline, "_prepare_deferred_tools", providers)
    monkeypatch.setattr("deeptutor.services.mcp.load_loaded_tools", lambda _: {"mastery_revise"})
    pipeline = MasteryLoopPipeline(language="en")
    context = UnifiedContext(
        session_id="synthetic",
        metadata={"mastery_mode": True, "mastery_path_id": "p", "mastery_session_mode": "study"},
    )
    await pipeline._prepare_deferred_tools(context)
    schemas = pipeline._build_llm_tool_schemas(pipeline._compose_enabled_tools(context), context)
    pipeline._tool_view.attach(schemas)
    assert sum(s["function"]["name"] == "mastery_revise" for s in schemas) == 1
    assert pipeline._deferred_loader.load(["mastery_status", "not_authorized"])["unknown"] == [
        "mastery_status",
        "not_authorized",
    ]
