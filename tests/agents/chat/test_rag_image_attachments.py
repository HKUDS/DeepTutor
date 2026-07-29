"""Tests for attaching retrieved PDF page images to chat Vision requests."""

from __future__ import annotations

from pathlib import Path

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext


def test_retrieved_page_images_become_deduplicated_multimodal_attachments(
    tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "page-3-figure.png"
    image_path.write_bytes(b"\x89PNG\r\nfigure")
    monkeypatch.setattr(
        "deeptutor.runtime.home.get_runtime_data_root",
        lambda: tmp_path,
    )

    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.binding = "openai"
    pipeline.model = "gpt-4o"
    context = UnifiedContext(
        session_id="s1",
        user_message="讲解第 3 页的几何题",
        metadata={},
    )
    source = {"title": "workbook.pdf", "page": "3", "image_paths": [str(image_path)]}

    added = pipeline._attach_rag_images(context, [source])
    assert len(added) == 1
    assert len(context.attachments) == 1
    assert context.attachments[0].type == "image"
    assert context.attachments[0].filename == image_path.name

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "讲解第 3 页的几何题"},
    ]
    prepared = pipeline._prepare_messages_with_attachments(messages, context)
    user_content = prepared[-1]["content"]
    assert any(part.get("type") == "image_url" for part in user_content)
    assert "data:image/png;base64," in user_content[-1]["image_url"]["url"]

    # A second retrieval of the same page must not add a duplicate image.
    assert pipeline._attach_rag_images(context, [source]) == []
    assert len(context.attachments) == 1


def test_retrieved_page_images_cannot_escape_runtime_data_root(tmp_path: Path, monkeypatch) -> None:
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"not allowed")
    monkeypatch.setattr(
        "deeptutor.runtime.home.get_runtime_data_root",
        lambda: tmp_path,
    )

    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    context = UnifiedContext(session_id="s1", user_message="q", metadata={})

    assert pipeline._attach_rag_images(
        context,
        [{"image_paths": [str(outside)]}],
    ) == []
    assert context.attachments == []
