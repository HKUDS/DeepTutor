"""Recorded RAG argument failures, replayed without an LLM or network."""

import asyncio
import json
from types import SimpleNamespace

import pymupdf
import pytest

from deeptutor.tools.builtin import RAGTool


@pytest.fixture
def source_kb(tmp_path, monkeypatch):
    kb = tmp_path / "demo"
    (kb / "raw").mkdir(parents=True)
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "Original source page")
        doc.save(kb / "raw" / "manual.pdf")
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_for_rag",
        lambda _: SimpleNamespace(base_dir=kb.parent, name=kb.name),
    )
    return kb


def _arguments():
    return dict(
        query="Inspect this source",
        kb_name="demo",
        source_path="manual.pdf",
        asset_id="",
        figure="",
        page=1,
        region=None,
        source_hash="",
    )


def test_mastery_inspection_keeps_original_pixels_private(source_kb):
    result = asyncio.run(
        RAGTool().execute(**_arguments(), _vision_supported=True, _mastery_source_context=True)
    )
    assert "Original source page" in result.content
    assert result.model_message
    assert result.public_result == {"content": "Source evidence inspected privately."}
    assert "![Original source evidence]" not in result.content
    assert "/api/knowledge-bases/" not in result.content
    assert "manual.pdf" in result.content


def test_mastery_presentation_requires_server_authorization(source_kb):
    result = asyncio.run(
        RAGTool().execute(**_arguments(), presentation="teaching", _mastery_source_context=True)
    )
    assert not result.success
    assert not result.public_result.get("sources")


def test_mastery_explicit_presentation_uses_authorized_view_only(source_kb):
    async def present(sources, purpose):
        assert purpose == "teaching" and sources[0]["page"] == 1
        assert sources[0]["source_ref"]["page_index"] == 0
        assert "url" not in sources[0]
        return [{"title": "Diagram", "preview_url": sources[0]["preview_url"]}]

    result = asyncio.run(
        RAGTool().execute(
            **_arguments(),
            presentation="teaching",
            _mastery_source_context=True,
            _present_mastery_sources=present,
        )
    )
    assert result.success
    assert result.public_result["sources"][0]["presentation"] == "teaching"
    assert "Original source page" not in str(result.public_result)


@pytest.mark.asyncio
async def test_real_mastery_rag_dispatch_does_not_replay_private_passages(source_kb):
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext
    from deeptutor.runtime.agentic.tool_dispatch import dispatch_tool_calls
    from deeptutor.runtime.stream_bus import StreamBus

    class Registry:
        def get(self, name):
            return RAGTool()

        async def execute(self, name, **kwargs):
            return await RAGTool().execute(**kwargs)

    bus, records = StreamBus(), []

    async def consume():
        async for event in bus.subscribe():
            records.append(event.to_dict())

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)
    result = await dispatch_tool_calls(
        tool_calls=[{"id": "inspect", "name": "rag", "arguments": json.dumps(_arguments())}],
        context=UnifiedContext(
            session_id="synthetic",
            user_message="Quiz me",
            metadata={"mastery_mode": True, "mastery_path_id": "path"},
        ),
        stream=bus,
        source="mastery_path",
        stage="responding",
        iteration_index=0,
        registry=Registry(),
        kwarg_augmenter=lambda name, args, context: MasteryLoopCapability().augment_kwargs(
            name, {**args, "_vision_supported": True}, context
        ),
    )
    await bus.close()
    await consumer
    replay = json.loads(json.dumps(records))
    assert all(
        value not in json.dumps(replay)
        for value in (
            "Original source page",
            "source-page?",
            "manual.pdf",
            "base64",
        )
    )
    assert result.sources == []
    assert "Original source page" in result.tool_messages[0]["content"]
    assert result.model_messages


def test_mastery_semantic_result_metadata_and_progress_remain_private(monkeypatch):
    async def search(**kwargs):
        assert kwargs["event_sink"] is None
        assert "_mastery_source_context" not in kwargs
        assert "presentation" not in kwargs
        return {"answer": "SECRET_SOLUTION", "sources": [{"text": "SECRET_SOLUTION"}]}

    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", search)
    result = asyncio.run(
        RAGTool().execute(
            query="Question",
            kb_name="demo",
            _mastery_source_context=True,
            presentation="inspect",
            event_sink=object(),
        )
    )
    assert result.content == "SECRET_SOLUTION"
    assert "SECRET_SOLUTION" not in json.dumps(result.public_result)


def test_pending_presentation_denial_preserves_private_evidence(source_kb):
    from deeptutor.learning.service import MasteryInteractionError

    async def deny(sources, purpose):
        raise MasteryInteractionError("An unanswered question uses this page.")

    result = asyncio.run(
        RAGTool().execute(
            **_arguments(),
            presentation="teaching",
            _mastery_source_context=True,
            _present_mastery_sources=deny,
            _vision_supported=True,
        )
    )
    assert not result.success
    assert "Original source page" in result.content
    assert result.model_message
    assert not result.public_result.get("sources")
