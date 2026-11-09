"""RAG tool selector contract regressions (issues #1928 and #2374).

Offline, LLM-free checks on a synthetic single-page PDF: the advertised
schema must match what execution enforces (optional selectors accept null,
pages are one-based integers, crops are four coordinates in 0..1), legacy
``region=[]`` placeholders mean "full page" instead of switching retrieval
modes, and malformed selectors fail visibly with a correctable message
instead of being clamped or replaced with other evidence.

``source_path`` alone is a document scope, not a visual request (#2374):
the query stays on the text path, restricted to that one document, and a
backend that cannot enforce the scope — or a document with no matching
passage — fails explicitly instead of mixing in other files. True visual
selectors (page, figure, region, asset_id, or page/figure references in
the query) still route to exact-source visual inspection.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from deeptutor.services.llm.provider_core.openai_responses.converters import convert_tools
from deeptutor.tools.builtin import RAGTool


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    raw = tmp_path / "kb" / "raw"
    raw.mkdir(parents=True)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((50, 50), "Manual: inspect the pump seal before restart")
    page.draw_line((50, 90), (300, 90))
    pdf.save(raw / "manual.pdf", deflate=True)
    pdf.close()
    return raw.parent


@pytest.fixture
def rag_calls(kb: Path, monkeypatch: pytest.MonkeyPatch):
    """Record semantic retrieval; visual resolution is patched per test."""
    calls: dict[str, list] = {"rag_search": [], "resolve_for_rag": []}

    async def fake_rag_search(**kwargs):
        calls["rag_search"].append(kwargs)
        return {"answer": "semantic answer", "sources": []}

    def fake_resolve(kb_name):
        calls["resolve_for_rag"].append(kb_name)
        return SimpleNamespace(base_dir=kb.parent, name=kb.name)

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_for_rag", fake_resolve)
    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", fake_rag_search)
    return calls


def _schema() -> dict:
    schema = RAGTool().get_definition().to_openai_schema()["function"]["parameters"]
    assert isinstance(schema, dict)
    return schema


def test_advertised_schema_matches_execution_contract():
    schema = _schema()
    properties = schema["properties"]
    assert schema["required"] == ["query", "kb_name"]
    assert properties["query"]["type"] == "string"
    assert properties["kb_name"]["type"] == "string"
    for name in ("source_path", "asset_id", "figure", "source_hash"):
        assert properties[name]["type"] == ["string", "null"], name
    assert properties["page"]["type"] == ["integer", "null"]
    assert properties["page"]["minimum"] == 1
    region = properties["region"]
    assert region["type"] == ["array", "null"]
    assert region["minItems"] == 4 and region["maxItems"] == 4
    assert region["items"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert "full page" in region["description"]


def test_responses_conversion_retains_selector_semantics():
    converted = convert_tools([RAGTool().get_definition().to_openai_schema()])
    assert len(converted) == 1
    parameters = converted[0]["parameters"]
    assert parameters["properties"]["page"]["minimum"] == 1
    assert parameters["properties"]["page"]["type"] == ["integer", "null"]
    region = parameters["properties"]["region"]
    assert region["minItems"] == 4 and region["maxItems"] == 4
    assert region["items"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert parameters["properties"]["source_hash"]["type"] == ["string", "null"]


@pytest.mark.asyncio
async def test_null_and_omitted_selectors_stay_semantic(kb, rag_calls):
    for extra in (
        {"region": []},
        {"region": None, "page": None, "source_path": None},
        {},
    ):
        result = await RAGTool().execute(query="pump seal", kb_name=kb.name, **extra)
        assert result.success, extra
        assert result.content == "semantic answer"
    assert len(rag_calls["rag_search"]) == 3
    assert rag_calls["resolve_for_rag"] == []


@pytest.mark.asyncio
async def test_page_with_legacy_empty_crop_returns_full_page(kb, rag_calls):
    result = await RAGTool().execute(
        query="Inspect this source",
        kb_name=kb.name,
        source_path="manual.pdf",
        page=1,
        region=[],
        _vision_supported=True,
    )
    assert result.success
    assert result.model_message["content"][1]["type"] == "image_url"
    assert "pump seal" in result.content
    assert "region=" not in result.sources[0]["visual_asset_url"]
    assert rag_calls["rag_search"] == []


@pytest.mark.asyncio
async def test_valid_crop_returns_intended_region_with_provenance(kb, rag_calls):
    result = await RAGTool().execute(
        query="Inspect this source",
        kb_name=kb.name,
        source_path="manual.pdf",
        page=1,
        region=[0, 0, 0.6, 0.3],
        _vision_supported=True,
    )
    assert result.success
    assert "region=0%2C0%2C0.6%2C0.3" in result.sources[0]["visual_asset_url"]
    assert result.sources[0]["source_document_id"]
    assert rag_calls["rag_search"] == []


@pytest.mark.parametrize(
    ("extra", "fragment"),
    [
        ({"page": 0, "region": []}, "one-based"),
        ({"page": -2}, "one-based"),
        ({"page": 1.5, "source_path": "manual.pdf"}, "integer"),
        ({"page": "1", "source_path": "manual.pdf"}, "integer"),
        ({"source_path": "manual.pdf", "page": 1, "region": [0, 1]}, "four finite numbers"),
        ({"source_path": "manual.pdf", "page": 1, "region": [0, 0, 2, 1]}, "0..1"),
        ({"source_path": "manual.pdf", "page": 1, "region": [0, 0, 0.5]}, "four finite numbers"),
        ({"source_path": "manual.pdf", "page": 1, "region": "0,0,1,1"}, "four finite numbers"),
    ],
)
@pytest.mark.asyncio
async def test_malformed_selectors_fail_visibly_without_substitution(
    kb, rag_calls, extra, fragment
):
    result = await RAGTool().execute(query="Inspect this source", kb_name=kb.name, **extra)
    assert not result.success
    assert fragment in result.content
    assert result.sources == []
    assert result.metadata["error_type"] == "invalid_selector"
    assert rag_calls["rag_search"] == []
    assert rag_calls["resolve_for_rag"] == []


@pytest.mark.asyncio
async def test_source_only_text_query_runs_document_scoped_text_search(kb, rag_calls, monkeypatch):
    (kb / "raw" / "notes.txt").write_text("Keep this source private.", encoding="utf-8")

    async def scoped_rag_search(**kwargs):
        rag_calls["rag_search"].append(kwargs)
        return {
            "answer": "scoped answer",
            "sources": [{"file_name": "notes.txt", "source": "notes.txt"}],
        }

    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", scoped_rag_search)
    result = await RAGTool().execute(
        query="What does this document say?",
        kb_name=kb.name,
        source_path="notes.txt",
    )
    assert result.success
    assert result.content == "scoped answer"
    assert result.metadata["source_scope"] == "notes.txt"
    assert result.sources == [
        {"type": "rag", "kb_name": kb.name, "file_name": "notes.txt", "source": "notes.txt"}
    ]
    assert result.model_message is None
    assert len(rag_calls["rag_search"]) == 1
    assert rag_calls["rag_search"][0]["document_keys"] == ["notes.txt"]
    assert rag_calls["resolve_for_rag"] == [kb.name]


@pytest.mark.asyncio
async def test_scoped_text_search_withholds_foreign_sources(kb, rag_calls, monkeypatch):
    (kb / "raw" / "notes.txt").write_text("Keep this source private.", encoding="utf-8")

    async def leaky_rag_search(**kwargs):
        return {
            "answer": "mixed answer",
            "provider": "mock",
            "sources": [
                {"file_name": "notes.txt", "source": "notes.txt"},
                {"file_name": "manual.pdf", "source": "manual.pdf"},
            ],
        }

    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", leaky_rag_search)
    result = await RAGTool().execute(
        query="What does this document say?",
        kb_name=kb.name,
        source_path="notes.txt",
    )
    assert not result.success
    assert result.metadata["error_type"] == "source_scope_unsupported"
    assert result.metadata["source_scope"] == "notes.txt"
    assert result.sources == []
    assert "withheld" in result.content
    assert rag_calls["rag_search"] == []


@pytest.mark.asyncio
async def test_scoped_text_search_reports_no_match_without_whole_kb_fallback(kb, rag_calls):
    (kb / "raw" / "notes.txt").write_text("Keep this source private.", encoding="utf-8")
    result = await RAGTool().execute(
        query="What does this document say?",
        kb_name=kb.name,
        source_path="notes.txt",
    )
    assert not result.success
    assert result.metadata["error_type"] == "source_scope_no_match"
    assert result.metadata["source_scope"] == "notes.txt"
    assert result.sources == []
    assert "no other document was searched" in result.content
    assert len(rag_calls["rag_search"]) == 1
    assert rag_calls["rag_search"][0]["document_keys"] == ["notes.txt"]


@pytest.mark.asyncio
async def test_scoped_text_search_rejects_unavailable_source(kb, rag_calls):
    result = await RAGTool().execute(
        query="What does this document say?",
        kb_name=kb.name,
        source_path="gone.txt",
    )
    assert not result.success
    assert result.metadata["error_type"] == "source_unavailable"
    assert result.sources == []
    assert rag_calls["rag_search"] == []


@pytest.mark.asyncio
async def test_scoped_text_search_verifies_source_hash(kb, rag_calls, monkeypatch):
    import hashlib

    notes = kb / "raw" / "notes.txt"
    notes.write_text("Keep this source private.", encoding="utf-8")
    digest = hashlib.sha256(notes.read_bytes()).hexdigest()

    async def scoped_rag_search(**kwargs):
        rag_calls["rag_search"].append(kwargs)
        return {"answer": "scoped answer", "sources": [{"source": "notes.txt"}]}

    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", scoped_rag_search)
    current = await RAGTool().execute(
        query="What does this document say?",
        kb_name=kb.name,
        source_path="notes.txt",
        source_hash=digest,
    )
    assert current.success
    assert current.content == "scoped answer"

    stale = await RAGTool().execute(
        query="What does this document say?",
        kb_name=kb.name,
        source_path="notes.txt",
        source_hash="b" * 64,
    )
    assert not stale.success
    assert stale.metadata["error_type"] == "source_changed"
    assert stale.sources == []
    assert len(rag_calls["rag_search"]) == 1


@pytest.mark.asyncio
async def test_source_only_scope_keeps_knowledge_base_access_check(kb, rag_calls, monkeypatch):
    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_for_rag", lambda _name: None)
    result = await RAGTool().execute(
        query="What does this document say?",
        kb_name=kb.name,
        source_path="notes.txt",
    )
    assert not result.success
    assert "not accessible" in result.content
    assert result.sources == []
    assert rag_calls["rag_search"] == []


@pytest.mark.parametrize("query", ["Inspect page 1", "检查第1页", "Inspect p. 1"])
@pytest.mark.asyncio
async def test_source_with_query_page_keeps_visual_inspection(kb, rag_calls, query):
    result = await RAGTool().execute(
        query=query,
        kb_name=kb.name,
        source_path="manual.pdf",
        _vision_supported=True,
    )
    assert result.success
    assert result.metadata["evidence_kind"] == "exact_source_visual"
    assert result.model_message["content"][1]["type"] == "image_url"
    assert "pump seal" in result.content
    assert rag_calls["rag_search"] == []

    unscoped = await RAGTool().execute(query=query, kb_name=kb.name)
    assert unscoped.success
    assert unscoped.content == "semantic answer"
    assert len(rag_calls["rag_search"]) == 1
