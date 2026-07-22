"""Tests for RAG/KB consistency at the capability layer.

After the refactor, RAG is no longer a user-selectable tool — its availability
is derived from whether any knowledge bases are attached for the turn.
These tests pin the contract that:

* ``deep_solve`` now runs on the chat agent loop (solve loop capability), reusing
  chat's *full* tool surface unchanged: ``rag`` auto-mounts iff a KB is
  attached, and user-toggleable tools (web_search, …) appear only when the
  user enabled them — exactly as in a plain chat turn. The plugin only *adds*
  its own ``solve_*`` tools on top.
* ``deep_research`` uses the same tool-composition policy as chat
  (``compose_enabled_tools``): the user's composer toggles flow through
  to the pipeline unchanged, ``rag`` auto-mounts iff a KB is attached.
  The legacy per-source gating (``sources: ["kb", "web", "papers"]``)
  has been removed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus


async def _drain(bus: StreamBus, task) -> list[StreamEvent]:
    await task
    await bus.close()
    return [event async for event in bus.subscribe()]


def _fake_llm_config() -> MagicMock:
    cfg = MagicMock()
    cfg.api_key = "sk-test"
    cfg.base_url = None
    cfg.api_version = None
    return cfg


# ---------------------------------------------------------------------------
# deep_solve: rag presence is keyed on attached KB
# ---------------------------------------------------------------------------


def _solve_pipeline(monkeypatch: pytest.MonkeyPatch) -> AgenticChatPipeline:
    """A bare pipeline whose only wired surface is tool composition."""
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_raw=lambda *_a, **_k: ""),
    )
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(list_notebooks=lambda: []),
    )
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline._deferred_loader = None
    pipeline._exec_enabled = False
    pipeline.registry = SimpleNamespace(
        get_enabled=lambda selected: [SimpleNamespace(name=n) for n in selected]
    )
    return pipeline


def test_deep_solve_omits_rag_when_no_knowledge_base(monkeypatch: pytest.MonkeyPatch) -> None:
    # Solve reuses chat's full surface: no KB → rag absent, and a user-toggle
    # tool the user did not enable (web_search) stays absent — the plugin never
    # force-mounts. Only its own solve_* tools are added.
    pipeline = _solve_pipeline(monkeypatch)
    context = UnifiedContext(
        user_message="solve x^2 = 4",
        metadata={"solve_mode": True, "solve_session_id": "turn-1"},
        knowledge_bases=[],
    )
    tools = pipeline._compose_enabled_tools(context)
    assert "rag" not in tools
    assert "web_search" not in tools  # not toggled on → not mounted (respects user)
    assert "solve_plan" in tools


def test_deep_solve_mounts_rag_when_knowledge_base_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _solve_pipeline(monkeypatch)
    context = UnifiedContext(
        user_message="solve x^2 = 4",
        metadata={"solve_mode": True, "solve_session_id": "turn-1"},
        knowledge_bases=["my-kb"],
    )
    tools = pipeline._compose_enabled_tools(context)
    assert "rag" in tools
    assert "solve_plan" in tools


# ---------------------------------------------------------------------------
# deep_research: tool composition matches chat (no sources gating)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deep_research_forwards_enabled_tools_and_kb_unchanged() -> None:
    """The capability passes the user's composer toggles (``enabled_tools``)
    and the attached KB (``kb_name``) through to the pipeline as-is. There
    is no per-source gating: ``compose_enabled_tools`` (run inside the
    pipeline) is the single arbiter of what the block loop sees."""
    from deeptutor.agents.research.capability import DeepResearchCapability

    captured_kwargs: dict[str, Any] = {}

    class _FakePipeline:
        def __init__(self, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

        async def run(self, *, stream: StreamBus, **_kwargs: Any) -> dict[str, Any]:
            return {
                "response": "",
                "output_dir": "",
                "outline_preview": True,
                "topic": "topic",
                "sub_topics": [{"title": "Subtopic 1", "overview": "Overview 1"}],
            }

    capability = DeepResearchCapability()
    bus = StreamBus()
    context = UnifiedContext(
        user_message="A topic to research",
        active_capability="deep_research",
        enabled_tools=["web_search", "paper_search"],
        knowledge_bases=["my-kb"],
        config_overrides={
            "mode": "report",
            "depth": "standard",
        },
        language="en",
    )

    with (
        patch(
            "deeptutor.agents.research.capability.ResearchPipeline",
            new=_FakePipeline,
        ),
        patch(
            "deeptutor.services.llm.config.get_llm_config",
            return_value=_fake_llm_config(),
        ),
        patch(
            "deeptutor.agents.research.capability.load_config_with_main",
            return_value={},
        ),
    ):
        await _drain(bus, capability.run(context, bus))

    assert captured_kwargs["enabled_tools"] == ["web_search", "paper_search"]
    assert captured_kwargs["kb_name"] == "my-kb"
    runtime_config = captured_kwargs.get("runtime_config") or {}
    researching = runtime_config.get("researching", {})
    # The legacy per-source enable_* flags must not appear in the
    # runtime config — composition is the pipeline's job.
    assert "enable_rag" not in researching
    assert "enable_web_search" not in researching
    assert "enable_paper_search" not in researching
    assert "enable_run_code" not in researching
    assert "sources" not in runtime_config.get("intent", {})
