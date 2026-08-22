"""Chat-side PageIndex SDK tool wiring.

Attaching a PageIndex KB overlays the SDK's tools for that turn, preloads them
(no load_tools round-trip), and injects the SDK's reading instructions without
publishing PageIndex into the global MCP registry.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.runtime.registry.deferred_tools import render_deferred_tools_manifest


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

    async def ensure_scope(self, _owner: str) -> list[BaseTool]:
        return []


def _prepare(monkeypatch, docs: dict[str, dict[str, str]]) -> AgenticChatPipeline:
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    pipe = AgenticChatPipeline(language="en")
    other_tool = FakeMCPTool("other", "do_thing")
    pipe.registry = FakeRegistry([other_tool])

    pageindex_tool = FakeMCPTool("unused", "get_page_content")
    pageindex_tool._name = "pageindex_cloud_get_page_content"
    pageindex_tool.server_name = ""
    pageindex_tool.provider_kind = "pageindex"
    pageindex_tool.provider_id = "pageindex"

    monkeypatch.setattr("deeptutor.services.mcp.get_mcp_manager", lambda: FakeManager())
    monkeypatch.setattr("deeptutor.services.mcp.load_loaded_tools", lambda _sid: set())
    # Non-admin user without an MCP grant: fail-closed empty whitelist.
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_mcp_tools", lambda: set())
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.pageindex.is_pageindex_kb",
        lambda name: name in docs,
    )

    async def bundles(_ctx):
        if not docs:
            return []
        kb, documents = next(iter(docs.items()))
        return [
            (
                kb,
                SimpleNamespace(
                    provider="pageindex",
                    tools=(pageindex_tool,),
                    documents=documents,
                    instructions="Use structure, then pages.",
                ),
            )
        ]

    monkeypatch.setattr(pipe, "_pageindex_sdk_tool_bundles", bundles)

    ctx = UnifiedContext(knowledge_bases=list(docs))
    asyncio.run(pipe._prepare_deferred_tools(ctx))
    return pipe


def test_pageindex_kb_preloads_turn_scoped_sdk_tools(monkeypatch) -> None:
    pipe = _prepare(monkeypatch, {"kb1": {"a.pdf": "pi-1"}})

    pool_names = {t.get_definition().name for t in pipe._deferred_pool}
    assert pool_names == {"pageindex_cloud_get_page_content"}
    # Preloaded: schema present without a load_tools round-trip.
    assert pipe._deferred_loader is not None
    preloaded = {s["function"]["name"] for s in pipe._deferred_loader.initial_schemas()}
    assert "pageindex_cloud_get_page_content" in preloaded


def test_no_pageindex_kb_keeps_fail_closed(monkeypatch) -> None:
    pipe = _prepare(monkeypatch, {})
    assert pipe._deferred_pool == []
    assert pipe._deferred_loader is None


def test_system_note_omits_document_metadata(monkeypatch) -> None:
    pipe = _prepare(monkeypatch, {"kb1": {"a.pdf": "pi-1", "b.docx": "pi-2"}})
    note = pipe._kb_system_note(UnifiedContext(knowledge_bases=["kb1"]))
    assert "pageindex_cloud_*" in note
    assert "Do not use rag to read these PageIndex knowledge bases" in note
    assert "Use structure, then pages." in note
    assert "a.pdf" not in note
    assert "b.docx" not in note
    assert "doc_id" not in note
    # Pure-pageindex conversation: rag isn't mounted, so no rag wording at all.
    assert "calling rag" not in note


def test_rag_kbs_excludes_pageindex(monkeypatch) -> None:
    pipe = _prepare(monkeypatch, {"kb1": {"a.pdf": "pi-1"}})
    ctx = UnifiedContext(knowledge_bases=["kb1", "kb2"])
    # kb1 is pageindex → excluded from the rag tool surface; kb2 stays.
    assert pipe._rag_kbs(ctx) == ["kb2"]
    note = pipe._kb_system_note(ctx)
    assert "Attached knowledge bases: kb2." in note
    assert "kb1" not in note


def test_pageindex_kb_is_never_preseeded(monkeypatch) -> None:
    pipe = _prepare(monkeypatch, {"kb1": {"a.pdf": "pi-1"}})
    called: list[str] = []

    async def seed(kb, _query, _stream):
        called.append(kb)
        return "context", []

    monkeypatch.setattr(pipe, "_seed_search_one_kb", seed)
    context = UnifiedContext(user_message="question", knowledge_bases=["kb1", "kb2"])
    asyncio.run(pipe._retrieve_kb_seed_block(context, StreamBus()))
    assert called == ["kb2"]


def test_oss_tools_are_turn_scoped_preloaded_and_excluded_from_rag(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    pipe = AgenticChatPipeline(language="en")
    pipe.registry = FakeRegistry([])
    oss_tool = FakeMCPTool("pageindex_oss", "get_page_content")
    oss_tool._name = "pageindex_oss_get_page_content"
    oss_tool.server_name = ""

    monkeypatch.setattr("deeptutor.services.mcp.get_mcp_manager", lambda: FakeManager())
    monkeypatch.setattr("deeptutor.services.mcp.load_loaded_tools", lambda _sid: set())
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_mcp_tools", lambda: set())
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.pageindex.is_pageindex_kb",
        lambda name: name == "oss-kb",
    )

    async def bundles(_ctx):
        return [
            (
                "oss-kb",
                SimpleNamespace(
                    provider="pageindex-oss",
                    tools=(oss_tool,),
                    documents={"manual.pdf": "pi-local"},
                    instructions="Read structure, then pages.",
                ),
            )
        ]

    monkeypatch.setattr(pipe, "_pageindex_sdk_tool_bundles", bundles)
    ctx = UnifiedContext(knowledge_bases=["oss-kb", "vectors"])
    asyncio.run(pipe._prepare_deferred_tools(ctx))

    assert pipe.tool_lookup.get("pageindex_oss_get_page_content") is oss_tool
    assert pipe._rag_kbs(ctx) == ["vectors"]
    assert "pageindex_oss_get_page_content" in {
        schema["function"]["name"] for schema in pipe._deferred_loader.initial_schemas()
    }
    note = pipe._pageindex_system_note()
    assert "manual.pdf" not in note
    assert "doc_id" not in note
    assert "Read structure, then pages." in note
    assert "Do not use rag to read these PageIndex knowledge bases" in note


def test_pageindex_tools_keep_cloud_and_oss_manifest_groups() -> None:
    cloud = FakeMCPTool("unused", "get_page_content")
    cloud._name = "pageindex_cloud_get_page_content"
    cloud.provider_kind = "pageindex"
    cloud.provider_id = "pageindex"
    oss = FakeMCPTool("unused", "get_page_content")
    oss._name = "pageindex_oss_get_page_content"
    oss.provider_kind = "pageindex"
    oss.provider_id = "pageindex-oss"

    manifest = render_deferred_tools_manifest([cloud, oss])

    assert "### PageIndex Cloud" in manifest
    assert "### PageIndex OSS" in manifest
