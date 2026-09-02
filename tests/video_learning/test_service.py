from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from deeptutor.video_learning import service


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / "workspace" / feature


@pytest.fixture
def isolated(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    settings_path = tmp_path / "settings" / "video_learning.json"
    monkeypatch.setattr(service, "video_learning_settings_path", lambda: settings_path)
    return tmp_path


@pytest.mark.parametrize(
    ("url", "video_id", "start"),
    [
        ("https://youtu.be/dQw4w9WgXcQ?t=82", "dQw4w9WgXcQ", 82),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1m2s&si=tracking", "dQw4w9WgXcQ", 62),
        ("https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ", 0),
        ("https://youtube.com/live/dQw4w9WgXcQ?start=12", "dQw4w9WgXcQ", 12),
        ("https://youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ", 0),
    ],
)
def test_parse_supported_youtube_urls(url: str, video_id: str, start: int) -> None:
    parsed = service.parse_youtube_url(url)
    assert parsed.video_id == video_id
    assert parsed.entry_time_seconds == start
    assert "si=" not in parsed.canonical_url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=../../etc",
        "https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ",
    ],
)
def test_rejects_non_youtube_and_invalid_ids(url: str) -> None:
    with pytest.raises(service.TimedMediaError):
        service.parse_youtube_url(url)


def test_segments_are_stable_learning_units() -> None:
    cues = [
        {"start": 0.0, "end": 10.0, "text": "One"},
        {"start": 10.0, "end": 22.0, "text": "sentence."},
        {"start": 22.0, "end": 45.0, "text": "Next concept."},
    ]
    segments = service.build_segments(cues)
    assert segments[0] == {"locator": 1, "start": 0.0, "end": 22.0, "text": "One sentence."}
    assert segments[1]["locator"] == 2


def test_transcript_normalization_enforces_the_storage_budget(monkeypatch) -> None:
    monkeypatch.setattr(service, "MAX_TRANSCRIPT_BYTES", 8)
    cues = service.normalize_cues(
        [
            {"start": 0, "duration": 1, "text": "1234"},
            {"start": 1, "duration": 1, "text": "5678"},
            {"start": 2, "duration": 1, "text": "overflow"},
        ]
    )
    assert [cue["text"] for cue in cues] == ["1234", "5678"]


def test_webvtt_preserves_caption_after_leading_blank_and_inline_tags() -> None:
    cues = service.parse_webvtt(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n \nOpening <c>idea</c>\nand continuation\n"
    )

    assert cues == [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "Opening idea and continuation",
        }
    ]


def test_webvtt_keeps_ordinary_cues_and_accepts_timing_settings() -> None:
    cues = service.parse_webvtt(
        """WEBVTT

first-cue
00:01.000 --> 00:02.500 line:90% position:50% align:middle
Ordinary caption

00:03.000 --> 00:04.000
Second line
"""
    )

    assert cues == [
        {"start": 1.0, "end": 2.5, "text": "Ordinary caption"},
        {"start": 3.0, "end": 4.0, "text": "Second line"},
    ]


def test_invidious_caption_choice_accepts_the_real_snake_case_schema() -> None:
    captions = [
        {"label": "English (auto-generated)", "language_code": "en", "auto_generated": True},
        {"label": "中文", "language_code": "zh-CN", "auto_generated": False},
    ]
    assert service._caption_choice(captions, "zh-CN") == captions[1]
    assert service._caption_choice(captions, "en") == captions[0]


def test_settings_accept_local_http_and_require_invidious_origin() -> None:
    normalized = service.normalize_video_learning_settings(
        {
            "default_provider": "invidious",
            "youtube": {"transcript_provider": "none"},
            "invidious": {"api_base_url": "http://127.0.0.1:3000/"},
        }
    )
    assert normalized["invidious"]["api_base_url"] == "http://127.0.0.1:3000"
    assert normalized["invidious"]["public_base_url"] == ""
    with pytest.raises(service.TimedMediaError):
        service.normalize_video_learning_settings({"default_provider": "invidious"})
    with pytest.raises(service.TimedMediaError):
        service.normalize_video_learning_settings(
            {"invidious": {"api_base_url": "http://localhost:99999"}}
        )


def test_store_discards_legacy_or_ephemeral_playback_descriptors(isolated: Path) -> None:
    store = service.get_timed_media_store()
    material_id = service.material_id_for("dQw4w9WgXcQ")
    store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": material_id,
            "source": {"video_id": "dQw4w9WgXcQ"},
            "playback": {"formats": {"18": {"url": "https://secret.example/video"}}},
            "learning": {"last_position": 17},
        }
    )
    raw = json.loads((isolated / "workspace" / "timed_media" / f"{material_id}.json").read_text())
    assert "playback" not in raw
    assert "secret.example" not in json.dumps(raw)


@pytest.mark.asyncio
async def test_legacy_v1_material_ignores_expired_playback_descriptor(isolated: Path) -> None:
    material_id = service.material_id_for("dQw4w9WgXcQ")
    path = isolated / "workspace" / "timed_media" / f"{material_id}.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "type": "timed_media",
                "material_id": material_id,
                "source": {
                    "provider": "youtube",
                    "video_id": "dQw4w9WgXcQ",
                    "url": "https://youtu.be/dQw4w9WgXcQ",
                },
                "metadata": {"duration_seconds": 100},
                "transcript": {"status": "unavailable", "cues": []},
                "learning": {"last_position": 23},
                "playback": {"url": "https://expired.example/direct.mp4"},
            }
        ),
        encoding="utf-8",
    )

    material = await service.material_with_playback(material_id)

    assert material["playback"] == {
        "provider": "youtube",
        "kind": "youtube_iframe",
        "video_id": "dQw4w9WgXcQ",
        "start_seconds": 23.0,
    }
    assert "expired.example" not in json.dumps(material)


def test_stores_with_the_same_material_id_are_user_isolated(tmp_path: Path) -> None:
    material_id = service.material_id_for("dQw4w9WgXcQ")
    first = service.TimedMediaStore(tmp_path / "alice")
    second = service.TimedMediaStore(tmp_path / "bob")
    base = {"version": 1, "type": "timed_media", "material_id": material_id}
    first.save({**base, "learning": {"last_position": 11}})
    second.save({**base, "learning": {"last_position": 22}})

    assert first.get(material_id)["learning"]["last_position"] == 11
    assert second.get(material_id)["learning"]["last_position"] == 22


@pytest.mark.asyncio
async def test_provider_switch_preserves_material_and_progress(monkeypatch, isolated: Path) -> None:
    async def youtube_metadata(_request):
        return {"title": "Native", "author_name": "Teacher"}

    async def youtube_transcript(_video_id, _language):
        return ([{"start": 0, "end": 12, "text": "Hello"}], "en", "youtube_transcript_api")

    async def invidious_resolution(_request, _language):
        return service.ProviderResolution(
            metadata={"title": "Mirror", "author": "Teacher", "lengthSeconds": 100},
            cues=[{"start": 0, "end": 12, "text": "Hello"}],
            transcript_language="en",
            transcript_source="invidious",
            formats=[{"format_id": "18", "mime_type": "video/mp4", "quality": "360p"}],
        )

    monkeypatch.setattr(service, "_youtube_metadata", youtube_metadata)
    monkeypatch.setattr(service, "_youtube_transcript", youtube_transcript)
    monkeypatch.setattr(service, "_invidious_resolution", invidious_resolution)
    first = await service.resolve_material("https://youtu.be/dQw4w9WgXcQ")
    stored = service.get_timed_media_store().get(first["material_id"])
    stored["learning"]["last_position"] = 42
    service.get_timed_media_store().save(stored)
    service.save_video_learning_settings(
        {
            "default_provider": "invidious",
            "youtube": {"transcript_provider": "youtube_transcript_api"},
            "invidious": {"api_base_url": "http://localhost:3000"},
        }
    )
    second = await service.resolve_material("https://youtu.be/dQw4w9WgXcQ")
    assert second["material_id"] == first["material_id"]
    assert second["learning"]["last_position"] == 42
    assert second["playback"]["provider"] == "invidious"


@pytest.mark.asyncio
async def test_missing_transcript_does_not_block_native_playback(
    monkeypatch, isolated: Path
) -> None:
    async def youtube_metadata(_request):
        return {"title": "No captions"}

    async def youtube_transcript(_video_id, _language):
        return [], "", "dependency_missing"

    monkeypatch.setattr(service, "_youtube_metadata", youtube_metadata)
    monkeypatch.setattr(service, "_youtube_transcript", youtube_transcript)
    material = await service.resolve_material("https://youtu.be/dQw4w9WgXcQ")
    assert material["playback"]["kind"] == "youtube_iframe"
    assert material["transcript"]["status"] == "unavailable"
    assert material["transcript"]["reason"] == "dependency_missing"


@pytest.mark.asyncio
async def test_refresh_invidious_transcript_preserves_playback_and_progress(
    monkeypatch, isolated: Path
) -> None:
    material_id = service.material_id_for("dQw4w9WgXcQ")
    store = service.get_timed_media_store()
    store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": material_id,
            "source": {
                "provider": "youtube",
                "video_id": "dQw4w9WgXcQ",
                "url": "https://youtu.be/dQw4w9WgXcQ",
            },
            "metadata": {"title": "Retry lesson", "duration_seconds": 120},
            "transcript": {"status": "unavailable", "reason": "unavailable", "cues": []},
            "segments": [],
            "learning": {"last_position": 42},
            "provider_cache": {
                "invidious_formats": [{"format_id": "18", "mime_type": "video/mp4"}]
            },
        }
    )
    service.save_video_learning_settings(
        {"default_provider": "invidious", "invidious": {"api_base_url": "http://invidious:3000"}}
    )

    async def metadata(_client, _base, _video_id):
        return {"captions": [{"label": "English", "languageCode": "en"}]}

    async def transcript(_client, _base, _video_id, _captions, _language, **_kwargs):
        return ([{"start": 1, "end": 4, "text": "Recovered caption."}], "en", "invidious")

    monkeypatch.setattr(service, "_invidious_metadata", metadata)
    monkeypatch.setattr(service, "_invidious_transcript", transcript)

    refreshed = await service.refresh_invidious_transcript(material_id)

    assert refreshed["transcript"]["status"] == "ready"
    assert refreshed["segments"] == [
        {"locator": 1, "start": 1, "end": 4, "text": "Recovered caption."}
    ]
    assert refreshed["learning"]["last_position"] == 42
    assert refreshed["playback"]["format_id"] == "18"
    assert "revision=" in refreshed["playback"]["subtitles_url"]


@pytest.mark.asyncio
async def test_refresh_invidious_transcript_does_not_overwrite_on_failure(
    monkeypatch, isolated: Path
) -> None:
    material_id = service.material_id_for("dQw4w9WgXcQ")
    store = service.get_timed_media_store()
    original = {
        "version": 1,
        "type": "timed_media",
        "material_id": material_id,
        "source": {"provider": "youtube", "video_id": "dQw4w9WgXcQ"},
        "transcript": {"status": "unavailable", "reason": "unavailable", "cues": []},
        "segments": [],
        "learning": {"last_position": 42},
        "provider_cache": {"invidious_formats": [{"format_id": "18", "mime_type": "video/mp4"}]},
    }
    store.save(original)
    service.save_video_learning_settings(
        {"default_provider": "invidious", "invidious": {"api_base_url": "http://invidious:3000"}}
    )

    async def metadata(_client, _base, _video_id):
        raise service.TimedMediaError("Invidious request failed with HTTP 503.")

    monkeypatch.setattr(service, "_invidious_metadata", metadata)

    with pytest.raises(service.TimedMediaError, match="HTTP 503"):
        await service.refresh_invidious_transcript(material_id)

    stored = store.get(material_id)
    assert stored["transcript"] == original["transcript"]
    assert stored["learning"] == original["learning"]


def test_service_module_does_not_bind_fcntl_at_import() -> None:
    # Top-level ``import fcntl`` breaks ``deeptutor start`` on Windows (#1140).
    assert "fcntl" not in service.__dict__


def test_timed_media_store_lock_is_cross_platform(isolated: Path) -> None:
    store = service.TimedMediaStore(root=isolated / "workspace" / "timed_media")
    material_id = "a" * 32
    with store.lock(material_id):
        lock_path = store.root / ".locks" / f"{material_id}.lock"
        assert lock_path.is_file()
        assert lock_path.stat().st_size >= 1


def test_timed_media_store_uses_msvcrt_locking_on_windows(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, int]] = []
    fake_msvcrt = SimpleNamespace(
        LK_LOCK=1,
        LK_UNLCK=2,
        locking=lambda _fileno, mode, length: calls.append((mode, length)),
    )
    monkeypatch.setattr(service, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    store = service.TimedMediaStore(root=isolated / "workspace" / "timed_media")
    with store.lock("b" * 32):
        assert calls == [(fake_msvcrt.LK_LOCK, 1)]

    assert calls == [
        (fake_msvcrt.LK_LOCK, 1),
        (fake_msvcrt.LK_UNLCK, 1),
    ]
