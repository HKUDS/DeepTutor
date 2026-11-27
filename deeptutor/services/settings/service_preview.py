"""Draft-only functional checks, with real results and bounded lifetimes.

The HTTP stream owns the operation: disconnecting cancels local polling and
releases results. Remote generation may continue if a vendor has accepted it.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import AsyncIterator

from deeptutor.services.voice.discovery import selected_catalog

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 40 * 1024 * 1024
AUDIO_TYPES = {
    "audio/wav": "sample.wav",
    "audio/x-wav": "sample.wav",
    "audio/mpeg": "sample.mp3",
    "audio/mp3": "sample.mp3",
    "audio/mp4": "sample.m4a",
    "audio/x-m4a": "sample.m4a",
    "audio/webm": "sample.webm",
    "audio/ogg": "sample.ogg",
    "audio/flac": "sample.flac",
}


def validate_input(service: str, text: str, audio: str, content_type: str) -> bytes:
    if service not in {"search", "stt", "imagegen", "videogen"}:
        raise ValueError("Unsupported preview service.")
    if service != "stt":
        if not text.strip() or len(text) > 2000:
            raise ValueError("Enter between 1 and 2000 characters.")
        return b""
    if content_type not in AUDIO_TYPES:
        raise ValueError("Choose a WAV, MP3, M4A, WebM, OGG or FLAC audio file.")
    if len(audio) > ((MAX_AUDIO_BYTES + 2) // 3) * 4:
        raise ValueError("Audio samples must be at most 8 MB.")
    try:
        raw = base64.b64decode(audio, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("The audio sample could not be read.") from exc
    if not raw or len(raw) > MAX_AUDIO_BYTES:
        raise ValueError("Choose a non-empty audio sample of at most 8 MB.")
    return raw


def media_result(raw: bytes, content_type: str, kind: str) -> dict:
    allowed = {
        "image": {"image/png", "image/jpeg", "image/webp", "image/gif"},
        "video": {"video/mp4", "video/webm", "video/quicktime"},
    }
    mime = content_type.split(";", 1)[0].strip().lower()
    if not raw or len(raw) > MAX_RESULT_BYTES or mime not in allowed[kind]:
        raise ValueError("Unsupported or oversized media result.")
    return {
        "type": "result",
        "kind": kind,
        "content_type": mime,
        "data": base64.b64encode(raw).decode("ascii"),
    }


async def preview_events(
    catalog: dict,
    service: str,
    profile_id: str,
    model_id: str | None,
    text: str,
    audio: bytes = b"",
    content_type: str = "",
) -> AsyncIterator[dict]:
    catalog = selected_catalog(catalog, service, profile_id, model_id)
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=16)

    async def progress(_message: str):
        # Upstream progress can contain signed URLs; expose only our own status.
        if queue.empty():
            queue.put_nowait({"type": "progress", "phase": "rendering"})

    async def execute() -> dict:
        if service == "search":
            from deeptutor.services.config.provider_runtime import resolve_search_runtime_config
            from deeptutor.services.settings.provider_probe import test_search_access

            config = resolve_search_runtime_config(catalog=catalog)
            result = await asyncio.to_thread(
                test_search_access,
                config.requested_provider,
                config.base_url,
                config.api_key,
                proxy=config.proxy or "",
                max_results=config.max_results,
                require_results=False,
                query=text,
            )
            rows = result.search_results or result.citations
            return {
                "type": "result",
                "kind": "search",
                "text": result.answer[:12000],
                "results": [
                    {"title": r.title[:500], "url": r.url[:4000], "snippet": r.snippet[:2000]}
                    for r in rows[:10]
                ],
            }
        if service == "stt":
            from deeptutor.services.voice import transcribe_audio

            transcript = await transcribe_audio(
                audio,
                catalog=catalog,
                filename=AUDIO_TYPES[content_type],
                content_type=content_type,
            )
            return {"type": "result", "kind": "transcript", "text": transcript[:24000]}
        if service == "imagegen":
            from deeptutor.services.imagegen import generate_image

            images = await generate_image(text, catalog=catalog, n=1)
            if not images:
                raise ValueError("No image returned.")
            return media_result(*images[0], "image")
        from deeptutor.services.videogen import generate_video

        video = await generate_video(text, catalog=catalog, progress=progress)
        return media_result(*video, "video")

    task = asyncio.create_task(execute())
    pending = None
    try:
        yield {"type": "progress", "phase": "requesting"}
        async with asyncio.timeout(600 if service == "videogen" else 120):
            while not task.done():
                pending = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {task, pending}, timeout=10, return_when=asyncio.FIRST_COMPLETED
                )
                if pending in done:
                    yield pending.result()
                else:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                    if not task.done():
                        yield {"type": "heartbeat"}
                pending = None
            yield await task
    except TimeoutError:
        yield {"type": "error", "code": "timeout"}
    except Exception:
        # Provider errors may include credentials, request bodies and signed URLs.
        yield {"type": "error", "code": "failed"}
    finally:
        task.cancel()
        if pending:
            pending.cancel()
        await asyncio.gather(task, *([pending] if pending else []), return_exceptions=True)
