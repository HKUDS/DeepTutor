from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from deeptutor.api.routers import video_learning as router
from deeptutor.video_learning import TimedMediaStore


@pytest.mark.asyncio
async def test_stream_proxy_forwards_range_without_buffering_complete_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"0123456789abcdefghijklmnopqrstuvwxyz"
    base_url = "http://127.0.0.1:18080"

    def handler(request: httpx.Request) -> httpx.Response:
        raw_range = request.headers.get("range", "")
        start, end = 0, len(payload) - 1
        if raw_range.startswith("bytes="):
            start_text, end_text = raw_range.removeprefix("bytes=").split("-", 1)
            start = int(start_text)
            end = int(end_text) if end_text else end
        body = payload[start : end + 1]
        headers = {
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(body)),
        }
        if raw_range:
            headers["Content-Range"] = f"bytes {start}-{end}/{len(payload)}"
        return httpx.Response(206 if raw_range else 200, content=body, headers=headers, request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        router.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(router, "load_integrations_settings", lambda: {"invidious_base_url": base_url})
    store = TimedMediaStore(tmp_path)
    material = store.create(
        {
            "source": {"video_id": "89ThCi5qq-A"},
            "playback": {
                "formats": {
                    "18": {
                        "url": f"{base_url}/video.mp4",
                        "mime_type": "video/mp4",
                        "content_length": len(payload),
                    }
                }
            },
        }
    )

    response = await router._open_stream(store, material, "18", _Request("bytes=4-9"))
    body = b"".join([chunk async for chunk in response.body_iterator])
    if response.background is not None:
        await response.background()

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 4-9/36"
    assert body == b"456789"


class _Request:
    def __init__(self, range_value: str) -> None:
        self.headers = {"range": range_value}


@pytest.mark.asyncio
async def test_video_note_is_persisted_in_the_material_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "assert_learning_surface", lambda _surface: None)
    store = TimedMediaStore(tmp_path)
    material = store.create({"source": {"video_id": "89ThCi5qq-A"}, "learning": {"notes": []}})
    monkeypatch.setattr(router, "get_timed_media_store", lambda: store)

    note = await router.add_video_note(
        material["material_id"],
        router.NoteRequest(text="Review this definition", time_seconds=18.5),
    )

    assert note["text"] == "Review this definition"
    assert note["time_seconds"] == 18.5
    assert store.get(material["material_id"])["learning"]["notes"] == [note]
