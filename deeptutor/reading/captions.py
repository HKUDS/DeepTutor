"""Vision-derived captions for a material's embedded images.

Embedded pictures live as bytes under ``<content_id>/media/`` with a
``media.json`` index, so a text-only model reading the material sees only the
extracted text — the figures are invisible to it. This module gives every
image a one-sentence, vision-model caption and writes it back into the index,
so ``read_material`` and search can describe the whole book, not just the page
the reader happens to have open.

The pass is deliberately best-effort and model-gated: no vision-capable LLM
means no captions, a single failing image never blocks its neighbours, and any
partial success is written back rather than discarded.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from typing import Any

from deeptutor.reading.store import ReadingStore
from deeptutor.services.config.runtime_settings import load_document_parsing_settings
from deeptutor.services.llm.client import get_llm_client
from deeptutor.services.rag.pipelines.llamaindex.config import image_description_limits

logger = logging.getLogger(__name__)

CAPTION_SYSTEM_PROMPT = (
    "You describe figures for a reader who cannot see them. You state only "
    "what is visibly present and you never guess at intent."
)

CAPTION_PROMPT = (
    "Describe this image in one sentence of at most 60 words. Only describe "
    "what is actually visible: the figure title or caption, axis labels, "
    "annotations, key numbers, and any formulas as written. If it is a "
    "diagram or slide graphic, say plainly what relationship or structure it "
    "shows. Do not add greetings, commentary, or Markdown headings."
)


def captions_enabled() -> bool:
    """Whether the document-parsing settings opt into image captioning."""
    try:
        return bool(load_document_parsing_settings().get("image_caption", False))
    except Exception:  # noqa: BLE001 - a settings read must never break ingest
        return False


async def caption_material_media(
    material_id: str,
    *,
    store: ReadingStore | None = None,
    force: bool = False,
    limit: int | None = None,
) -> int:
    """Caption this material's embedded images and write them back.

    Returns the number of captions actually written. Rows that already carry a
    caption are skipped unless *force* is set; *limit* caps how many images are
    processed in this pass. A missing or text-only LLM produces zero calls and
    a warning.
    """
    store = store or ReadingStore()
    rows = store.media_items(material_id)
    pending = [row for row in rows if force or not str(row.get("caption") or "").strip()]
    if limit is not None:
        pending = pending[: max(0, int(limit))]
    if not pending:
        return 0

    try:
        client = get_llm_client()
    except Exception as exc:  # noqa: BLE001 - the client may not be configured
        logger.warning("Image captioning skipped: LLM client is unavailable (%s)", exc)
        return 0
    if not client.supports_multimodal_images():
        logger.warning("Image captioning skipped: the configured LLM does not accept image input.")
        return 0

    concurrency, timeout_seconds = image_description_limits()
    semaphore = asyncio.Semaphore(concurrency)

    async def _caption_one(row: dict[str, Any]) -> tuple[str, str] | None:
        name = str(row.get("name") or "")
        path = store.media_path(material_id, name)
        if path is None:
            logger.warning("Image captioning skipped: %s is missing on disk", name)
            return None
        mime = str(row.get("mime") or "") or (
            mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        try:
            async with semaphore:
                data = await asyncio.to_thread(path.read_bytes)
                encoded = base64.b64encode(data).decode("ascii")
                text = await asyncio.wait_for(
                    client.complete(
                        CAPTION_PROMPT,
                        system_prompt=CAPTION_SYSTEM_PROMPT,
                        image_data=encoded,
                        image_mime_type=mime,
                        image_filename=name,
                    ),
                    timeout=timeout_seconds,
                )
        except asyncio.TimeoutError:
            logger.warning("Image captioning timed out after %ss: %s", timeout_seconds, name)
            return None
        except Exception as exc:  # noqa: BLE001 - one bad image must not sink the rest
            logger.warning("Image captioning failed for %s: %s", name, exc)
            return None
        caption = str(text or "").strip()
        if not caption:
            logger.warning("Image captioning returned no text for %s", name)
            return None
        return name, caption

    results = await asyncio.gather(*(_caption_one(row) for row in pending), return_exceptions=True)
    captions: dict[str, str] = {}
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("Image captioning task failed: %s", result)
            continue
        if result is None:
            continue
        captions[result[0]] = result[1]

    if not captions:
        return 0
    return store.update_media_captions(material_id, captions)


__all__ = [
    "CAPTION_PROMPT",
    "CAPTION_SYSTEM_PROMPT",
    "caption_material_media",
    "captions_enabled",
]
