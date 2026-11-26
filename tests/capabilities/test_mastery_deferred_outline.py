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
    schemas = pipeline._build_llm_tool_schemas(pipeline._compose_enabled_tools(context), context)
    pipeline._tool_view.attach(schemas)
    assert "mastery_build" in [s["function"]["name"] for s in schemas]
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


@pytest.mark.parametrize("language", ["en", "zh"])
def test_session_mode_is_a_snapshot_not_a_system_prompt_change(language):
    pipeline = MasteryLoopPipeline(language=language)
    assembler = pipeline._prompt_assembler
    prompts, snapshots = [], []
    for mode in ("outline", "study", "review"):
        context = UnifiedContext(metadata={"mastery_mode": True, "mastery_session_mode": mode})
        prompts.append([(b.name, b.content) for b in assembler.foundation_blocks(context)])
        snapshots.append(assembler.session_mode_snapshot(context))
    # Every mode sees the same foundation, so a switch keeps the cached prefix.
    assert prompts[0] == prompts[1] == prompts[2]
    assert len(set(snapshots)) == 3
    assert all(s.startswith("[Runtime context: mastery_session_mode]\n") for s in snapshots)
    assert "`review`" in snapshots[2]


@pytest.mark.parametrize("language", ["en", "zh"])
def test_only_the_current_modes_rules_reach_the_model(language):
    pipeline = MasteryLoopPipeline(language=language)
    assembler = pipeline._prompt_assembler
    rules = {mode: assembler._t(f"session.{mode}") for mode in ("outline", "study", "review")}
    assert all(rules.values())
    context = UnifiedContext(metadata={"mastery_mode": True, "mastery_session_mode": "study"})
    system = "\n".join(b.content for b in assembler.foundation_blocks(context))
    # The system prompt names the modes but carries none of their rule sets,
    # so it never shows the model three conflicting sets of rules at once.
    assert not any(body in system for body in rules.values())
    for mode, body in rules.items():
        context = UnifiedContext(metadata={"mastery_mode": True, "mastery_session_mode": mode})
        snapshot = assembler.session_mode_snapshot(context)
        assert body in snapshot
        assert not any(other in snapshot for name, other in rules.items() if name != mode)


@pytest.mark.asyncio
async def test_outline_tools_stay_mounted_after_leaving_outline(monkeypatch):
    from deeptutor.runtime.registry.deferred_tools import DeferredToolLoader

    state: dict[str, set[str]] = {}

    async def providers(self, context):
        loader = DeferredToolLoader(
            registry=self.registry, session_id=context.session_id, loaded=set(), allowed=set()
        )
        self._tool_view = ProviderToolView(
            registry=self.registry, loader=loader, pool=(), manifest=""
        )
        self._deferred_loader = loader

    monkeypatch.setattr(AgenticLoopPipeline, "_prepare_deferred_tools", providers)
    monkeypatch.setattr(
        "deeptutor.services.mcp.load_loaded_tools", lambda sid: set(state.get(sid, set()))
    )
    monkeypatch.setattr(
        "deeptutor.services.mcp.session_state.record_loaded_tools",
        lambda sid, names: state.__setitem__(sid, set(names)),
    )

    def tool_names(mode: str) -> list[str]:
        return [s["function"]["name"] for s in surfaces[mode]]

    surfaces: dict[str, list[dict]] = {}
    for mode in ("outline", "study"):
        pipeline = MasteryLoopPipeline(language="en")
        context = UnifiedContext(
            session_id="synthetic",
            metadata={"mastery_mode": True, "mastery_path_id": "p", "mastery_session_mode": mode},
        )
        await pipeline._prepare_deferred_tools(context)
        schemas = pipeline._build_llm_tool_schemas(
            pipeline._compose_enabled_tools(context), context
        )
        pipeline._tool_view.attach(schemas)
        surfaces[mode] = schemas

    assert {"mastery_build", "mastery_revise"} <= state["synthetic"]
    assert sorted(tool_names("outline")) == sorted(tool_names("study"))


@pytest.mark.asyncio
async def test_switching_to_outline_loads_the_tools_the_next_turn_mounts(monkeypatch):
    """A study turn that switches to outline ends with the outline turn's tools.

    Loading the outline tools one by one left the next turn (in outline mode,
    which mounts them all eagerly) with a schema more than the last request of
    the switching turn, so that turn started with a full cache miss.
    """
    from deeptutor.capabilities.mastery.loop import _mode_binder
    from deeptutor.runtime.registry.deferred_tools import DeferredToolLoader

    state: dict[str, set[str]] = {}

    async def providers(self, context):
        loader = DeferredToolLoader(
            registry=self.registry, session_id=context.session_id, loaded=set(), allowed=set()
        )
        self._tool_view = ProviderToolView(
            registry=self.registry, loader=loader, pool=(), manifest=""
        )
        self._deferred_loader = loader

    monkeypatch.setattr(AgenticLoopPipeline, "_prepare_deferred_tools", providers)
    monkeypatch.setattr(
        "deeptutor.services.mcp.load_loaded_tools", lambda sid: set(state.get(sid, set()))
    )
    monkeypatch.setattr(
        "deeptutor.services.mcp.session_state.record_loaded_tools",
        lambda sid, names: state.__setitem__(sid, set(names)),
    )

    async def turn(mode: str, *, switch_to: str | None = None) -> list[str]:
        pipeline = MasteryLoopPipeline(language="en")
        context = UnifiedContext(
            session_id="synthetic",
            metadata={"mastery_mode": True, "mastery_path_id": "p", "mastery_session_mode": mode},
        )
        await pipeline._prepare_deferred_tools(context)
        schemas = pipeline._build_llm_tool_schemas(
            pipeline._compose_enabled_tools(context), context
        )
        pipeline._tool_view.attach(schemas)
        if switch_to:
            _mode_binder(context)(switch_to)
        return [s["function"]["name"] for s in schemas]

    switching = await turn("study", switch_to="outline")
    following = await turn("outline")

    assert {"mastery_build", "mastery_revise"} <= set(switching)
    assert sorted(following) == sorted(switching)


@pytest.mark.asyncio
async def test_mode_switches_keep_tools_identical_without_other_deferred_tools(monkeypatch):
    """A fresh install has no MCP tools, so nothing else keeps a loader alive.

    Outline used to mount its tools eagerly and skip the loader, so an outline
    turn lost ``load_tools`` and placed the outline tools elsewhere in tools[]
    than the study turns around it.
    """
    state: dict[str, set[str]] = {}

    async def providers(self, context):
        self._tool_view = ProviderToolView.empty(self.registry)
        self._deferred_loader = None
        self._deferred_pool = []

    monkeypatch.setattr(AgenticLoopPipeline, "_prepare_deferred_tools", providers)
    monkeypatch.setattr(
        "deeptutor.services.mcp.load_loaded_tools", lambda sid: set(state.get(sid, set()))
    )
    monkeypatch.setattr(
        "deeptutor.services.mcp.session_state.record_loaded_tools",
        lambda sid, names, **_: state.__setitem__(sid, set(names)),
    )

    async def turn(mode: str) -> list[dict]:
        pipeline = MasteryLoopPipeline(language="en")
        context = UnifiedContext(
            session_id="synthetic",
            metadata={"mastery_mode": True, "mastery_path_id": "p", "mastery_session_mode": mode},
        )
        await pipeline._prepare_deferred_tools(context)
        schemas = pipeline._build_llm_tool_schemas(
            pipeline._compose_enabled_tools(context), context
        )
        pipeline._tool_view.attach(schemas)
        return schemas

    outline = await turn("outline")
    study = await turn("study")
    back = await turn("outline")

    names = [s["function"]["name"] for s in outline]
    assert {"load_tools", "mastery_build", "mastery_revise"} <= set(names)
    assert json.dumps(study) == json.dumps(outline)
    assert json.dumps(back) == json.dumps(outline)


@pytest.mark.asyncio
async def test_navigation_is_mounted_before_the_first_topic_exists(monkeypatch):
    """The first mastery turn usually creates the topic.

    Navigation used to mount only once a topic existed, so the second turn's
    tools[] grew by three schemas and missed the whole cached prefix.
    """
    topics = {"exist": False}

    async def providers(self, context):
        self._tool_view = ProviderToolView.empty(self.registry)
        self._deferred_loader = None
        self._deferred_pool = []

    monkeypatch.setattr(AgenticLoopPipeline, "_prepare_deferred_tools", providers)
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.user_has_mastery_topics", lambda: topics["exist"]
    )
    monkeypatch.setattr("deeptutor.services.mcp.load_loaded_tools", lambda _: set())
    monkeypatch.setattr(
        "deeptutor.services.mcp.session_state.record_loaded_tools", lambda *_, **__: None
    )

    async def names() -> list[str]:
        pipeline = MasteryLoopPipeline(language="en")
        context = UnifiedContext(
            session_id="synthetic",
            metadata={"mastery_mode": True, "mastery_session_mode": "study"},
        )
        await pipeline._prepare_deferred_tools(context)
        return pipeline._compose_enabled_tools(context)

    first = await names()
    topics["exist"] = True
    second = await names()

    assert "mastery_sessions" in first
    assert first == second
