from __future__ import annotations

import asyncio
import json

from deeptutor.services.rag.pipelines.pageindex.sources import pageindex_sources_from_text
from deeptutor.services.rag.pipelines.pageindex.tools import PageIndexOSSTool


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
    tool = PageIndexOSSTool(
        _SDKTool(),
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
