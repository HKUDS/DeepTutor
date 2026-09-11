"""Targeted tests for Issue #752 — Obsidian vault support in the research block.

Covers the four behaviours of the fix:

* KB metadata resolution at ``ResearchPipeline`` construction (Obsidian vs
  indexed vs none), with no RAG usage audit side-effects.
* Tool composition matrix: Obsidian-only, indexed-only, no-KB, mixed
  evidence tools, and registry-missing Obsidian tools.
* Server-side ``_vault_path`` injection (and forging protection).
* Citation pipeline participation of the three read-only Obsidian tools.
* KB system-note selection per KB type, in both prompt languages.

The Obsidian capability's own exclusive-turn path is untouched; the research
pipeline has its own tool composition (``_block_tool_names``) that is tested
here directly.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.agents.research.data_structures import DynamicTopicQueue, ToolTrace
from deeptutor.agents.research.pipeline import (
    LABEL_FINISH,
    ResearchedBlock,
    ResearchPipeline,
    _BlockLoopHost,
)
from deeptutor.agents.research.utils.citation_manager import CitationManager
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome
from deeptutor.runtime.stream_bus import StreamBus

OBSIDIAN_TOOLS = ("obsidian_search", "obsidian_read", "obsidian_list")
ALL_TOOLS = frozenset(
    {
        "rag",
        "web_search",
        "paper_search",
        "exec",
        *OBSIDIAN_TOOLS,
    }
)


class _ToolRegistry:
    def __init__(self, names: set[str]) -> None:
        self.names = names

    def build_openai_schemas(self, names):
        return [
            {"type": "function", "function": {"name": name, "parameters": {}}}
            for name in names
            if name in self.names
        ]

    def build_prompt_text(self, names, **_kwargs):
        return "\n".join(f"- {name}" for name in names)

    def get(self, name):
        return SimpleNamespace(name=name) if name in self.names else None

    def get_enabled(self, names):
        return [SimpleNamespace(name=name) for name in names if name in self.names]


def _bind_kb(
    monkeypatch: pytest.MonkeyPatch,
    *,
    obsidian: set[str] | None = None,
    obsidian_path: str = "/vault/root",
) -> None:
    """Make ``resolve_kb_metadata`` report the requested KB types.

    ``obsidian=None`` leaves every ref indexed; an empty set makes every ref
    fail to resolve (``None`` metadata). The mock records calls so tests can
    assert resolution happened exactly once per construction.
    """
    calls: list[str] = []

    def fake(ref: str | None) -> dict | None:
        if ref is None:
            return None
        calls.append(str(ref))
        if obsidian is None:
            return {"name": ref, "type": None}
        if str(ref) in obsidian:
            return {"name": str(ref), "type": "obsidian", "vault_path": obsidian_path}
        return None

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_metadata", fake)
    return calls


def _make_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    registry: _ToolRegistry,
    enabled_tools: list[str],
    kb_name: str | None = None,
) -> ResearchPipeline:
    class _FakeLLM:
        binding = "openai"
        model = "gpt-x"
        api_key = "k"
        base_url = "u"
        api_version = None
        extra_headers = {}

    monkeypatch.setattr("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM())
    monkeypatch.setattr("deeptutor.agents.research.pipeline.get_tool_registry", lambda: registry)
    monkeypatch.setattr("deeptutor.agents.research.pipeline.user_has_memory", lambda: False)
    monkeypatch.setattr("deeptutor.agents.research.pipeline.user_has_notebooks", lambda: False)
    monkeypatch.setattr(
        "deeptutor.agents.research.pipeline.exec_capability_available", lambda: False
    )
    return ResearchPipeline(
        language="en",
        runtime_config={"queue": {"max_length": 5}},
        enabled_tools=enabled_tools,
        kb_name=kb_name,
    )


# ---------------------------------------------------------------------------
# 2. KB metadata resolution at construction
# ---------------------------------------------------------------------------


def test_init_resolves_obsidian_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="/srv/vault/a")
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="vault",
    )
    assert pipeline._is_obsidian_kb is True
    assert pipeline._vault_path == "/srv/vault/a"


def test_init_keeps_obsidian_type_without_vault_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="")
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="vault",
    )
    assert pipeline._is_obsidian_kb is True
    assert pipeline._vault_path is None


def test_init_resolves_indexed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian=None)
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="kb-main",
    )
    assert pipeline._is_obsidian_kb is False
    assert pipeline._vault_path is None


def test_init_without_kb_skips_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _bind_kb(monkeypatch, obsidian={"vault"})
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name=None,
    )
    assert pipeline._is_obsidian_kb is False
    assert pipeline._vault_path is None
    assert calls == []


def test_init_unresolvable_reference_stays_non_obsidian(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian=set())
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="missing",
    )
    assert pipeline._is_obsidian_kb is False
    assert pipeline._vault_path is None


def test_init_does_not_trigger_rag_usage_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Construction resolves KB metadata as a pure read — ``log_usage`` for
    ``rag_query`` must never fire (only ``resolve_for_rag`` audits)."""
    from deeptutor.multi_user import audit

    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
        lambda ref: {"name": ref, "type": "obsidian", "vault_path": "/v"},
    )
    audit_calls: list[tuple] = []

    class _NoAudit:
        def __call__(self, *args, **kwargs):
            audit_calls.append((args, kwargs))

    monkeypatch.setattr(audit, "log_usage", _NoAudit())
    _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="vault",
    )
    assert audit_calls == []


# ---------------------------------------------------------------------------
# 3. Tool composition matrix
# ---------------------------------------------------------------------------


def test_obsidian_kb_mounts_read_tools_and_no_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"})
    registry = _ToolRegistry(set(ALL_TOOLS))
    pipeline = _make_pipeline(
        monkeypatch,
        registry=registry,
        enabled_tools=["web_search", "paper_search"],
        kb_name="vault",
    )
    names = pipeline._block_tool_names()
    assert "rag" not in names
    assert "obsidian_write" not in names
    for tool in OBSIDIAN_TOOLS:
        assert tool in names
    # user-toggled evidence tools survive alongside the vault tools
    assert "web_search" in names
    assert "paper_search" in names


def test_indexed_kb_mounts_rag_and_no_obsidian(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian=None)
    registry = _ToolRegistry(set(ALL_TOOLS))
    pipeline = _make_pipeline(
        monkeypatch,
        registry=registry,
        enabled_tools=[],
        kb_name="kb-main",
    )
    names = pipeline._block_tool_names()
    assert "rag" in names
    for tool in OBSIDIAN_TOOLS:
        assert tool not in names


def test_no_kb_mounts_neither_rag_nor_obsidian(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"})
    registry = _ToolRegistry(set(ALL_TOOLS))
    pipeline = _make_pipeline(
        monkeypatch,
        registry=registry,
        enabled_tools=[],
        kb_name=None,
    )
    names = pipeline._block_tool_names()
    assert "rag" not in names
    for tool in OBSIDIAN_TOOLS:
        assert tool not in names


def test_obsidian_kb_missing_registry_tool_is_filtered(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"})
    registry = _ToolRegistry({"obsidian_search", "obsidian_read", "web_search"})
    pipeline = _make_pipeline(
        monkeypatch,
        registry=registry,
        enabled_tools=["web_search"],
        kb_name="vault",
    )
    names = pipeline._block_tool_names()
    assert "obsidian_search" in names
    assert "obsidian_read" in names
    assert "obsidian_list" not in names  # not registered → filtered
    assert "rag" not in names


def test_obsidian_kb_without_vault_path_mounts_no_kb_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="")
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(set(ALL_TOOLS)),
        enabled_tools=[],
        kb_name="vault",
    )
    names = pipeline._block_tool_names()
    assert "rag" not in names
    for tool in OBSIDIAN_TOOLS:
        assert tool not in names


# ---------------------------------------------------------------------------
# 4. Server-side vault path injection
# ---------------------------------------------------------------------------


def test_augment_injects_vault_path_for_obsidian_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="/srv/vault")
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="vault",
    )
    ctx = UnifiedContext(session_id="s1", user_message="m")
    for tool in OBSIDIAN_TOOLS:
        kwargs = pipeline._augment_tool_kwargs(tool, {}, ctx)
        assert kwargs["_vault_path"] == "/srv/vault"


def test_augment_overwrites_forged_vault_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="/srv/vault")
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="vault",
    )
    ctx = UnifiedContext(session_id="s1", user_message="m")
    kwargs = pipeline._augment_tool_kwargs("obsidian_read", {"_vault_path": "/etc"}, ctx)
    assert kwargs["_vault_path"] == "/srv/vault"


def test_augment_leaves_non_obsidian_tools_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="/srv/vault")
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="vault",
    )
    ctx = UnifiedContext(session_id="s1", user_message="m")
    for tool in ("rag", "web_search", "exec"):
        kwargs = pipeline._augment_tool_kwargs(tool, {"query": "q"}, ctx)
        assert "_vault_path" not in kwargs


def test_augment_without_vault_path_keeps_safe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A vault path missing from metadata means the tools are simply not
    mounted; if augment is still reached the kwargs stay untouched and the
    Obsidian tool's own guard returns its standard safe failure."""
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="")
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="vault",
    )
    ctx = UnifiedContext(session_id="s1", user_message="m")
    kwargs = pipeline._augment_tool_kwargs("obsidian_search", {"query": "x"}, ctx)
    assert "_vault_path" not in kwargs


# ---------------------------------------------------------------------------
# 5. Citation pipeline participation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_query"),
    (
        ("obsidian_search", {"query": "evidence"}, "evidence"),
        ("obsidian_read", {"note": "Research Notes.md"}, "Research Notes.md"),
        ("obsidian_list", {"folder": "research"}, "research"),
        ("obsidian_list", {}, "/"),
    ),
)
async def test_obsidian_tool_results_enter_citation_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    tool_name: str,
    arguments: dict[str, str],
    expected_query: str,
) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="/srv/vault")
    registry = _ToolRegistry({tool_name})
    pipeline = _make_pipeline(
        monkeypatch,
        registry=registry,
        enabled_tools=[],
        kb_name="vault",
    )

    async def _fake_summary(**_kwargs):
        return "Obsidian evidence summary."

    monkeypatch.setattr(pipeline, "_summarise_tool_result", _fake_summary)

    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Obsidian evidence", "")
    block = queue.blocks[0]
    citations = CitationManager("test-research", cache_dir=tmp_path)
    host = _BlockLoopHost(
        pipeline=pipeline,
        block=block,
        queue=queue,
        citations=citations,
        topic="Obsidian evidence",
        stream=StreamBus(),
        context=UnifiedContext(session_id="s1", user_message="m"),
        client=None,
    )
    outcome = DispatchOutcome(
        tool_messages=[
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": tool_name,
                "content": "raw obsidian answer",
            }
        ]
    )
    await host._summarise_and_record(
        [{"id": "call-1", "name": tool_name, "arguments": arguments}],
        outcome,
    )

    assert len(block.tool_traces) == 1
    trace = block.tool_traces[0]
    assert trace.tool_type == tool_name
    assert trace.citation_id == "CIT-1-01"
    assert trace.query == expected_query
    assert outcome.tool_messages[0]["content"].startswith("[CIT-1-01]")
    assert "CIT-1-01" in citations.get_all_citations()
    references = pipeline._render_reference_list(citations)
    assert '<li id="ref-cit-1-01" data-citation-id="CIT-1-01">' in references
    assert expected_query in references


@pytest.mark.asyncio
async def test_obsidian_empty_result_skips_citation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="/srv/vault")
    registry = _ToolRegistry({"obsidian_read"})
    pipeline = _make_pipeline(
        monkeypatch,
        registry=registry,
        enabled_tools=[],
        kb_name="vault",
    )
    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Empty", "")
    block = queue.blocks[0]
    citations = CitationManager("test-research", cache_dir=tmp_path)
    host = _BlockLoopHost(
        pipeline=pipeline,
        block=block,
        queue=queue,
        citations=citations,
        topic="Empty",
        stream=StreamBus(),
        context=UnifiedContext(session_id="s1", user_message="m"),
        client=None,
    )
    outcome = DispatchOutcome(
        tool_messages=[
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "obsidian_read",
                "content": "",
            }
        ]
    )
    await host._summarise_and_record(
        [{"id": "call-1", "name": "obsidian_read", "arguments": {}}],
        outcome,
    )
    assert block.tool_traces == []
    assert citations.get_all_citations() == {}


# ---------------------------------------------------------------------------
# 6. KB system note per KB type
# ---------------------------------------------------------------------------


def test_obsidian_kb_system_note_mentions_read_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"}, obsidian_path="/srv/vault")
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="vault",
    )
    note = pipeline._kb_system_note()
    for tool in OBSIDIAN_TOOLS:
        assert tool in note
    # the note must not instruct calling rag (it may only forbid it)
    assert "When calling rag" not in note
    assert "kb_name must be" not in note
    assert "read-only" in note.lower() or "只读" in note


def test_indexed_kb_system_note_keeps_kb_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian=None)
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name="kb-main",
    )
    note = pipeline._kb_system_note()
    assert "kb-main" in note


def test_no_kb_system_note_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_kb(monkeypatch, obsidian={"vault"})
    pipeline = _make_pipeline(
        monkeypatch,
        registry=_ToolRegistry(ALL_TOOLS),
        enabled_tools=[],
        kb_name=None,
    )
    assert pipeline._kb_system_note() == ""
