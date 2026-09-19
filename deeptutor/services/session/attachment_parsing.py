"""Configured parser integration for chat PDF attachments."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import Any

from deeptutor.services.config.runtime_settings import get_chat_attachment_limits
from deeptutor.services.parsing import get_parse_service
from deeptutor.services.storage import AttachmentStore

logger = logging.getLogger(__name__)


async def parse_chat_pdf_attachments(
    records: Iterable[dict[str, Any]],
    *,
    attachment_store: AttachmentStore,
    session_id: str,
    document_texts: Iterable[str],
    on_progress: Callable[[str, str, str], None] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse every chat PDF with the active engine and update model context."""
    updated = [dict(record) for record in records]
    contexts = list(document_texts)
    limits = get_chat_attachment_limits()
    total_chars = sum(
        int(record.get("extracted_chars") or 0)
        for record in updated
        if not str(record.get("filename") or "").lower().endswith(".pdf")
    )

    for record in updated:
        filename = str(record.get("filename") or "")
        if not filename.lower().endswith(".pdf"):
            continue
        attachment_id = str(record.get("id") or "")
        if on_progress:
            on_progress(attachment_id, "submitting", "Submitting to the configured document parser")
        path = attachment_store.resolve_path(
            session_id=session_id,
            attachment_id=str(record.get("id") or ""),
            filename=filename,
        )
        error = ""
        text = ""
        if path is None:
            error = "stored attachment could not be found for configured parsing"
        elif limits.max_chars_total - total_chars <= 0:
            error = "total extracted-text quota exceeded"
        else:
            try:
                parsed = await asyncio.to_thread(
                    get_parse_service().parse,
                    path,
                    on_output=lambda message: on_progress(attachment_id, "parsing", message)
                    if on_progress
                    else None,
                )
                text = str(parsed.markdown or "").strip()
                if not text:
                    error = "configured parser produced no content"
            except Exception as exc:
                logger.info("Configured parser failed for chat PDF %s: %s", filename, exc)
                error = str(exc)
        if text:
            cap = min(limits.max_chars_per_doc, limits.max_chars_total - total_chars)
            if len(text) > cap:
                text = text[:cap] + f"... (truncated, {len(text)} chars total; chat quota hit)"
            record["extracted_text"] = text
            record["extracted_chars"] = len(text)
            record.pop("extraction_error", None)
            total_chars += len(text)
        else:
            record["extracted_text"] = ""
            record["extracted_chars"] = 0
            record["extraction_error"] = error
        _replace_context(contexts, filename, text, error)
        if on_progress:
            on_progress(
                attachment_id,
                "completed" if text else "failed",
                "Document parsing completed" if text else f"Document parsing failed: {error}",
            )
    return updated, contexts


def _replace_context(
    contexts: list[str], filename: str, text: str, error: str
) -> None:
    replacement = (
        f"[File: {filename}]\n{text}"
        if not error
        else f"[File: {filename} - could not be read: {error}]"
    )
    for index, context in enumerate(contexts):
        if context.startswith(f"[File: {filename}]"):
            contexts[index] = replacement
            return
    contexts.append(replacement)
