from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from deeptutor.video_learning import invidious_hub, service


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / "workspace" / feature


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    settings_path = tmp_path / "settings" / "video_learning.json"
    monkeypatch.setattr(service, "video_learning_settings_path", lambda: settings_path)
    return tmp_path


def _configure(isolated: Path) -> None:
    isolated.joinpath("settings").mkdir(parents=True, exist_ok=True)
    service.save_video_learning_settings(
        {
            "version": 1,
            "default_provider": "youtube",
            "youtube": {"transcript_provider": "youtube_transcript_api"},
            "invidious": {
                "api_base_url": "http://127.0.0.1:3000",
                "public_base_url": "http://invidious.local",
            },
        }
    )


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler):
    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, url: str, **kwargs):
            return handler(url, kwargs)

    monkeypatch.setattr(invidious_hub.httpx, "AsyncClient", _Client)


@pytest.mark.asyncio
async def test_public_feed_normalizes_popular_items(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(isolated)
    seen: list[str] = []

    def handler(url: str, kwargs: dict) -> _Response:
        seen.append(url)
        assert kwargs == {}
        return _Response(
            200,
            [
                {
                    "videoId": "dQw4w9WgXcQ",
                    "title": "  Example lecture  ",
                    "author": "Tutor",
                    "authorId": "UC123",
                    "lengthSeconds": "82",
                    "viewCount": "9",
                    "publishedText": "1 day ago",
                    "videoThumbnails": [
                        {"url": "https://images.example.test/vi/dQw4w9WgXcQ/hqdefault.jpg"},
                        {"url": "/vi/dQw4w9WgXcQ/hqdefault.jpg"},
                    ],
                },
                {"title": "missing id"},
                {"videoId": "nope"},
            ],
        )

    _patch_client(monkeypatch, handler)
    feed = await invidious_hub.get_public_feed("")
    assert seen == ["http://127.0.0.1:3000/api/v1/popular"]
    assert feed["current_tab"] == "Popular"
    assert feed["tabs"] == ["Popular", "Trending"]
    assert feed["reason"] == ""
    assert feed["items"] == [
        {
            "video_id": "dQw4w9WgXcQ",
            "has_captions": None,
            "title": "Example lecture",
            "author": "Tutor",
            "author_id": "UC123",
            "duration_seconds": 82,
            "thumbnail_url": "http://invidious.local/vi/dQw4w9WgXcQ/hqdefault.jpg",
            "view_count": 9,
            "published_text": "1 day ago",
            "url": "https://youtu.be/dQw4w9WgXcQ",
        }
    ]


@pytest.mark.asyncio
async def test_public_feed_caps_items_and_uses_trending(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(isolated)

    def handler(url: str, _kwargs: dict) -> _Response:
        assert url.endswith("/api/v1/trending")
        rows = [
            {"videoId": f"dQw4w9WgX{index:02d}", "title": f"Video {index}"}
            for index in range(invidious_hub.MAX_FEED_ITEMS + 5)
        ]
        return _Response(200, rows)

    _patch_client(monkeypatch, handler)
    feed = await invidious_hub.get_public_feed("trending")
    assert feed["current_tab"] == "Trending"
    assert len(feed["items"]) == invidious_hub.MAX_FEED_ITEMS
    assert all(item["url"].startswith("https://youtu.be/") for item in feed["items"])


@pytest.mark.asyncio
async def test_public_feed_unconfigured_and_invalid_tab(isolated: Path) -> None:
    with pytest.raises(service.TimedMediaError, match="Configure the Invidious API"):
        await invidious_hub.get_public_feed("Popular")
    _configure(isolated)
    with pytest.raises(service.TimedMediaError, match="Popular or Trending"):
        await invidious_hub.get_public_feed("Subscriptions")


@pytest.mark.asyncio
async def test_public_feed_unavailable_stays_empty(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(isolated)

    def handler(_url: str, _kwargs: dict) -> _Response:
        raise httpx.ConnectError("down")

    _patch_client(monkeypatch, handler)
    feed = await invidious_hub.get_public_feed("Popular")
    assert feed["items"] == []
    assert feed["reason"] == "unavailable"


def test_youtube_watch_url_rejects_bad_ids() -> None:
    assert invidious_hub.youtube_watch_url("dQw4w9WgXcQ") == "https://youtu.be/dQw4w9WgXcQ"
    with pytest.raises(service.TimedMediaError):
        invidious_hub.youtube_watch_url("short-id")
