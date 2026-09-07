"""Generated-file attachments carried by a turn's stream events.

The unified ``exec`` and media tools write files into the turn workspace and
report their logical paths. ``workspace_present`` then publishes an immutable
workspace item in its tool result and the loop's final SOURCES event. Legacy
non-workspace artifact events remain readable for older stored sessions.

Persisting them as assistant-message attachments is what lets the chat UI
render openable cards (same Viewer path as user uploads) and list them in the
session activity panel, instead of relying on the model pasting a raw
``/files/outputs`` URL into its answer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

# Artifact URLs are minted as ``"/files/outputs/" + quote(relative_path)`` by
# ``services.sandbox.artifacts``. The URL is therefore the record's single
# source of truth for locating the file again — no redundant path field has to
# be persisted (or leaked to the client).
_OUTPUTS_URL_PREFIX = "/files/outputs/"
_WORKSPACE_ITEMS_URL_PREFIX = "/files/workspace-items/"

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
            if isinstance(entry, dict) and entry.get("type") in {"artifact", "workspace_item"}
        ]
    elif event.type == StreamEventType.TOOL_RESULT:
        tool_meta = metadata.get("tool_metadata")
        if isinstance(tool_meta, dict):
            workspace_items = [
                e for e in tool_meta.get("workspace_items") or [] if isinstance(e, dict)
            ]
            raw = workspace_items or [
                e for e in tool_meta.get("artifacts") or [] if isinstance(e, dict)
            ]
    attachments: list[dict[str, Any]] = []
    for entry in raw:
        url = str(entry.get("url") or "")
        if not url:
            continue
        mime = str(entry.get("mime_type") or "")
        attachment = {
            "type": "image" if mime.startswith("image/") else "document",
            "filename": str(entry.get("filename") or "file"),
            "mime_type": mime,
            "url": url,
            "size_bytes": entry.get("size_bytes"),
            "generated": bool(entry.get("generated", True)),
        }
        item_id = str(entry.get("workspace_item_id") or "")
        if item_id:
            attachment.update(
                {
                    "origin": "workspace",
                    "workspace_id": str(entry.get("workspace_id") or ""),
                    "workspace_item_id": item_id,
                    "relative_path": str(entry.get("relative_path") or ""),
                    "sha256": str(entry.get("sha256") or ""),
                    "title": str(entry.get("title") or ""),
                    "caption": str(entry.get("caption") or ""),
                }
            )
        attachments.append(attachment)
    return attachments


async def fill_preview_text(attachments: list[dict[str, Any]]) -> None:
    """Populate ``extracted_text`` on artifacts the browser cannot render.

    Mutates *attachments* in place. Each supported binary is parsed in a
    short-lived process so optional Office libraries release their memory as
    soon as the preview has been produced.
    """
    if not any(_needs_preview_text(att) for att in attachments):
        return
    from deeptutor.utils.document_extractor import (
        DocumentExtractionError,
        extract_text_from_path_isolated,
    )

    for attachment in attachments:
        if not _needs_preview_text(attachment):
            continue
        path = _resolve_artifact_path(str(attachment.get("url") or ""))
        if path is None:
            continue
        try:
            text = await extract_text_from_path_isolated(
                path,
                filename_hint=str(attachment.get("filename") or path.name),
                max_chars=_PREVIEW_TEXT_MAX_CHARS,
            )
        except DocumentExtractionError as exc:
            logger.debug("No preview text for artifact %s: %s", path, exc)
            continue
        except OSError as exc:
            logger.debug("Could not read artifact %s for preview: %s", path, exc)
            continue
        if text.strip():
            attachment["extracted_text"] = text


def _needs_preview_text(attachment: dict[str, Any]) -> bool:
    filename = str(attachment.get("filename") or "")
    return Path(filename).suffix.lower() in _PREVIEW_TEXT_EXTENSIONS


def _resolve_artifact_path(url: str) -> Path | None:
    """Map an artifact's ``/files/outputs`` URL back to its file on disk.

    Returns ``None`` unless the result is a real file the outputs endpoint
    would itself serve — the same guard ``/files/outputs`` applies, so a crafted
    URL cannot walk this out of the public workspace.
    """
    if url.startswith(_WORKSPACE_ITEMS_URL_PREFIX):
        parts = url[len(_WORKSPACE_ITEMS_URL_PREFIX) :].split("/", 1)
        if len(parts) != 2:
            return None
        try:
            from deeptutor.services.workspace import get_content_workspace_service

            path, _item = get_content_workspace_service().resolve_published_item(parts[0], parts[1])
            return path
        except (OSError, ValueError):
            return None
    if not url.startswith(_OUTPUTS_URL_PREFIX):
        return None
    service = get_path_service()
    candidate = service.get_public_outputs_root() / unquote(url[len(_OUTPUTS_URL_PREFIX) :])
    if not service.is_public_output_path(candidate):
        return None
    return candidate.resolve()


__all__ = ["artifact_attachments", "fill_preview_text"]
