"""Source visual provenance, KB scope, and model pixel delivery."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
import zipfile

from PIL import Image
import pytest

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.visual_assets import (
    VisualAssetStore,
    collect_visual_assets,
)


def _fixture(tmp_path: Path, *, suffix: str = ".pdf", engine: str = "mineru"):
    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    source = raw / f"lesson{suffix}"
    source.write_bytes(b"source document with a figure")
    assets = tmp_path / "parse-cache" / "images"
    assets.mkdir(parents=True)
    image = assets / "figure.png"
    Image.new("RGB", (3, 2), color=(17, 99, 211)).save(image)
    parsed = ParsedDocument(
        markdown="The learning curve is shown below.\n\n![Learning curve](images/figure.png)",
        blocks=(
            [
                {
                    "type": "image",
                    "img_path": str(image),
                    "page_idx": 2,
                    "bbox": [10, 20, 100, 200],
                    "image_caption": ["Learning curve"],
                }
            ]
            if engine == "mineru"
            else None
        ),
        asset_dir=assets,
        source_hash="source-hash",
        parser_signature=f"{engine}-signature",
        engine=engine,
    )
    return kb_dir, source, image, parsed


@pytest.mark.parametrize(
    ("suffix", "engine"),
    [(".pdf", "mineru"), (".epub", "pymupdf4llm")],
)
def test_verified_source_visual_contract_and_lifecycle(tmp_path: Path, suffix: str, engine: str):
    kb_dir, source, image, parsed = _fixture(tmp_path, suffix=suffix, engine=engine)
    candidates = collect_visual_assets(parsed, source, kb_dir)
    assert len(candidates) == 1
    record = candidates[0].record
    assert record["asset_id"] == collect_visual_assets(parsed, source, kb_dir)[0].record["asset_id"]
    assert record["source_path"] == source.name
    assert record["source_document_id"]
    assert record["parser_engine"] == engine
    assert record["caption"] == "Learning curve"
    if engine == "mineru":
        assert record["page_index"] == 2
        assert record["page_number"] == 3
        assert record["bbox"] == [10, 20, 100, 200]
        assert record["source_locator"] == "blocks.json#/0"
    else:
        assert record["page_index"] is None
        assert record["source_locator"].startswith("markdown:")

    store = VisualAssetStore(kb_dir)
    store.publish(candidates, replace=True)
    assert store.read(record["asset_id"]) == (record, image.read_bytes())
    assert store.read("../manifest.json") is None
    persisted = store.root / (record["asset_id"] + ".png")
    persisted.write_bytes(b"\x89PNG\r\n\x1a\ncorrupted")
    assert store.read(record["asset_id"]) is None
    store.publish(candidates, replace=True)
    newer = ParsedDocument(
        markdown=parsed.markdown,
        blocks=parsed.blocks,
        asset_dir=parsed.asset_dir,
        parser_signature="new-parser-signature",
        engine=parsed.engine,
    )
    newer_candidate = collect_visual_assets(newer, source, kb_dir)[0]
    store.publish([newer_candidate])
    assert store.read(record["asset_id"]) is not None  # older index version remains valid
    assert store.read(newer_candidate.record["asset_id"]) is not None
    moved = kb_dir / "raw" / "folder" / source.name
    moved.parent.mkdir()
    source.rename(moved)
    store.move_source(source.name, f"folder/{source.name}")
    assert store.records()[record["asset_id"]]["source_path"] == f"folder/{source.name}"
    store.remove_source(f"folder/{source.name}")
    assert store.read(record["asset_id"]) is None
    assert store.read(newer_candidate.record["asset_id"]) is None
    assert not persisted.exists()


def test_manifest_limit_does_not_replace_existing_assets(tmp_path: Path, monkeypatch):
    import deeptutor.services.rag.visual_assets as assets_module

    kb_dir, source, image, parsed = _fixture(tmp_path)
    original = collect_visual_assets(parsed, source, kb_dir)[0]
    store = VisualAssetStore(kb_dir)
    store.publish([original])
    manifest_before = store.manifest_path.read_bytes()
    monkeypatch.setattr(assets_module, "MAX_MANIFEST_BYTES", len(manifest_before) + 10)
    second = assets_module.VisualAssetCandidate(
        path=image,
        record={**original.record, "asset_id": "a" * 64},
    )
    with pytest.raises(OSError, match="manifest exceeds"):
        store.publish([second])
    assert store.manifest_path.read_bytes() == manifest_before
    assert store.read(original.record["asset_id"]) is not None
    assert store.read(second.record["asset_id"]) is None


def test_size_count_and_rebuild_cleanup(tmp_path: Path, monkeypatch):
    import deeptutor.services.rag.visual_assets as assets_module

    kb_dir, source, image, parsed = _fixture(tmp_path)
    store = VisualAssetStore(kb_dir)
    first = collect_visual_assets(parsed, source, kb_dir)[0]
    store.publish([first])
    source.unlink()
    store.publish([], prune_missing=True)
    assert store.read(first.record["asset_id"]) is None

    source.write_bytes(b"source document with a figure")
    monkeypatch.setattr(assets_module, "MAX_IMAGE_BYTES", 10)
    assert collect_visual_assets(parsed, source, kb_dir) == []
    monkeypatch.setattr(assets_module, "MAX_IMAGE_BYTES", 5 * 1024 * 1024)
    for index in range(2):
        Image.new("RGB", (3, 2), color=(index * 60, 0, 0)).save(image.parent / f"extra-{index}.png")
    monkeypatch.setattr(assets_module, "MAX_ASSETS_PER_DOCUMENT", 2)
    assert len(collect_visual_assets(parsed, source, kb_dir)) == 2


@pytest.mark.parametrize("suffix", [".pdf", ".epub"])
def test_real_pymupdf_parser_extracts_pdf_and_epub_pixels(tmp_path: Path, suffix: str):
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("pymupdf4llm")
    from deeptutor.services.parsing.cache import load_ir
    from deeptutor.services.parsing.engines.pymupdf4llm.config import PyMuPDF4LLMConfig
    from deeptutor.services.parsing.engines.pymupdf4llm.engine import PyMuPDF4LLMParser

    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    source = raw / f"lesson{suffix}"
    image = tmp_path / "figure.png"
    Image.new("RGB", (100, 80), color="blue").save(image)
    if suffix == ".pdf":
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((50, 50), "Learning curve")
        page.insert_image(fitz.Rect(50, 80, 250, 240), filename=str(image))
        pdf.save(source)
        pdf.close()
    else:
        with zipfile.ZipFile(source, "w") as epub:
            epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            epub.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            )
            epub.writestr(
                "OEBPS/content.opf",
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Lesson</dc:title><dc:language>en</dc:language><dc:identifier id="id">lesson</dc:identifier></metadata><manifest><item id="page" href="page.xhtml" media-type="application/xhtml+xml"/><item id="fig" href="figure.png" media-type="image/png"/></manifest><spine><itemref idref="page"/></spine></package>',
            )
            epub.writestr(
                "OEBPS/page.xhtml",
                '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Lesson</title></head><body><p>Learning curve</p><img src="figure.png" alt="Learning curve"/></body></html>',
            )
            epub.write(image, "OEBPS/figure.png")

    workdir = tmp_path / "parse"
    workdir.mkdir()
    PyMuPDF4LLMParser().parse(source, workdir, config=PyMuPDF4LLMConfig())
    markdown, blocks, asset_dir = load_ir(workdir)
    parsed = ParsedDocument(
        markdown=markdown,
        blocks=blocks,
        asset_dir=asset_dir,
        parser_signature="pymupdf-test",
        engine="pymupdf4llm",
    )
    candidates = collect_visual_assets(parsed, source, kb_dir)
    assert len(candidates) == 1
    assert candidates[0].record["mime_type"] == "image/png"
    assert candidates[0].record["source_locator"].startswith("markdown:")
    assert candidates[0].record["context"].startswith("Learning curve")


def test_visual_document_is_searchable_with_text_embeddings(tmp_path: Path, monkeypatch):
    pytest.importorskip("llama_index.core")
    import deeptutor.services.parsing as parsing
    from deeptutor.services.rag.pipelines.llamaindex.document_loader import LlamaIndexDocumentLoader

    kb_dir, source, _image, parsed = _fixture(tmp_path, suffix=".epub", engine="pymupdf4llm")

    class Parser:
        def parse(self, _source, **_kwargs):
            return parsed

    monkeypatch.setattr(parsing, "get_parse_service", lambda: Parser())
    candidates = []
    documents = asyncio.run(
        LlamaIndexDocumentLoader().load([str(source)], kb_dir=kb_dir, visual_candidates=candidates)
    )
    visual = [doc for doc in documents if doc.metadata.get("content_type") == "source_visual"]
    assert len(visual) == 1
    assert len(candidates) == 1
    assert visual[0].metadata["visual_asset_id"] == candidates[0].record["asset_id"]
    assert "Learning curve" in visual[0].text
    assert "The learning curve" in visual[0].text
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    retrieved = SimpleNamespace(
        node=SimpleNamespace(
            text=visual[0].text,
            metadata=visual[0].metadata,
            node_id="visual-node",
        ),
        score=0.9,
    )
    result = LlamaIndexPipeline._nodes_to_result(None, "learning curve", [retrieved])
    assert result["sources"][0]["visual_asset_id"] == candidates[0].record["asset_id"]
    assert result["sources"][0]["chunk_id"] == "visual-node"


def test_visual_preview_enforces_kb_scope_and_verified_bytes(tmp_path: Path, monkeypatch):
    import importlib

    from fastapi import HTTPException

    import deeptutor.services.config as config_module

    monkeypatch.setattr(config_module, "load_config_with_main", lambda *_args: {})
    knowledge = importlib.import_module("deeptutor.api.routers.knowledge")

    kb_dir, source, image, parsed = _fixture(tmp_path)
    candidate = collect_visual_assets(parsed, source, kb_dir)[0]
    VisualAssetStore(kb_dir).publish([candidate])
    monkeypatch.setattr(knowledge, "_resolve_kb_raw_dir", lambda _kb_name: kb_dir / "raw")
    response = asyncio.run(knowledge.serve_kb_visual_asset("kb", candidate.record["asset_id"]))
    assert response.body == image.read_bytes()
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    def denied(_kb_name):
        raise HTTPException(status_code=403, detail="Knowledge base is not assigned to you")

    monkeypatch.setattr(knowledge, "_resolve_kb_raw_dir", denied)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(knowledge.serve_kb_visual_asset("kb", candidate.record["asset_id"]))
    assert exc.value.status_code == 403


def test_rag_tool_sends_exact_retrieved_pixels_to_vision_model(tmp_path: Path, monkeypatch):
    from deeptutor.multi_user import knowledge_access
    from deeptutor.services.workspace import context as workspace_context
    from deeptutor.tools import rag_tool
    from deeptutor.tools.builtin import RAGTool

    kb_dir, source, image, parsed = _fixture(tmp_path)
    record = collect_visual_assets(parsed, source, kb_dir)[0]
    VisualAssetStore(kb_dir).publish([record], replace=True)
    monkeypatch.setattr(
        knowledge_access,
        "resolve_for_rag",
        lambda kb_name: SimpleNamespace(name="kb", base_dir=tmp_path) if kb_name == "kb" else None,
    )
    monkeypatch.setattr(workspace_context, "current_workspace_id", lambda: "study")

    async def search(**_kwargs):
        return {
            "answer": "A learning curve is cited.",
            "sources": [
                {
                    "title": "lesson.pdf",
                    "visual_asset_id": record.record["asset_id"],
                    "caption": "Learning curve",
                    "source": "/etc/passwd",
                }
            ],
        }

    monkeypatch.setattr(rag_tool, "rag_search", search)
    result = asyncio.run(
        RAGTool().execute(query="learning curve", kb_name="kb", _vision_supported=True)
    )
    assert result.model_message is not None
    parts = result.model_message["content"]
    assert parts[0]["type"] == "text"
    assert record.record["asset_id"] in parts[0]["text"]
    assert "Learning curve" not in parts[0]["text"]
    assert parts[1]["type"] == "image_url"
    data_uri = parts[1]["image_url"]["url"]
    assert data_uri.startswith("data:image/png;base64,")
    assert base64.b64decode(data_uri.split(",", 1)[1]) == image.read_bytes()
    assert result.sources[0]["visual_asset_url"].endswith(
        f"{record.record['asset_id']}?dt_workspace=study"
    )
    assert "base64" not in str(result.metadata)

    text_only = asyncio.run(
        RAGTool().execute(query="learning curve", kb_name="kb", _vision_supported=False)
    )
    assert text_only.model_message is None
    assert "cannot inspect source image pixels" in text_only.content

    monkeypatch.setattr(knowledge_access, "resolve_for_rag", lambda _kb_name: None)
    inaccessible = asyncio.run(
        RAGTool().execute(query="learning curve", kb_name="kb", _vision_supported=True)
    )
    assert inaccessible.model_message is None

    monkeypatch.setattr(
        knowledge_access,
        "resolve_for_rag",
        lambda _kb_name: SimpleNamespace(name="different-kb", base_dir=tmp_path),
    )
    cross_kb = asyncio.run(
        RAGTool().execute(query="learning curve", kb_name="kb", _vision_supported=True)
    )
    assert cross_kb.model_message is None


def test_rag_model_payload_is_bounded_to_two_images(tmp_path: Path, monkeypatch):
    from deeptutor.multi_user import knowledge_access
    from deeptutor.tools import rag_tool
    from deeptutor.tools.builtin import RAGTool

    kb_dir, source, image, parsed = _fixture(tmp_path)
    for index in range(2):
        Image.new("RGB", (3, 2), color=(0, index * 60, 10)).save(
            image.parent / f"extra-{index}.png"
        )
    candidates = collect_visual_assets(parsed, source, kb_dir)
    assert len(candidates) == 3
    VisualAssetStore(kb_dir).publish(candidates)
    monkeypatch.setattr(
        knowledge_access,
        "resolve_for_rag",
        lambda _kb_name: SimpleNamespace(name="kb", base_dir=tmp_path),
    )

    async def search(**_kwargs):
        return {
            "answer": "Three figures found.",
            "sources": [{"visual_asset_id": item.record["asset_id"]} for item in candidates],
        }

    monkeypatch.setattr(rag_tool, "rag_search", search)
    result = asyncio.run(RAGTool().execute(query="figures", kb_name="kb", _vision_supported=True))
    assert sum(part["type"] == "image_url" for part in result.model_message["content"]) == 2


def test_visual_message_reaches_next_model_request_without_stream_leak(tmp_path: Path, monkeypatch):
    from deeptutor.runtime.agentic import loop as agent_loop
    from deeptutor.runtime.agentic.labeled_step import LabeledStepResult
    from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome, _collect_outcome

    kb_dir, source, image, parsed = _fixture(tmp_path)
    candidate = collect_visual_assets(parsed, source, kb_dir)[0]
    VisualAssetStore(kb_dir).publish([candidate], replace=True)
    record, pixels = VisualAssetStore(kb_dir).read(candidate.record["asset_id"])
    private_message = {
        "role": "user",
        "content": [
            {"type": "text", "text": f"Inspect {record['asset_id']}"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + base64.b64encode(pixels).decode()},
            },
        ],
    }

    class Stream:
        def __init__(self):
            self.events = []

        async def tool_result(self, **kwargs):
            self.events.append(kwargs)

    stream = Stream()
    outcome = asyncio.run(
        _collect_outcome(
            prepared=[("tool-1", "rag", {})],
            results=[
                {
                    "result_text": "Source visual found",
                    "sources": [],
                    "metadata": {},
                    "model_message": private_message,
                }
            ],
            per_tool_trace_meta=[{}],
            stream=stream,
            source="chat",
            stage="exploring",
        )
    )
    assert outcome.model_messages == [{**private_message, "_after_tool_call_id": "tool-1"}]
    assert "base64" not in str(stream.events)
    capped = asyncio.run(
        _collect_outcome(
            prepared=[(f"tool-{index}", "rag", {}) for index in range(3)],
            results=[
                {
                    "result_text": "Source visual found",
                    "sources": [],
                    "metadata": {},
                    "model_message": private_message,
                }
                for _ in range(3)
            ],
            per_tool_trace_meta=[{} for _ in range(3)],
            stream=stream,
            source="chat",
            stage="exploring",
        )
    )
    assert len(capped.model_messages) == 2

    captured = []

    async def fake_step(**kwargs):
        captured.append(list(kwargs["messages"]))
        if len(captured) == 1:
            return LabeledStepResult(
                label="CALL_TOOLS",
                text="",
                tool_calls=[{"id": "tool-1", "name": "rag", "arguments": "{}"}],
            )
        return LabeledStepResult(label="FINISH", text="Done")

    monkeypatch.setattr(agent_loop, "run_labeled_step", fake_step)

    class Host:
        async def guard_context_window(self, _messages):
            pass

        def build_iteration_trace_meta(self, _iteration):
            return {}, {}

        async def dispatch_tools(self, **_kwargs):
            return outcome

    protocol = agent_loop.LabelProtocol(
        allowed=("CALL_TOOLS", "FINISH"),
        terminal=frozenset({"FINISH"}),
        intermediate=frozenset(),
        final=frozenset(),
        tool_label="CALL_TOOLS",
    )
    loop_result = asyncio.run(
        agent_loop.run_agentic_loop(
            initial_messages=[{"role": "user", "content": "What does the figure show?"}],
            protocol=protocol,
            client=object(),
            model="gpt-4o",
            completion_kwargs={},
            binding="openai",
            tool_schemas=[],
            stream=stream,
            source="chat",
            stage="exploring",
            max_iterations=2,
            host=Host(),
        )
    )
    assert loop_result.completed
    assert "base64" not in str(loop_result.messages)
    assert all(message.get("role") != "user" for message in loop_result.messages[1:])
    next_request = captured[1]
    assert next_request[-2]["role"] == "tool"
    assert next_request[-1] == private_message
    assert (
        base64.b64decode(next_request[-1]["content"][1]["image_url"]["url"].split(",", 1)[1])
        == image.read_bytes()
    )
    from deeptutor.services.llm.provider_core.anthropic_provider import AnthropicProvider
    from deeptutor.services.llm.provider_core.openai_responses.converters import convert_messages

    _system, responses_input = convert_messages(next_request)
    response_image = responses_input[-1]["content"][1]
    assert response_image["type"] == "input_image"
    assert base64.b64decode(response_image["image_url"].split(",", 1)[1]) == image.read_bytes()
    anthropic_image = AnthropicProvider._convert_image_block(next_request[-1]["content"][1])
    assert anthropic_image["type"] == "image"
    assert base64.b64decode(anthropic_image["source"]["data"]) == image.read_bytes()
    _system, anthropic_messages = AnthropicProvider.__new__(AnthropicProvider)._convert_messages(
        next_request
    )
    assert anthropic_messages[-1]["role"] == "user"
    assert anthropic_messages[-1]["content"][0]["type"] == "tool_result"
    assert anthropic_messages[-1]["content"][-1]["type"] == "image"


def test_visual_messages_follow_complete_tool_reply_batch():
    from deeptutor.runtime.agentic.loop import _with_transient_model_messages

    messages = [
        {"role": "assistant", "tool_calls": [{"id": "rag"}, {"id": "other"}]},
        {"role": "tool", "tool_call_id": "rag", "content": "Figure found"},
        {"role": "tool", "tool_call_id": "other", "content": "Other result"},
    ]
    transient = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}],
            "_after_tool_call_id": "rag",
        }
    ]
    request = _with_transient_model_messages(messages, transient)
    assert [item["role"] for item in request] == ["assistant", "tool", "tool", "user"]
    assert request[-1]["content"] == transient[0]["content"]
    assert messages[-1]["role"] == "tool"  # canonical history was not changed


def test_visual_images_are_bounded_across_tool_rounds(monkeypatch):
    from deeptutor.agents.loop.pipeline import IMAGE_TOKEN_GUARD_RESERVE, AgenticLoopPipeline
    from deeptutor.runtime.agentic import loop as agent_loop
    from deeptutor.runtime.agentic.labeled_step import LabeledStepResult
    from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome

    requests = []
    guard_estimates = []

    async def fake_step(**kwargs):
        requests.append(kwargs["messages"])
        if len(requests) <= 2:
            tool_id = f"tool-{len(requests)}"
            return LabeledStepResult(
                label="CALL_TOOLS",
                text="",
                tool_calls=[{"id": tool_id, "name": "rag", "arguments": "{}"}],
            )
        return LabeledStepResult(label="FINISH", text="Done")

    monkeypatch.setattr(agent_loop, "run_labeled_step", fake_step)

    class Host:
        async def guard_context_window(self, messages):
            guard_estimates.append(AgenticLoopPipeline._estimate_messages_tokens(messages))

        def build_iteration_trace_meta(self, _iteration):
            return {}, {}

        async def dispatch_tools(self, *, iteration, **_kwargs):
            tool_id = f"tool-{iteration + 1}"
            return DispatchOutcome(
                tool_messages=[
                    {"role": "tool", "tool_call_id": tool_id, "content": "Figure found"}
                ],
                model_messages=[
                    {
                        "role": "user",
                        "_after_tool_call_id": tool_id,
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{iteration}{image}"},
                            }
                            for image in range(2)
                        ],
                    }
                ],
            )

    protocol = agent_loop.LabelProtocol(
        allowed=("CALL_TOOLS", "FINISH"),
        terminal=frozenset({"FINISH"}),
        intermediate=frozenset(),
        final=frozenset(),
        tool_label="CALL_TOOLS",
    )
    result = asyncio.run(
        agent_loop.run_agentic_loop(
            initial_messages=[{"role": "user", "content": "Explain the figures"}],
            protocol=protocol,
            client=object(),
            model="vision-model",
            completion_kwargs={},
            binding="openai",
            tool_schemas=[],
            stream=object(),
            source="chat",
            stage="exploring",
            max_iterations=3,
            host=Host(),
        )
    )
    assert result.completed
    images = [
        part["image_url"]["url"]
        for message in requests[2]
        for part in (message.get("content") or [])
        if isinstance(part, dict) and part.get("type") == "image_url"
    ]
    assert images == ["data:image/png;base64,10", "data:image/png;base64,11"]
    assert guard_estimates[2] >= 2 * IMAGE_TOKEN_GUARD_RESERVE
    assert "base64" not in str(result.messages)
