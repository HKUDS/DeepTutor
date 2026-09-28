"""Configured parser integration for chat PDF attachments."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
import logging
import re
from typing import Any

from deeptutor.services.config.runtime_settings import get_chat_attachment_limits
from deeptutor.services.parsing import get_parse_service
from deeptutor.services.storage import AttachmentStore
from deeptutor.utils.document_images import find_markers

logger = logging.getLogger(__name__)
_PDF_PAGE_HEADER = re.compile(r"--- Page (\d+) ---")


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
    if not any(str(record.get("filename") or "").lower().endswith(".pdf") for record in updated):
        return updated, contexts
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
        fallback_text = str(record.get("extracted_text") or "").strip()
        if path is None:
            error = "stored attachment could not be found for configured parsing"
        elif limits.max_chars_total - total_chars <= 0:
            error = "total extracted-text quota exceeded"
        else:
            try:
                parsed = await asyncio.to_thread(
                    get_parse_service().parse,
                    path,
                    on_output=lambda message: (
                        on_progress(attachment_id, "parsing", message) if on_progress else None
                    ),
                )
                if on_progress:
                    on_progress(attachment_id, "retrieving", "Retrieving parsed document result")
                text = str(parsed.markdown or "").strip()
                if not text:
                    error = "configured parser produced no content"
            except Exception as exc:
                logger.info("Configured parser failed for chat PDF %s: %s", filename, exc)
                error = str(exc)
        if text:
            cap = min(limits.max_chars_per_doc, limits.max_chars_total - total_chars)
            image_locations = _pdf_image_locations(fallback_text, text)
            if image_locations:
                # Reserve room for the original page-to-image mapping even if
                # the configured parser's Markdown fills the text quota.
                note = "\n\n[Embedded image locations in original PDF]"
                for location in image_locations:
                    if len(note) + 1 + len(location) > cap:
                        break
                    note += "\n" + location
                if note != "\n\n[Embedded image locations in original PDF]":
                    text = text[: cap - len(note)] + note
                else:
                    text = text[:cap]
            elif len(text) > cap:
                text = text[:cap] + f"... (truncated, {len(text)} chars total; chat quota hit)"
            record["extracted_text"] = text
            record["extracted_chars"] = len(text)
            record.pop("extraction_error", None)
            record.pop("parser_error", None)
            total_chars += len(text)
            phase = "completed"
            detail = "Document parsing completed"
        elif fallback_text:
            # A configured cloud/local engine can be temporarily unavailable.
            # Preserve usable native text rather than turning a readable PDF
            # into a failed attachment; the parser error remains observable.
            text = fallback_text
            record["extracted_text"] = text
            record["extracted_chars"] = len(text)
            record.pop("extraction_error", None)
            record["parser_error"] = error
            total_chars += len(text)
            _replace_context(contexts, filename, text, "")
            phase = "fallback"
            detail = f"Configured parser failed; using local PDF text: {error}"
        else:
            record["extracted_text"] = ""
            record["extracted_chars"] = 0
            record["extraction_error"] = error
            _replace_context(contexts, filename, text, error)
            phase = "failed"
            detail = f"Document parsing failed: {error}"
        if text and phase == "completed":
            _replace_context(contexts, filename, text, "")
        if on_progress:
            on_progress(
                attachment_id,
                phase,
                detail,
            )
    return updated, contexts


def _pdf_image_locations(native_text: str, parsed_text: str) -> list[str]:
    """Keep native PDF page markers for images omitted by configured parsers."""
    page_number: str | None = None
    locations: list[str] = []
    for line in native_text.splitlines():
        stripped = line.strip()
        page = _PDF_PAGE_HEADER.fullmatch(stripped)
        if page:
            page_number = page.group(1)
        elif page_number:
            for index, name in find_markers(stripped):
                location = f"--- Page {page_number} ---\n[图片 {index}: {name}]"
                if location not in parsed_text and location not in locations:
                    locations.append(location)
    return locations


def _replace_context(contexts: list[str], filename: str, text: str, error: str) -> None:
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
