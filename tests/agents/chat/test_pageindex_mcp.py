"""Chat-side PageIndex MCP wiring.

Attaching a PageIndex KB grants the turn the built-in pageindex MCP server's
tools (narrowed implicit grant), preloads them (no load_tools round-trip),
and injects the KB's document list into the system prompt.
"""

from __future__ import annotations

import asyncio

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult


class FakeMCPTool(BaseTool):
    deferred = True

    def __init__(self, server: str, name: str) -> None:
        self.server_name = server
        self._name = f"mcp_{server}_{name}"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description="fake",
            raw_parameters={"type": "object", "properties": {}},
        )

    async def execute(self, **kwargs) -> ToolResult:  # pragma: no cover - unused
        return ToolResult(content="")


class FakeRegistry:
    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = {t.get_definition().name: t for t in tools}

    def deferred_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)


class FakeManager:
    async def ensure_started(self) -> None:
        return None


def _prepare(monkeypatch, docs: dict[str, dict[str, str]]) -> AgenticChatPipeline:
    pipe = AgenticChatPipeline(language="en")
    pageindex_tool = FakeMCPTool("pageindex", "get_page_content")
    other_tool = FakeMCPTool("other", "do_thing")
    pipe.registry = FakeRegistry([pageindex_tool, other_tool])

    monkeypatch.setattr("deeptutor.services.mcp.get_mcp_manager", lambda: FakeManager())
    monkeypatch.setattr("deeptutor.services.mcp.load_loaded_tools", lambda _sid: set())
    # Non-admin user without an MCP grant: fail-closed empty whitelist.
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_mcp_tools", lambda: set())
    monkeypatch.setattr(pipe, "_pageindex_doc_maps", lambda _ctx: docs)

    ctx = UnifiedContext(knowledge_bases=list(docs))
    asyncio.run(pipe._prepare_deferred_tools(ctx))
    return pipe


def test_pageindex_kb_grants_and_preloads_server_tools(monkeypatch) -> None:
    pipe = _prepare(monkeypatch, {"kb1": {"a.pdf": "pi-1"}})

    pool_names = {t.get_definition().name for t in pipe._deferred_pool}
    # Implicit grant covers exactly the pageindex server, not other MCP tools.
    assert pool_names == {"mcp_pageindex_get_page_content"}
    # Preloaded: schema present without a load_tools round-trip.
    assert pipe._deferred_loader is not None
    preloaded = {s["function"]["name"] for s in pipe._deferred_loader.initial_schemas()}
    assert "mcp_pageindex_get_page_content" in preloaded


def test_no_pageindex_kb_keeps_fail_closed(monkeypatch) -> None:
    pipe = _prepare(monkeypatch, {})
    assert pipe._deferred_pool == []
    assert pipe._deferred_loader is None


def test_system_note_lists_documents(monkeypatch) -> None:
    pipe = _prepare(monkeypatch, {"kb1": {"a.pdf": "pi-1", "b.docx": "pi-2"}})
    note = pipe._kb_system_note(UnifiedContext(knowledge_bases=["kb1"]))
    assert "mcp_pageindex_get_document_structure" in note
    assert "a.pdf (doc_id: pi-1)" in note
    assert "b.docx (doc_id: pi-2)" in note
    # Pure-pageindex conversation: rag isn't mounted, so no rag wording at all.
    assert "calling rag" not in note


def test_rag_kbs_excludes_pageindex(monkeypatch) -> None:
    pipe = _prepare(monkeypatch, {"kb1": {"a.pdf": "pi-1"}})
    ctx = UnifiedContext(knowledge_bases=["kb1", "kb2"])
    # kb1 is pageindex → excluded from the rag tool surface; kb2 stays.
    assert pipe._rag_kbs(ctx) == ["kb2"]
    note = pipe._kb_system_note(ctx)
    assert "Attached knowledge bases: kb2." in note
    assert "kb1" in note  # listed in the PageIndex MCP block instead
