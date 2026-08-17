"""Turn-scoped DeepTutor wrappers for PageIndex OSS SDK tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolLookup, ToolResult
from deeptutor.runtime.registry.scoped_registry import ScopedToolRegistry

from .pipeline import PageIndexPipeline
from .sources import pageindex_sources_from_text
from .storage import OSS_PROVIDER

TOOL_PREFIX = "pageindex_oss_"


class PageIndexOSSTool(BaseTool):
    deferred = True
    provider_kind = "pageindex"
    provider_id = OSS_PROVIDER

    def __init__(
        self,
        sdk_tool: Any,
        *,
        kb_name: str,
        doc_ids: dict[str, str],
    ) -> None:
        self._sdk_tool = sdk_tool
        self._kb_name = kb_name
        self._doc_ids = doc_ids

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=f"{TOOL_PREFIX}{self._sdk_tool.name}",
            description=f"[PageIndex OSS: {self._kb_name}] {self._sdk_tool.description}",
            raw_parameters=dict(self._sdk_tool.params_json_schema),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        kwargs.pop("event_sink", None)
        text = await self._sdk_tool.on_invoke_tool(
            None,
            json.dumps(kwargs, ensure_ascii=False),
        )
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            payload = {}
        success = not (
            isinstance(payload, dict)
            and (payload.get("success") is False or payload.get("errorCode"))
        )
        sources = pageindex_sources_from_text(
            str(text),
            provider=OSS_PROVIDER,
            kb_name=self._kb_name,
            doc_ids=self._doc_ids,
        )
        return ToolResult(
            content=str(text),
            sources=sources,
            metadata={
                "pageindex_provider": OSS_PROVIDER,
                "kb_name": self._kb_name,
                "sources": sources,
            },
            success=success,
        )


@dataclass(frozen=True)
class PageIndexOSSToolBundle:
    tools: tuple[PageIndexOSSTool, ...]
    instructions: str
    documents: dict[str, str]


@dataclass(frozen=True)
class PageIndexToolContext:
    provider: str
    kb_name: str
    registry: ToolLookup
    tools: tuple[BaseTool, ...]
    instructions: str
    documents: dict[str, str]


async def build_oss_tool_bundle(kb_name: str, kb_base_dir: str) -> PageIndexOSSToolBundle:
    """Build the SDK's read-only tools, hard-scoped to one OSS KB."""

    def build() -> PageIndexOSSToolBundle:
        pipeline = PageIndexPipeline(kb_base_dir=kb_base_dir, provider=OSS_PROVIDER)
        documents = pipeline.document_map(kb_name)
        client = pipeline.sdk_client_for_read(kb_name)
        doc_ids = list(documents.values())
        sdk_tools = client.as_openai_tools(doc_id=doc_ids)
        instructions = client.agent_instructions(doc_id=doc_ids)
        return PageIndexOSSToolBundle(
            tools=tuple(
                PageIndexOSSTool(tool, kb_name=kb_name, doc_ids=documents) for tool in sdk_tools
            ),
            instructions=str(instructions or ""),
            documents=documents,
        )

    return await asyncio.to_thread(build)


async def build_pageindex_tool_context(
    kb_name: str | None,
    *,
    base_registry: ToolLookup,
) -> PageIndexToolContext | None:
    """Resolve one PageIndex KB into tools for an existing workflow loop."""
    if not kb_name:
        return None
    from deeptutor.multi_user.knowledge_access import resolve_kb
    from deeptutor.services.rag.factory import PAGEINDEX_PROVIDER
    from deeptutor.services.rag.provider_binding import resolve_bound_provider

    resource = resolve_kb(kb_name, require_write=False)
    base_dir = str(resource.base_dir)
    provider = resolve_bound_provider(base_dir, resource.name)
    pipeline = PageIndexPipeline(kb_base_dir=base_dir, provider=provider)
    documents = pipeline.document_map(resource.name)
    if provider == OSS_PROVIDER:
        bundle = await build_oss_tool_bundle(resource.name, base_dir)
        registry = ScopedToolRegistry(base=base_registry, overlay=bundle.tools)
        return PageIndexToolContext(
            provider=provider,
            kb_name=kb_name,
            registry=registry,
            tools=bundle.tools,
            instructions=bundle.instructions,
            documents=bundle.documents,
        )
    if provider == PAGEINDEX_PROVIDER:
        from deeptutor.services.mcp import get_mcp_manager
        from deeptutor.services.mcp.pageindex_server import PAGEINDEX_SERVER_NAME

        manager = get_mcp_manager()
        await manager.ensure_started()
        tools = tuple(
            tool
            for tool in manager.adapters_for()
            if getattr(tool, "provider_id", "") == PAGEINDEX_SERVER_NAME
        )
        return PageIndexToolContext(
            provider=provider,
            kb_name=kb_name,
            registry=base_registry,
            tools=tools,
            instructions="",
            documents=documents,
        )
    return None


__all__ = [
    "PageIndexOSSTool",
    "PageIndexOSSToolBundle",
    "PageIndexToolContext",
    "TOOL_PREFIX",
    "build_oss_tool_bundle",
    "build_pageindex_tool_context",
]
