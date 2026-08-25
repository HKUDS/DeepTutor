"""Offline tests for Bilibili learning and the reserved YouTube branch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.tools.builtin import WebFetchTool
from deeptutor.tools.video_learning import detect_video_provider, learn_video


class _Response:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        url: str = "",
        content: bytes = b"",
        content_type: str = "application/json",
    ) -> None:
        self.status_code = 200
        self.url = url
        self.headers = {
            "content-length": str(len(content)),
            "content-type": content_type,
        }
        self.content = content
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    async def aiter_bytes(self):
        yield self.content or json.dumps(self._payload).encode()


class _Client:
    def __init__(self, routes: dict[str, dict[str, Any]]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((url, kwargs))
        if url not in self.routes:
            raise AssertionError(f"unexpected URL: {url}")
        return _Response(self.routes[url])

    def stream(self, _method: str, url: str, **kwargs: Any):
        outer = self

        class _StreamContext:
            async def __aenter__(self) -> _Response:
                outer.calls.append((url, kwargs))
                if url not in outer.routes:
                    raise AssertionError(f"unexpected URL: {url}")
                route = outer.routes[url]
                return route if isinstance(route, _Response) else _Response(route)

            async def __aexit__(self, *_args: object) -> None:
                return None

        return _StreamContext()


def _factory(client: _Client):
    def factory(*, timeout: float, user_agent: str) -> _Client:
        return client

    return factory


def _bilibili_routes() -> dict[str, dict[str, Any]]:
    return {
        "https://api.bilibili.com/x/web-interface/view?bvid=BV1234567890": {
            "code": 0,
            "data": {
                "bvid": "BV1234567890",
                "cid": 111,
                "title": "Fourier Basics",
                "desc": "<p>Signals and frequencies.</p>",
                "duration": 3661,
                "owner": {"name": "Learning Lab"},
                "pages": [
                    {"cid": 111, "part": "Part 1", "duration": 3600},
                    {"cid": 222, "part": "Part 2", "duration": 61},
                ],
            },
        },
        "https://api.bilibili.com/x/player/v2?bvid=BV1234567890&cid=222": {
            "code": 0,
            "data": {
                "subtitle": {
                    "subtitles": [
                        {"lan": "en", "subtitle_url": "//en.example.invalid/subtitle.json"},
                        {
                            "lan": "zh-CN",
                            "lan_doc": "中文（简体）",
                            "subtitle_url": "//aisubtitle.hdslb.com/bcd/subtitle.json",
                        },
                    ]
                }
            },
        },
        "https://aisubtitle.hdslb.com/bcd/subtitle.json": {
            "body": [
                {"from": 1, "to": 2, "content": "第一句"},
                {"from": 61, "to": 62, "content": "第二句"},
            ]
        },
    }


def test_detects_video_providers_and_reserves_youtube() -> None:
    assert detect_video_provider("https://www.bilibili.com/video/BV1234567890?p=2") == "bilibili"
    assert detect_video_provider("https://b23.tv/BV1234567890") == "bilibili"
    assert detect_video_provider("https://www.youtube.com/watch?v=abc") == "youtube"
    assert detect_video_provider("https://youtu.be/abc") == "youtube"
    assert detect_video_provider("https://example.com/video/BV1234567890") is None


@pytest.mark.asyncio
async def test_bilibili_learning_selects_page_and_preferred_subtitle() -> None:
    client = _Client(_bilibili_routes())

    outcome = await learn_video(
        "https://www.bilibili.com/video/BV1234567890?p=2",
        max_chars=10_000,
        client_factory=_factory(client),
        host_validator=lambda _host: False,
    )

    assert outcome.ok is True
    assert outcome.url == "https://www.bilibili.com/video/BV1234567890?p=2"
    assert outcome.title == "Fourier Basics"
    assert outcome.author == "Learning Lab"
    assert outcome.duration_seconds == 61
    assert outcome.subtitle_language == "zh-CN"
    assert "[00:01] 第一句" in outcome.markdown
    assert "[01:01] 第二句" in outcome.markdown
    assert client.calls[1][0] == "https://api.bilibili.com/x/player/v2?bvid=BV1234567890&cid=222"


@pytest.mark.asyncio
async def test_bilibili_learning_reports_missing_subtitle_without_guessing(
    tmp_path: Path,
) -> None:
    routes = _bilibili_routes()
    routes["https://api.bilibili.com/x/player/v2?bvid=BV1234567890&cid=111"] = {
        "code": 0,
        "data": {"subtitle": {"subtitles": []}},
    }
    client = _Client(routes)

    outcome = await learn_video(
        "https://www.bilibili.com/video/BV1234567890",
        max_chars=10_000,
        client_factory=_factory(client),
        host_validator=lambda _host: False,
        state_dir=tmp_path,
    )

    assert outcome.ok is False
    assert outcome.title == "Fourier Basics"
    assert "no subtitle" in outcome.error
    assert "generate_transcript_if_missing" in outcome.error
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_bilibili_subtitle_redirect_is_rechecked() -> None:
    routes = _bilibili_routes()
    routes["https://aisubtitle.hdslb.com/bcd/subtitle.json"] = _Response(
        {},
        url="https://attacker.invalid/subtitle.json",
        content=b"{}",
    )
    client = _Client(routes)

    outcome = await learn_video(
        "https://www.bilibili.com/video/BV1234567890?p=2",
        max_chars=10_000,
        client_factory=_factory(client),
        host_validator=lambda _host: False,
    )

    assert outcome.ok is False
    assert "outside its allowed domains" in outcome.error


@pytest.mark.asyncio
async def test_prepared_transcript_is_reused_without_refetching_audio(
    tmp_path: Path,
) -> None:
    from deeptutor.tools.video_learning import _save_video_state

    url = "https://www.bilibili.com/video/BV1234567890"
    _save_video_state(
        url,
        tmp_path,
        status="succeeded",
        job_id="job-1",
        segments=[{"from": 12, "content": "生成的句子"}],
    )
    routes = _bilibili_routes()
    routes["https://api.bilibili.com/x/player/v2?bvid=BV1234567890&cid=111"] = {
        "code": 0,
        "data": {"subtitle": {"subtitles": []}},
    }
    client = _Client(routes)

    outcome = await learn_video(
        url,
        max_chars=10_000,
        client_factory=_factory(client),
        host_validator=lambda _host: False,
        state_dir=tmp_path,
    )

    assert outcome.ok is True
    assert outcome.job_id == "job-1"
    assert outcome.subtitle_language == "auto"
    assert "[00:12] 生成的句子" in outcome.markdown
    assert all("playurl" not in called_url for called_url, _ in client.calls)


@pytest.mark.asyncio
async def test_invalid_youtube_url_is_rejected() -> None:
    outcome = await learn_video("https://youtu.be/abc", max_chars=10_000)

    assert outcome.ok is False
    assert outcome.provider == "youtube"
    assert "invalid YouTube URL" in outcome.error


@pytest.mark.asyncio
async def test_background_preparation_uses_audio_only_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.tools.video_learning as video_learning

    async def fake_transcribe(
        audio: bytes,
        *,
        duration_seconds: int,
        content_type: str,
    ) -> list[dict[str, Any]]:
        assert audio == b"AUDIODATA"
        assert duration_seconds == 60
        assert content_type == "audio/mp4"
        return [{"start": 3, "end": 60, "text": "自动转写文本"}]

    monkeypatch.setattr(video_learning, "_transcribe_audio_segments", fake_transcribe)
    routes = {
        "https://api.bilibili.com/x/web-interface/view?bvid=BV1234567890": {
            "code": 0,
            "data": {
                "title": "Fourier Basics",
                "cid": 111,
                "duration": 60,
                "owner": {"name": "Learning Lab"},
                "pages": [{"cid": 111, "part": "P1", "duration": 60}],
            },
        },
        "https://api.bilibili.com/x/player/playurl?bvid=BV1234567890&cid=111&fnval=16": {
            "code": 0,
            "data": {
                "dash": {
                    "audio": [
                        {
                            "bandwidth": 1000,
                            "baseUrl": "//upos-sz-mirror08c.bilivideo.com/a.m4a",
                        },
                        {
                            "bandwidth": 100,
                            "baseUrl": "https://upos-sz-mirror08c.bilivideo.com/low.m4a",
                        },
                    ]
                }
            },
        },
    }
    routes["https://upos-sz-mirror08c.bilivideo.com/low.m4a"] = _Response(
        {},
        content=b"AUDIODATA",
        content_type="audio/mp4",
    )
    client = _Client(routes)
    await video_learning._run_transcript_preparation(
        "https://www.bilibili.com/video/BV1234567890",
        job_id="job-2",
        client_factory=_factory(client),
        host_validator=lambda _host: False,
        state_dir=tmp_path,
    )

    state = video_learning._load_video_state(
        "https://www.bilibili.com/video/BV1234567890", tmp_path
    )
    assert state["status"] == "succeeded", state
    assert state["segments"] == [
        {"start": 3, "end": 60, "text": "自动转写文本", "locator": 1}
    ]
    assert state["transcript"]["source"]["duration_seconds"] == 60
    assert state["transcript"]["source"]["video_id"] == "BV1234567890"
    assert state["transcript"]["source"]["cid"] == 111
    assert state["transcript"]["source"]["page"] == 1
    assert state["audio_bytes"] == len(b"AUDIODATA")


def test_bilibili_audio_urls_are_limited_to_bilibili_media_domains() -> None:
    from deeptutor.tools.video_learning import _select_bilibili_audio_url

    unsafe = {
        "audio": [
            {"bandwidth": 1, "baseUrl": "https://example.com/audio.m4a"},
        ]
    }
    with pytest.raises(ValueError, match="unsafe audio URL"):
        _select_bilibili_audio_url(unsafe, lambda _host: False)


@pytest.mark.asyncio
async def test_bilibili_audio_stream_stops_at_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.tools.video_learning as video_learning

    monkeypatch.setattr(video_learning, "MAX_AUDIO_BYTES", 4)
    calls: list[int] = []

    class _ChunkResponse:
        status_code = 200
        url = "https://mirror.bilivideo.com/audio.m4a"
        headers = {"content-type": "audio/mp4"}

        async def aiter_bytes(self):
            for size in (3, 2, 5):
                calls.append(size)
                yield b"a" * size

    class _ChunkClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def stream(self, *_args: object, **_kwargs: object):
            outer = self

            class _Context:
                async def __aenter__(self):
                    return _ChunkResponse()

                async def __aexit__(self, *_exit_args: object) -> None:
                    return None

            return _Context()

    with pytest.raises(ValueError, match="32 MB"):
        await video_learning._read_bilibili_audio(
            _ChunkClient(),
            "https://mirror.bilivideo.com/audio.m4a",
            {},
            validator=lambda _host: False,
        )
    assert calls == [3, 2]


@pytest.mark.asyncio
async def test_bilibili_audio_redirect_is_rechecked() -> None:
    import deeptutor.tools.video_learning as video_learning

    class _RedirectResponse:
        status_code = 200
        url = "https://example.com/audio.m4a"
        headers = {"content-type": "audio/mp4"}

        async def aiter_bytes(self):
            yield b"a"

    class _RedirectClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def stream(self, *_args: object, **_kwargs: object):
            outer = self

            class _Context:
                async def __aenter__(self):
                    return _RedirectResponse()

                async def __aexit__(self, *_exit_args: object) -> None:
                    return None

            return _Context()

    with pytest.raises(ValueError, match="allowed CDN domains"):
        await video_learning._read_bilibili_audio(
            _RedirectClient(),
            "https://mirror.bilivideo.com/audio.m4a",
            {},
            validator=lambda _host: False,
        )


@pytest.mark.asyncio
async def test_web_fetch_surfaces_video_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.tools.video_learning as video_learning

    async def fake_learn_video(url: str, *, max_chars: int, **_kwargs: Any):
        return video_learning.VideoLearningOutcome(
            ok=True,
            provider="bilibili",
            markdown="# Video\ntranscript",
            url=url,
            title="Video",
            author="Author",
            duration_seconds=90,
            subtitle_language="zh-CN",
        )

    monkeypatch.setattr(video_learning, "learn_video", fake_learn_video)

    result = await WebFetchTool().execute(url="https://www.bilibili.com/video/BV1234567890")

    assert result.success is True
    assert result.sources == [
        {
            "type": "video",
            "provider": "bilibili",
            "url": "https://www.bilibili.com/video/BV1234567890",
            "title": "Video",
        }
    ]
    assert result.metadata["duration_seconds"] == 90


@pytest.mark.asyncio
async def test_web_fetch_uses_current_user_video_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope
    import deeptutor.tools.video_learning as video_learning

    user_root = tmp_path / "data" / "users" / "u_alice"
    received: dict[str, Path] = {}

    async def fake_learn_video(url: str, *, max_chars: int, state_dir: Path, **_kwargs: Any):
        received["state_dir"] = state_dir
        return video_learning.VideoLearningOutcome(
            ok=True,
            provider="bilibili",
            markdown="# Video\ntranscript",
            url=url,
            title="Video",
        )

    monkeypatch.setattr(video_learning, "learn_video", fake_learn_video)
    token = set_current_user(
        CurrentUser(
            id="u_alice",
            username="alice",
            role="user",
            scope=UserScope(kind="user", user_id="u_alice", root=user_root),
        )
    )
    try:
        await WebFetchTool().execute(url="https://www.bilibili.com/video/BV1234567890")
    finally:
        reset_current_user(token)

    assert received["state_dir"] == user_root.resolve() / "user" / "video_learning"
