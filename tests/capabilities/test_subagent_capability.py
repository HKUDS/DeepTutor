"""Tests for the subagent capability: binding, activation, tool budget/streaming.

The capability is the connected-agent twin of Obsidian — selecting a
``type: subagent`` KB runs the turn exclusively on ``consult_subagent``. These
tests stub the KB metadata resolver and the backend, so nothing spawns a real
CLI; they verify the wiring (binding, exclusivity, injected spec) and the tool's
authoritative consult-budget + session continuity + event streaming.
"""

from __future__ import annotations

import pytest

from deeptutor.agents._shared.tool_composition import ToolMountFlags, compose_enabled_tools
from deeptutor.capabilities import any_exclusive_capability_active
from deeptutor.capabilities.subagent import (
    SUBAGENT_TOOL_NAMES,
    ConsultSubagentTool,
    SubagentCapability,
    connection_for_turn,
)
from deeptutor.capabilities.subagent import binding as subagent_binding
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.types import ConsultResult, SubagentEvent


def _bind(monkeypatch, *, kind: str = "claude_code", cwd: str = "", name: str = "myagent") -> None:
    """Make ``resolve_kb_metadata`` report ``name`` as a connected subagent."""
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
        lambda ref: (
            {"name": ref, "type": "subagent", "agent_kind": kind, "cwd": cwd}
            if ref == name
            else {"name": ref, "type": None}
        ),
    )


# ---- binding & activation ----------------------------------------------------


def test_inactive_without_subagent_kb(monkeypatch) -> None:
    _bind(monkeypatch)
    cap = SubagentCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert cap.is_active(ctx) is False
    assert cap.system_block(ctx, language="en", prompts={}) is None


def test_active_injects_spec_and_min_rounds(monkeypatch) -> None:
    _bind(monkeypatch, kind="codex", cwd="/tmp/proj")
    cap = SubagentCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["myagent"])
    assert cap.is_active(ctx) is True
    assert tuple(cap.owned_tools) == SUBAGENT_TOOL_NAMES

    block = cap.system_block(ctx, language="en", prompts={})
    assert block is not None and "myagent" in block.content
    # The loop budget floor is lifted so the full consult budget + a finish
    # round always fit.
    assert ctx.runtime.min_loop_rounds >= 2

    spec = cap.augment_kwargs("consult_subagent", {"question": "q"}, ctx)["_subagent"]
    assert spec["kind"] == "codex"
    assert spec["cwd"] == "/tmp/proj"
    assert spec["budget"] >= 1
    assert isinstance(spec["config"], BackendConfig)
    assert spec["state"] == {"count": 0, "session_id": None, "name": "myagent"}
    # Never injected for a non-owned tool.
    assert "_subagent" not in cap.augment_kwargs("rag", {}, ctx)


def test_consult_budget_override_from_runtime_context(monkeypatch) -> None:
    _bind(monkeypatch)
    cap = SubagentCapability()
    # Typed per-turn override from the composer wins over the default.
    ctx = UnifiedContext(
        user_message="hi",
        knowledge_bases=["myagent"],
        runtime=TurnRuntimeContext(subagent_consult_budget=3),
    )
    assert (
        cap.augment_kwargs("consult_subagent", {"question": "q"}, ctx)["_subagent"]["budget"] == 3
    )
    # Out-of-range values are clamped, not trusted.
    ctx_hi = UnifiedContext(
        user_message="hi",
        knowledge_bases=["myagent"],
        runtime=TurnRuntimeContext(subagent_consult_budget=999),
    )
    assert (
        cap.augment_kwargs("consult_subagent", {"question": "q"}, ctx_hi)["_subagent"]["budget"]
        == 12
    )


def test_binding_cached(monkeypatch) -> None:
    calls = {"n": 0}

    def fake(ref):
        calls["n"] += 1
        return {"name": ref, "type": "subagent", "agent_kind": "claude_code", "cwd": ""}

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_metadata", fake)
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["a"])
    subagent_binding.connection_for_turn(ctx)
    subagent_binding.connection_for_turn(ctx)
    assert calls["n"] == 1  # second call hits the per-turn cache


# ---- exclusivity -------------------------------------------------------------


def test_exclusive_compose_drops_builtins_but_keeps_coexisting_rag() -> None:
    # Issue #650: the KB built-ins coexist when has_kb is set (a co-selected
    # real KB the capability does not own is both searchable and enumerable);
    # other built-ins/toggles stay dropped.
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search", "rag"],
        optional_whitelist=["web_search", "rag"],
        mount_flags=ToolMountFlags(has_kb=True, has_exec=True, has_memory=True),
        capability_owned=["consult_subagent"],
        exclusive=True,
    )
    assert set(composed) == {
        "workspace_list",
        "workspace_read",
        "workspace_search",
        "workspace_present",
        "consult_subagent",
        "rag",
        "kb_files",
        "ask_user",
    }


def test_exclusive_compose_pure_subagent_mounts_no_rag() -> None:
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search"],
        optional_whitelist=["web_search"],
        mount_flags=ToolMountFlags(has_kb=False),
        capability_owned=["consult_subagent"],
        exclusive=True,
    )
    assert set(composed) == {
        "workspace_list",
        "workspace_read",
        "workspace_search",
        "workspace_present",
        "consult_subagent",
        "ask_user",
    }


def test_registry_flags_subagent_turn_as_exclusive(monkeypatch) -> None:
    _bind(monkeypatch)
    subagent_turn = UnifiedContext(user_message="hi", knowledge_bases=["myagent"])
    plain_turn = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert any_exclusive_capability_active(subagent_turn) is True
    assert any_exclusive_capability_active(plain_turn) is False


def test_owned_kbs_reports_only_agent_ref(monkeypatch) -> None:
    # Issue #650: the agent ref is owned (consulted, not rag'd); a co-selected
    # LlamaIndex KB is not owned, so it keeps its rag surface.
    _bind(monkeypatch)  # only "myagent" resolves as a subagent
    cap = SubagentCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["myagent", "kb-plain"])
    assert cap.owned_kbs(ctx) == {"myagent"}
    assert subagent_binding.subagent_refs(ctx) == {"myagent"}


# ---- consult tool ------------------------------------------------------------


class _FakeBackend:
    kind = "claude_code"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.last_images: list[str] | None = None

    async def consult(
        self, question, *, on_event, cwd, session_id, config, images=None, partner_id=None
    ):
        self.calls.append((question, session_id))
        self.last_images = images
        await on_event(SubagentEvent(kind="tool", text="$ ls"))
        await on_event(SubagentEvent(kind="result", text=f"answer:{question}"))
        return ConsultResult(
            final_text=f"answer:{question}",
            session_id="sess-1",
            success=True,
            event_count=2,
        )


def _spec(state: dict, *, budget: int = 2) -> dict:
    return {
        "kind": "claude_code",
        "cwd": "",
        "name": "myagent",
        "budget": budget,
        "config": BackendConfig(),
        "state": state,
    }


@pytest.mark.asyncio
async def test_consult_streams_events_and_threads_session(monkeypatch) -> None:
    backend = _FakeBackend()
    monkeypatch.setattr("deeptutor.services.subagent.get_backend", lambda kind: backend)
    tool = ConsultSubagentTool()
    state: dict = {"count": 0, "session_id": None, "name": "myagent"}
    streamed: list[tuple[str, str, str]] = []

    async def sink(event_type, message, metadata=None):
        streamed.append((event_type, message, (metadata or {}).get("subagent_channel", "")))

    res1 = await tool.execute(question="Q1", _subagent=_spec(state), event_sink=sink)
    assert res1.success is True
    assert "answer:Q1" in res1.content
    assert state["count"] == 1
    assert state["session_id"] == "sess-1"  # captured for continuity
    # Every native event streamed out under the single subagent trace_kind.
    assert all(etype == "subagent_event" for etype, _, _ in streamed)
    channels = {chan for _, _, chan in streamed}
    assert "tool" in channels and "result" in channels

    # Second consult resumes the same backend session.
    await tool.execute(question="Q2", _subagent=_spec(state), event_sink=sink)
    assert backend.calls[1] == ("Q2", "sess-1")


@pytest.mark.asyncio
async def test_consult_budget_is_authoritative(monkeypatch) -> None:
    backend = _FakeBackend()
    monkeypatch.setattr("deeptutor.services.subagent.get_backend", lambda kind: backend)
    tool = ConsultSubagentTool()
    state: dict = {"count": 0, "session_id": None, "name": "myagent"}

    async def sink(*_a, **_k):
        return None

    await tool.execute(question="Q1", _subagent=_spec(state, budget=1), event_sink=sink)
    # Budget of 1 is spent → the second consult is refused without driving the backend.
    refused = await tool.execute(question="Q2", _subagent=_spec(state, budget=1), event_sink=sink)
    assert refused.success is False
    assert "budget" in refused.content.lower()
    assert len(backend.calls) == 1  # backend never invoked the second time


@pytest.mark.asyncio
async def test_consult_without_spec_is_graceful() -> None:
    res = await ConsultSubagentTool().execute(question="hi")
    assert res.success is False and "no subagent" in res.content.lower()


@pytest.mark.asyncio
async def test_session_id_persists_across_turns(monkeypatch, tmp_path) -> None:
    # A backend session id captured in one turn is remembered (keyed by chat
    # session + connection) and resumed by the next turn's augment_kwargs — so
    # the local agent keeps context across DeepTutor's separate messages.
    from deeptutor.services.subagent import sessions as sess

    monkeypatch.setattr(sess, "_path", lambda: tmp_path / "subagent_sessions.json")
    _bind(monkeypatch)  # "myagent" → claude_code
    backend = _FakeBackend()
    monkeypatch.setattr("deeptutor.services.subagent.get_backend", lambda kind: backend)

    cap = SubagentCapability()
    tool = ConsultSubagentTool()

    async def sink(*_a, **_k):
        return None

    # Turn 1: nothing remembered yet → consult creates "sess-1", which persists.
    ctx1 = UnifiedContext(user_message="hi", knowledge_bases=["myagent"], session_id="chatA")
    spec1 = cap.augment_kwargs("consult_subagent", {"question": "Q1"}, ctx1)["_subagent"]
    assert spec1["state"]["session_id"] is None
    await tool.execute(question="Q1", _subagent=spec1, event_sink=sink)
    assert sess.get_session(sess.session_key("chatA", "myagent")) == "sess-1"

    # Turn 2 (fresh context): augment_kwargs seeds the remembered session.
    ctx2 = UnifiedContext(user_message="more", knowledge_bases=["myagent"], session_id="chatA")
    spec2 = cap.augment_kwargs("consult_subagent", {"question": "Q2"}, ctx2)["_subagent"]
    assert spec2["state"]["session_id"] == "sess-1"

    # A different chat session does not inherit the agent session.
    ctx3 = UnifiedContext(user_message="hi", knowledge_bases=["myagent"], session_id="chatB")
    spec3 = cap.augment_kwargs("consult_subagent", {"question": "Q"}, ctx3)["_subagent"]
    assert spec3["state"]["session_id"] is None
