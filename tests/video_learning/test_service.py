from pathlib import Path
from typing import Any

import httpx
import pytest

from deeptutor.video_learning.marks import create_mark
from deeptutor.video_learning.service import (
    TimedMediaNotFound,
    TimedMediaStore,
    YouTubeResolver,
    build_segments,
    ensure_remote_material,
    normalize_cues,
    parse_timestamp,
    parse_youtube_url,
)


class _InvidiousClient:
    def __init__(self, routes: dict[str, tuple[int, Any, dict[str, str]]]) -> None:
        self.routes = routes

    async def get(self, url: str, **_kwargs: Any) -> httpx.Response:
        status, payload, headers = self.routes[url]
        request = httpx.Request("GET", url)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload, headers=headers, request=request)
        return httpx.Response(status, json=payload, headers=headers, request=request)


class _AsyncClientFactory:
    def __init__(self, client: _InvidiousClient) -> None:
        self.client = client

    async def __aenter__(self) -> _InvidiousClient:
        return self.client

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_parse_youtube_url_preserves_timestamp_without_tracking_parameters():
    parsed = parse_youtube_url("https://youtu.be/89ThCi5qq-A?t=18m42s&si=tracking")
    assert parsed.video_id == "89ThCi5qq-A"
    assert parsed.entry_time_seconds == 1122
    assert parsed.canonical_url == "https://youtu.be/89ThCi5qq-A?t=1122"


@pytest.mark.parametrize(("raw", "expected"), [("16", 16), ("1h2m3s", 3723), ("bad", 0)])
def test_parse_timestamp(raw: str, expected: int):
    assert parse_timestamp(raw) == expected


def test_build_segments_combines_short_adjacent_cues():
    cues = normalize_cues([
        {"start": 0, "duration": 5, "text": "First"},
        {"start": 5, "duration": 5, "text": "idea."},
        {"start": 40, "duration": 5, "text": "Second"},
    ])
    segments = build_segments(cues)
    assert len(segments) == 2
    assert segments[0]["text"] == "First idea."
    assert segments[0]["locator"] == 1


def test_timed_media_store_is_atomic_and_user_scoped(tmp_path: Path):
    store = TimedMediaStore(tmp_path)
    material = store.create({"source": {"video_id": "abc"}, "playback": {"formats": {}}})
    assert store.get(material["material_id"])["type"] == "timed_media"
    with pytest.raises(TimedMediaNotFound):
        store.get("../secrets")


@pytest.mark.asyncio
async def test_invidious_is_primary_and_normalizes_public_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = "http://127.0.0.1:18080"
    video_url = f"{base}/api/v1/videos/89ThCi5qq-A"
    transcript_url = f"{base}/api/v1/transcripts/89ThCi5qq-A?lang=en"
    client = _InvidiousClient(
        {
            video_url: (
                200,
                {
                    "title": "Gradient descent",
                    "author": "Course",
                    "lengthSeconds": "120",
                    "captions": [{"languageCode": "en"}],
                    "formatStreams": [
                        {
                            "itag": "18/unsafe",
                            "type": "video/mp4; codecs=avc1",
                            "url": "http://127.0.0.1:18080/video.mp4",
                            "qualityLabel": "360p",
                        }
                    ],
                },
                {},
            ),
            transcript_url: (
                200,
                [{"start": 0, "duration": 21, "text": "The first idea."}],
                {},
            ),
        }
    )

    class _Client(_InvidiousClient):
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    fake = _Client(client.routes)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _AsyncClientFactory(fake))
    monkeypatch.setattr(
        "deeptutor.video_learning.service._optional_ytdlp_metadata",
        lambda _url: pytest.fail("yt-dlp fallback must not run when Invidious succeeds"),
    )
    monkeypatch.setattr(
        "deeptutor.video_learning.service._is_disallowed_host",
        lambda _host: False,
    )

    material = await YouTubeResolver(base_url=base).resolve(
        "https://youtu.be/89ThCi5qq-A?t=16",
        store=TimedMediaStore(tmp_path),
    )

    assert material["source"]["entry_time_seconds"] == 16
    assert material["transcript"]["source"] == "invidious"
    assert material["segments"][0]["locator"] == 1
    format_ids = list(material["playback"]["formats"])
    assert len(format_ids) == 1
    assert format_ids[0] != "18/unsafe"


@pytest.mark.asyncio
async def test_resolve_reuses_feed_launched_remote_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = "http://127.0.0.1:18080"
    video_url = f"{base}/api/v1/videos/89ThCi5qq-A"
    transcript_url = f"{base}/api/v1/transcripts/89ThCi5qq-A?lang=en"
    client = _InvidiousClient(
        {
            video_url: (
                200,
                {
                    "title": "Gradient descent",
                    "author": "Course",
                    "lengthSeconds": "120",
                    "captions": [{"languageCode": "en"}],
                    "formatStreams": [
                        {"itag": "18", "type": "video/mp4", "url": f"{base}/video.mp4"}
                    ],
                },
                {},
            ),
            transcript_url: (
                200,
                [{"start": 10, "duration": 5, "text": "Remote key idea context."}],
                {},
            ),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _AsyncClientFactory(client))
    monkeypatch.setattr(
        "deeptutor.video_learning.service._optional_ytdlp_metadata",
        lambda _url: {},
    )
    store = TimedMediaStore(tmp_path)
    skeleton = ensure_remote_material("89ThCi5qq-A", title="Temporary feed title")
    mark = create_mark(
        skeleton,
        {
            "kind": "key_point",
            "start_seconds": 12,
            "end_seconds": 12,
            "note": "Captured from phone",
            "source": "remote_phone",
        },
    )
    store.save(skeleton)

    resolved = await YouTubeResolver(base_url=base).resolve(
        "https://youtu.be/89ThCi5qq-A",
        language="en",
        store=store,
    )

    assert resolved["material_id"] == skeleton["material_id"]
    assert resolved["metadata"]["title"] == "Gradient descent"
    assert resolved["transcript"]["cues"]
    assert resolved["learning"]["marks"] == [mark]


@pytest.mark.asyncio
async def test_invidious_redirect_outside_configured_origin_is_rejected() -> None:
    base = "http://127.0.0.1:18080"
    client = _InvidiousClient(
        {
            f"{base}/api/v1/videos/89ThCi5qq-A": (
                302,
                b"",
                {"location": "https://attacker.example/api/v1/videos/89ThCi5qq-A"},
            ),
        }
    )
    resolver = YouTubeResolver(base_url=base)
    with pytest.raises(Exception, match="redirected outside"):
        await resolver._json(client, f"{base}/api/v1/videos/89ThCi5qq-A")


@pytest.mark.asyncio
async def test_invidious_caption_redirect_within_configured_origin_is_followed() -> None:
    base = "http://127.0.0.1:18080"
    caption_url = f"{base}/api/v1/captions/89ThCi5qq-A?lang=en"
    companion_url = f"{base}/companion/api/v1/captions/89ThCi5qq-A?lang=en&check=trusted"
    client = _InvidiousClient(
        {
            caption_url: (302, b"", {"location": "/companion/api/v1/captions/89ThCi5qq-A?lang=en&check=trusted"}),
            companion_url: (200, b"WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nOpening idea\n", {}),
        }
    )

    response = await YouTubeResolver(base_url=base)._get(client, caption_url)

    assert response.status_code == 200
    assert "Opening idea" in response.text


@pytest.mark.asyncio
async def test_resolve_honors_requested_caption_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = "http://127.0.0.1:18080"
    video_url = f"{base}/api/v1/videos/89ThCi5qq-A"
    transcript_url = f"{base}/api/v1/transcripts/89ThCi5qq-A?lang=en"
    client = _InvidiousClient(
        {
            video_url: (
                200,
                {
                    "title": "Language selection",
                    "lengthSeconds": "30",
                    "captions": [{"languageCode": "zh-CN"}, {"languageCode": "en"}],
                    "formatStreams": [{"itag": "18", "type": "video/mp4", "url": f"{base}/video.mp4"}],
                },
                {},
            ),
            transcript_url: (200, [{"start": 0, "duration": 21, "text": "English caption."}], {},),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _AsyncClientFactory(client))
    monkeypatch.setattr("deeptutor.video_learning.service._optional_ytdlp_metadata", lambda _url: {})
    material = await YouTubeResolver(base_url=base).resolve(
        "https://youtu.be/89ThCi5qq-A",
        language="en",
        store=TimedMediaStore(tmp_path),
    )
    assert material["transcript"]["language"] == "en"
    assert material["transcript"]["cues"][0]["text"] == "English caption."
