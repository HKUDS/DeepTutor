"""Turn-scoped DeepTutor wrappers for PageIndex Cloud and OSS SDK tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
import json
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolLookup, ToolResult
from deeptutor.runtime.registry.scoped_registry import ScopedToolRegistry

from .pipeline import PageIndexPipeline
from .storage import CLOUD_PROVIDER, OSS_PROVIDER

TOOL_PREFIXES = {
    CLOUD_PROVIDER: "pageindex_cloud_",
    OSS_PROVIDER: "pageindex_oss_",
}


def pageindex_sources_from_text(
    text: str,
    *,
    provider: str,
    kb_name: str = "",
    doc_ids: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Normalize real PageIndex page reads into DeepTutor source rows."""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("success") is False or payload.get("errorCode"):
        return []
    document_name = str(payload.get("doc_name") or "").strip()
    content = payload.get("content")
    if not document_name or not isinstance(content, list):
        return []

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in content:
        if not isinstance(item, dict) or item.get("page") in (None, ""):
            continue
        page = item["page"]
        block_id = str(item.get("block_id") or "").strip()
        key = (str(page), block_id)
        if key in seen:
            continue
        seen.add(key)
        row: dict[str, Any] = {
            "type": "pageindex",
            "provider": provider,
            "document_name": document_name,
            "source": document_name,
            "page": page,
        }
        if kb_name:
            row["kb_name"] = kb_name
        if doc_ids and document_name in doc_ids:
            row["doc_id"] = doc_ids[document_name]
        if block_id:
            row["block_id"] = block_id
        rows.append(row)
    return rows


class PageIndexSDKTool(BaseTool):
    deferred = True
    provider_kind = "pageindex"

    def __init__(
        self,
        sdk_tool: Any,
        *,
        provider: str,
        kb_name: str,
        doc_ids: dict[str, str],
    ) -> None:
        self._sdk_tool = sdk_tool
        self.provider_id = provider
        self._kb_name = kb_name
        self._doc_ids = doc_ids

    def get_definition(self) -> ToolDefinition:
        label = "Cloud" if self.provider_id == CLOUD_PROVIDER else "OSS"
        return ToolDefinition(
            name=f"{TOOL_PREFIXES[self.provider_id]}{self._sdk_tool.name}",
            description=f"[PageIndex {label}: {self._kb_name}] {self._sdk_tool.description}",
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
            provider=self.provider_id,
            kb_name=self._kb_name,
            doc_ids=self._doc_ids,
        )
        return ToolResult(
            content=str(text),
            sources=sources,
            metadata={
                "pageindex_provider": self.provider_id,
                "kb_name": self._kb_name,
                "sources": sources,
            },
            success=success,
        )


@dataclass(frozen=True)
class PageIndexSDKToolBundle:
    provider: str
    tools: tuple[PageIndexSDKTool, ...]
    instructions: str
    documents: dict[str, str]


@dataclass(frozen=True)
class PageIndexToolContext:
    provider: str
    registry: ToolLookup
    tools: tuple[BaseTool, ...]
    instructions: str
    documents: dict[str, str]


@lru_cache(maxsize=1)
def _cloud_read_tools(client: Any) -> tuple[Any, ...]:
    """Cache live Cloud schemas on the SDK client that owns their MCP session."""
    return tuple(client.as_openai_tools(include_management=False))


async def build_sdk_tool_bundle(
    kb_name: str,
    kb_base_dir: str,
    *,
    provider: str,
) -> PageIndexSDKToolBundle:
    """Build one KB's read-only SDK tools without exposing their transport."""

    def build() -> PageIndexSDKToolBundle:
        pipeline = PageIndexPipeline(kb_base_dir=kb_base_dir, provider=provider)
        documents = pipeline.document_map(kb_name)
        client = pipeline.sdk_client_for_read(kb_name)
        sdk_tools = (
            client.as_openai_tools(include_management=False)
            if provider == OSS_PROVIDER
            else _cloud_read_tools(client)
        )
        instructions = client.agent_instructions()
        return PageIndexSDKToolBundle(
            provider=provider,
            tools=tuple(
                PageIndexSDKTool(
                    tool,
                    provider=provider,
                    kb_name=kb_name,
                    doc_ids=documents,
                )
                for tool in sdk_tools
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
    from deeptutor.services.rag.provider_binding import resolve_bound_provider

    resource = resolve_kb(kb_name, require_write=False)
    base_dir = str(resource.base_dir)
    provider = resolve_bound_provider(base_dir, resource.name)
    if provider in {CLOUD_PROVIDER, OSS_PROVIDER}:
        bundle = await build_sdk_tool_bundle(resource.name, base_dir, provider=provider)
        registry = ScopedToolRegistry(base=base_registry, overlay=bundle.tools)
        return PageIndexToolContext(
            provider=provider,
            registry=registry,
            tools=bundle.tools,
            instructions=bundle.instructions,
            documents=bundle.documents,
        )
    return None


__all__ = [
    "PageIndexSDKTool",
    "PageIndexSDKToolBundle",
    "PageIndexToolContext",
    "TOOL_PREFIXES",
    "build_sdk_tool_bundle",
    "build_pageindex_tool_context",
    "pageindex_sources_from_text",
]
