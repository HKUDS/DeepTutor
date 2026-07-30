"""Generated-file attachments carried by a turn's stream events.

The ``exec`` / ``code_execution`` / media tools write files into the turn
workspace and publish them in two places: each ``tool_result`` event carries
them in ``metadata.tool_metadata.artifacts`` the moment the tool finishes (the
source that survives cancelled turns), and the loop's final SOURCES event
aggregates them as ``type=="artifact"`` sources. Both are read — the caller
dedupes by URL.

Persisting them as assistant-message attachments is what lets the chat UI
render openable cards (same Viewer path as user uploads) and list them in the
session activity panel, instead of relying on the model pasting a raw
``/api/outputs`` URL into its answer.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

# Artifact URLs are minted as ``"/api/outputs/" + quote(relative_path)`` by
# ``services.sandbox.artifacts``. The URL is therefore the record's single
# source of truth for locating the file again — no redundant path field has to
# be persisted (or leaked to the client).
_OUTPUTS_URL_PREFIX = "/api/outputs/"

# Extensions whose preview drawer has no in-browser renderer and therefore
# falls back to the extractor's plain text (mirrors the frontend's
# ``OFFICE_BINARY_EXTS`` in ``web/components/chat/preview/previewerFor.ts``).
# Uploads get their ``extracted_text`` from the upload path; generated files
# never went through it, so a produced .pptx would otherwise open to an empty
# preview. Formats the browser *can* render (.docx via docx-preview, .xlsx via
# exceljs, PDF, images, text) are deliberately excluded — extracting them would
# only cost IO and database size. Legacy binaries the extractor cannot parse
# (.ppt/.doc/.xls) stay in the set: it is cheaper to let the extractor reject
# them than to duplicate its format list here.
_PREVIEW_TEXT_EXTENSIONS = frozenset({".pptx", ".ppt", ".doc", ".xls"})

# Preview text is read by a human in the drawer, not fed to the model, so it
# needs far less headroom than an uploaded document's index-facing extraction.
# It is persisted inside the assistant message's ``attachments`` JSON — keeping
# it tight keeps chat history small.
_PREVIEW_TEXT_MAX_CHARS = 20_000


def artifact_attachments(event: StreamEvent) -> list[dict[str, Any]]:
    """Return the attachment records for the artifacts *event* carries."""
    metadata = event.metadata or {}
    raw: list[Any] = []
    if event.type == StreamEventType.SOURCES:
        raw = [
            entry
            for entry in metadata.get("sources") or []
            if isinstance(entry, dict) and entry.get("type") == "artifact"
        ]
    elif event.type == StreamEventType.TOOL_RESULT:
        tool_meta = metadata.get("tool_metadata")
        if isinstance(tool_meta, dict):
            raw = [e for e in tool_meta.get("artifacts") or [] if isinstance(e, dict)]
    attachments: list[dict[str, Any]] = []
    for entry in raw:
        url = str(entry.get("url") or "")
        if not url:
            continue
        mime = str(entry.get("mime_type") or "")
        attachments.append(
            {
                "type": "image" if mime.startswith("image/") else "document",
                "filename": str(entry.get("filename") or "file"),
                "mime_type": mime,
                "url": url,
                "size_bytes": entry.get("size_bytes"),
                "generated": True,
            }
        )
    return attachments


async def fill_preview_text(attachments: list[dict[str, Any]]) -> None:
    """Populate ``extracted_text`` on artifacts the browser cannot render.

    Mutates *attachments* in place. Reading and parsing files is blocking work,
    so it runs off the event loop; ``to_thread`` copies contextvars, so the
    per-user path scope resolves the same as on the loop.
    """
    if not any(_needs_preview_text(att) for att in attachments):
        return
    await asyncio.to_thread(_fill_preview_text_sync, attachments)


def _needs_preview_text(attachment: dict[str, Any]) -> bool:
    filename = str(attachment.get("filename") or "")
    return Path(filename).suffix.lower() in _PREVIEW_TEXT_EXTENSIONS


def _fill_preview_text_sync(attachments: list[dict[str, Any]]) -> None:
    from deeptutor.utils.document_extractor import (
        DocumentExtractionError,
        extract_text_from_path,
    )

    for attachment in attachments:
        if not _needs_preview_text(attachment):
            continue
        path = _resolve_artifact_path(str(attachment.get("url") or ""))
        if path is None:
            continue
        try:
            text = extract_text_from_path(path, max_chars=_PREVIEW_TEXT_MAX_CHARS)
        except DocumentExtractionError as exc:
            # Unsupported legacy binary, empty deck, oversized file: the card
            # still opens and offers a download, it just has no inline text.
            logger.debug("No preview text for artifact %s: %s", path, exc)
            continue
        except OSError as exc:
            logger.debug("Could not read artifact %s for preview: %s", path, exc)
            continue
        if text.strip():
            attachment["extracted_text"] = text


def _resolve_artifact_path(url: str) -> Path | None:
    """Map an artifact's ``/api/outputs`` URL back to its file on disk.

    Returns ``None`` unless the result is a real file the outputs endpoint
    would itself serve — the same guard ``/api/outputs`` applies, so a crafted
    URL cannot walk this out of the public workspace.
    """
    if not url.startswith(_OUTPUTS_URL_PREFIX):
        return None
    service = get_path_service()
    candidate = service.get_public_outputs_root() / unquote(url[len(_OUTPUTS_URL_PREFIX) :])
    if not service.is_public_output_path(candidate):
        return None
    return candidate.resolve()


__all__ = ["artifact_attachments", "fill_preview_text"]
