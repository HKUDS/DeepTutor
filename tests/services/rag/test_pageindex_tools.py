from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from deeptutor.services.rag.pipelines.pageindex import tools as tools_mod
from deeptutor.services.rag.pipelines.pageindex import validate_pageindex_oss_selection
from deeptutor.services.rag.pipelines.pageindex.storage import CLOUD_PROVIDER, OSS_PROVIDER
from deeptutor.services.rag.pipelines.pageindex.tools import (
    PageIndexSDKTool,
    pageindex_sources_from_text,
)


class _SDKTool:
    name = "get_page_content"
    description = "Read pages"
    params_json_schema = {
        "type": "object",
        "properties": {"doc_name": {"type": "string"}, "pages": {"type": "string"}},
        "required": ["doc_name", "pages"],
    }

    async def on_invoke_tool(self, _context, _args_json: str) -> str:
        return json.dumps(
            {
                "success": True,
                "doc_name": "manual.pdf",
                "content": [{"page": 3, "text": "grounded"}],
            }
        )


def test_page_content_emits_real_structured_sources() -> None:
    tool = PageIndexSDKTool(
        _SDKTool(),
        provider=OSS_PROVIDER,
        kb_name="manuals",
        doc_ids={"manual.pdf": "pi-1"},
    )

    result = asyncio.run(tool.execute(doc_name="manual.pdf", pages="3"))

    assert tool.name == "pageindex_oss_get_page_content"
    assert result.sources == [
        {
            "type": "pageindex",
            "provider": "pageindex-oss",
            "kb_name": "manuals",
            "document_name": "manual.pdf",
            "doc_id": "pi-1",
            "source": "manual.pdf",
            "page": 3,
        }
    ]
    assert result.metadata["sources"] == result.sources


def test_cloud_sdk_tool_uses_cloud_identity_and_sources() -> None:
    tool = PageIndexSDKTool(
        _SDKTool(),
        provider=CLOUD_PROVIDER,
        kb_name="hosted",
        doc_ids={"manual.pdf": "cloud-1"},
    )

    result = asyncio.run(tool.execute(doc_name="manual.pdf", pages="3"))

    assert tool.name == "pageindex_cloud_get_page_content"
    assert tool.provider_kind == "pageindex"
    assert tool.provider_id == CLOUD_PROVIDER
    assert result.sources[0]["provider"] == CLOUD_PROVIDER
    assert result.sources[0]["doc_id"] == "cloud-1"


class _SDKClient:
    def __init__(self) -> None:
        self.tool_calls: list[dict] = []
        self.instruction_calls: list[object] = []

    def as_openai_tools(self, **kwargs):
        self.tool_calls.append(kwargs)
        return [_SDKTool()]

    def agent_instructions(self, doc_id=None):
        self.instruction_calls.append(doc_id)
        return "SDK instructions"


@pytest.mark.parametrize("provider", [CLOUD_PROVIDER, OSS_PROVIDER])
def test_bundle_uses_unscoped_sdk_instructions(monkeypatch, provider: str) -> None:
    sdk_client = _SDKClient()

    class _Pipeline:
        def __init__(self, **_kwargs) -> None:
            pass

        def document_map(self, _kb_name: str) -> dict[str, str]:
            return {"manual.pdf": "cloud-1"}

        def sdk_client_for_read(self, _kb_name: str):
            return sdk_client

    monkeypatch.setattr(tools_mod, "PageIndexPipeline", _Pipeline)

    bundle = asyncio.run(tools_mod.build_sdk_tool_bundle("hosted", "/kb", provider=provider))

    assert sdk_client.tool_calls == [{"include_management": False}]
    assert sdk_client.instruction_calls == [None]
    assert bundle.provider == provider
    assert bundle.instructions == "SDK instructions"
    assert [tool.name for tool in bundle.tools] == [
        f"{'pageindex_oss' if provider == OSS_PROVIDER else 'pageindex_cloud'}_get_page_content"
    ]


def test_structure_or_failure_does_not_invent_page_sources() -> None:
    assert (
        pageindex_sources_from_text(
            json.dumps({"success": True, "doc_name": "manual.pdf", "structure": []}),
            provider="pageindex-oss",
        )
        == []
    )
    assert (
        pageindex_sources_from_text(
            json.dumps(
                {
                    "success": False,
                    "doc_name": "manual.pdf",
                    "content": [{"page": 9, "text": "not real"}],
                }
            ),
            provider="pageindex-oss",
        )
        == []
    )


def _patch_selection(monkeypatch, providers: dict[str, str]) -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb",
        lambda name, **_kwargs: SimpleNamespace(base_dir="/kb", name=name),
    )
    monkeypatch.setattr(
        "deeptutor.services.rag.provider_binding.resolve_bound_provider",
        lambda _base, name: providers[name],
    )


def test_rejects_two_oss_kbs(monkeypatch) -> None:
    _patch_selection(monkeypatch, {"one": "pageindex-oss", "two": "pageindex-oss"})
    with pytest.raises(ValueError, match="at most one"):
        validate_pageindex_oss_selection(["one", "two"])


def test_cloud_and_oss_can_coexist(monkeypatch) -> None:
    _patch_selection(
        monkeypatch,
        {"cloud": "pageindex", "oss": "pageindex-oss", "vectors": "llamaindex"},
    )
    validate_pageindex_oss_selection(["cloud", "oss", "vectors"])
