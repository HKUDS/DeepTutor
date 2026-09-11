"""Tests for generated-artifact attachment records."""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.artifact_attachments import (
    _resolve_artifact_path,
    artifact_attachments,
    fill_preview_text,
)

# ---------------------------------------------------------------------------
# artifact_attachments
# ---------------------------------------------------------------------------


class TestArtifactAttachments:
    def _sources_event(self, sources: list[dict]) -> StreamEvent:
        return StreamEvent(type=StreamEventType.SOURCES, metadata={"sources": sources})

    def test_artifact_source_becomes_generated_attachment(self) -> None:
        event = self._sources_event(
            [
                {
                    "type": "artifact",
                    "filename": "report.pdf",
                    "url": "/files/outputs/workspace/chat/chat/t1/exec/report.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 2048,
                }
            ]
        )
        atts = artifact_attachments(event)
        assert len(atts) == 1
        a = atts[0]
        assert a["type"] == "document"
        assert a["filename"] == "report.pdf"
        assert a["url"].endswith("report.pdf")
        assert a["mime_type"] == "application/pdf"
        assert a["generated"] is True

    def test_image_artifact_typed_as_image(self) -> None:
        event = self._sources_event(
            [
                {
                    "type": "artifact",
                    "filename": "chart.png",
                    "url": "/files/outputs/x/chart.png",
                    "mime_type": "image/png",
                }
            ]
        )
        assert artifact_attachments(event)[0]["type"] == "image"

    def test_non_artifact_sources_ignored(self) -> None:
        event = self._sources_event([{"type": "rag", "query": "q", "kb_name": "kb"}])
        assert artifact_attachments(event) == []

    def test_tool_result_artifacts_extracted(self) -> None:
        # tool_result events carry artifacts the moment exec finishes — the
        # durable source for cancelled turns (the aggregate SOURCES event
        # only fires when the loop completes).
        event = StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            content="Exit code: 0",
            metadata={
                "tool_metadata": {
                    "exit_code": 0,
                    "artifacts": [
                        {
                            "filename": "notes.pdf",
                            "url": "/files/outputs/workspace/chat/chat/t2/exec/notes.pdf",
                            "mime_type": "application/pdf",
                            "size_bytes": 1024,
                        }
                    ],
                }
            },
        )
        atts = artifact_attachments(event)
        assert len(atts) == 1
        assert atts[0]["filename"] == "notes.pdf"
        assert atts[0]["generated"] is True

    def test_tool_result_without_artifacts_ignored(self) -> None:
        event = StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            content="rag result",
            metadata={"tool_metadata": {"kb_name": "kb"}},
        )
        assert artifact_attachments(event) == []

    def test_presented_user_file_keeps_workspace_identity(self) -> None:
        event = self._sources_event(
            [
                {
                    "type": "workspace_item",
                    "workspace_id": "ws_one",
                    "workspace_item_id": "wsi_one",
                    "relative_path": "lesson/notes.md",
                    "filename": "notes.md",
                    "url": "/files/workspace-items/ws_one/wsi_one",
                    "mime_type": "text/markdown",
                    "generated": False,
                }
            ]
        )

        attachment = artifact_attachments(event)[0]

        assert attachment["origin"] == "workspace"
        assert attachment["relative_path"] == "lesson/notes.md"
        assert attachment["generated"] is False

    def test_non_sources_event_ignored(self) -> None:
        event = StreamEvent(type=StreamEventType.CONTENT, content="hello")
        assert artifact_attachments(event) == []

    def test_artifact_without_url_skipped(self) -> None:
        event = self._sources_event([{"type": "artifact", "filename": "x.pdf"}])
        assert artifact_attachments(event) == []

    def test_no_absolute_path_is_persisted(self) -> None:
        # The producer rows carry an absolute ``path``; it must not ride along
        # into the attachment record, which reaches the browser verbatim.
        event = self._sources_event(
            [
                {
                    "type": "artifact",
                    "filename": "deck.pptx",
                    "url": "/files/outputs/x/deck.pptx",
                    "path": "/home/someone/data/users/u1/workspace/x/deck.pptx",
                    "mime_type": "application/vnd.openxmlformats-officedocument"
                    ".presentationml.presentation",
                }
            ]
        )
        assert "path" not in artifact_attachments(event)[0]


# ---------------------------------------------------------------------------
# _resolve_artifact_path
# ---------------------------------------------------------------------------


class TestResolveArtifactPath:
    def test_non_outputs_url_rejected(self) -> None:
        assert _resolve_artifact_path("/files/attachments/abc/deck.pptx") is None

    def test_empty_url_rejected(self) -> None:
        assert _resolve_artifact_path("") is None

    def test_traversal_outside_public_root_rejected(self) -> None:
        assert _resolve_artifact_path("/files/outputs/../../../etc/passwd") is None

    def test_missing_file_rejected(self) -> None:
        # is_public_output_path also requires the target to exist as a file.
        assert _resolve_artifact_path("/files/outputs/workspace/chat/chat/t/exec/gone.pptx") is None


# ---------------------------------------------------------------------------
# fill_preview_text
# ---------------------------------------------------------------------------


def _write_minimal_pptx(path: Path, text: str) -> None:
    """A one-slide .pptx the OOXML extractor can read."""
    slide = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p>"
        "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        zf.writestr("ppt/slides/slide1.xml", slide)


class TestFillPreviewText:
    @pytest.mark.asyncio
    async def test_pptx_gets_preview_text(self, tmp_path, monkeypatch) -> None:
        from deeptutor.services.session import artifact_attachments as module

        # Workspace snapshots are physically stored by hash without an
        # extension; format routing must use the attachment's logical name.
        blob = tmp_path / "4f73c2a1"
        _write_minimal_pptx(blob, "Chapter one")
        monkeypatch.setattr(module, "_resolve_artifact_path", lambda url: blob)

        attachments = [{"filename": "deck.pptx", "url": "/files/outputs/x/deck.pptx"}]
        await fill_preview_text(attachments)

        assert "Chapter one" in attachments[0]["extracted_text"]

    @pytest.mark.asyncio
    async def test_browser_renderable_formats_skipped(self, tmp_path, monkeypatch) -> None:
        # .docx/.xlsx/.pdf render client-side; extracting them would only cost
        # IO and database size.
        from deeptutor.services.session import artifact_attachments as module

        calls: list[str] = []
        monkeypatch.setattr(module, "_resolve_artifact_path", lambda url: calls.append(url) or None)

        attachments = [
            {"filename": "report.docx", "url": "/files/outputs/x/report.docx"},
            {"filename": "sheet.xlsx", "url": "/files/outputs/x/sheet.xlsx"},
            {"filename": "paper.pdf", "url": "/files/outputs/x/paper.pdf"},
            {"filename": "chart.png", "url": "/files/outputs/x/chart.png"},
        ]
        await fill_preview_text(attachments)

        assert calls == []
        assert all("extracted_text" not in att for att in attachments)

    @pytest.mark.asyncio
    async def test_unreadable_artifact_leaves_record_intact(self, tmp_path, monkeypatch) -> None:
        from deeptutor.services.session import artifact_attachments as module

        missing = tmp_path / "gone.pptx"
        monkeypatch.setattr(module, "_resolve_artifact_path", lambda url: missing)

        attachments = [{"filename": "gone.pptx", "url": "/files/outputs/x/gone.pptx"}]
        await fill_preview_text(attachments)

        assert "extracted_text" not in attachments[0]

    @pytest.mark.asyncio
    async def test_empty_list_is_a_noop(self) -> None:
        await fill_preview_text([])
