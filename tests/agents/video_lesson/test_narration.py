"""Narration timing and the generated voice module, without calling the TTS service."""

from __future__ import annotations

import asyncio

from deeptutor.agents.video_lesson import narration
from deeptutor.agents.video_lesson.narration import Clip, NarrationLine, estimate, voice_module


def test_estimate_spaces_captions_by_sentence() -> None:
    clip = estimate("先看结论。再看为什么！", "zh")
    assert [text for _, text in clip.captions] == ["先看结论。", "再看为什么！"]
    assert clip.captions[0][0] == 0 < clip.captions[1][0] < clip.frames
    assert clip.audio is None


def test_narrate_falls_back_to_captions_when_speech_fails(monkeypatch) -> None:
    async def broken(text: str, voice: str) -> Clip:
        raise RuntimeError("offline")

    monkeypatch.setattr(narration, "speak", broken)
    cache: dict = {}
    clips = asyncio.run(narration.narrate([NarrationLine("s1", "一句话。")], "zh", cache))
    assert clips["s1"].audio is None and clips["s1"].captions
    assert "一句话。" in cache


def test_voice_module_inlines_audio() -> None:
    module = voice_module(
        {"s1": Clip("a。", 30, [(0, "a。")], b"ID3"), "s2": estimate("b。", "zh")}
    )
    assert module.startswith("export const VOICE = ")
    assert '"src": "data:audio/mpeg;base64,SUQz"' in module
    assert module.count('"src"') == 1


def _tts(monkeypatch, **config) -> None:
    from types import SimpleNamespace

    from deeptutor.services.config import provider_runtime

    monkeypatch.setattr(
        provider_runtime, "resolve_tts_runtime_config", lambda: SimpleNamespace(**config)
    )


def test_settings_edge_voice_is_used_for_its_language(monkeypatch) -> None:
    _tts(monkeypatch, provider_name="edge", voice="en-US-AndrewMultilingualNeural")
    assert narration._configured_voice("en") == "en-US-AndrewMultilingualNeural"
    assert narration._configured_voice("zh") is None


def test_non_edge_tts_settings_keep_the_default_voice(monkeypatch) -> None:
    _tts(monkeypatch, provider_name="openai", voice="alloy")
    assert narration._configured_voice("en") is None


def test_settings_tts_provider_is_used_before_edge(monkeypatch) -> None:
    async def settings(text: str) -> Clip:
        return Clip(text, 30, [(0, text)], b"SETTINGS")

    async def edge(text: str, voice: str) -> Clip:
        raise AssertionError("Edge must not be called when the Settings provider works")

    monkeypatch.setattr(narration, "_settings_provider", lambda: "openai")
    monkeypatch.setattr(narration, "speak_with_settings", settings)
    monkeypatch.setattr(narration, "speak", edge)
    clips = asyncio.run(narration.narrate([NarrationLine("s1", "One line.")], "en"))
    assert clips["s1"].audio == b"SETTINGS"


def test_settings_tts_failure_falls_back_to_edge(monkeypatch) -> None:
    async def settings(text: str) -> Clip:
        raise RuntimeError("provider down")

    async def edge(text: str, voice: str) -> Clip:
        return Clip(text, 30, [(0, text)], b"EDGE")

    monkeypatch.setattr(narration, "_settings_provider", lambda: "openai")
    monkeypatch.setattr(narration, "speak_with_settings", settings)
    monkeypatch.setattr(narration, "speak", edge)
    monkeypatch.setattr(narration.importlib.util, "find_spec", lambda name: object())
    clips = asyncio.run(narration.narrate([NarrationLine("s1", "One line.")], "en"))
    assert clips["s1"].audio == b"EDGE"


def test_edge_settings_leave_narration_to_edge(monkeypatch) -> None:
    _tts(monkeypatch, provider_name="edge", voice="en-US-AvaNeural")
    assert narration._settings_provider() is None


def test_settings_pcm_preserves_input_rate_and_channels(monkeypatch):
    from deeptutor.agents.video_lesson import narration

    calls = []

    async def synthesize(*args, **kwargs):
        return b"\0" * 3200, "audio/pcm;rate=16000;channels=2"

    async def convert(args, data):
        calls.append(args)
        return b"\0" * 4800

    monkeypatch.setattr("deeptutor.services.voice.synthesize_speech", synthesize)
    monkeypatch.setattr(narration, "_ffmpeg", convert)
    asyncio.run(narration.speak_with_settings("Hello"))
    assert calls[0][:8] == ["-f", "s16le", "-ar", "16000", "-ac", "2", "-i", "pipe:0"]


def test_ffmpeg_is_killed_and_reaped_when_cancelled(monkeypatch):
    from deeptutor.agents.video_lesson import narration

    class Process:
        returncode = None
        killed = waited = False

        async def communicate(self, data):
            raise asyncio.CancelledError

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True

    proc = Process()

    async def create(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)

    async def check():
        try:
            await narration._ffmpeg([], b"audio")
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation was swallowed")

    asyncio.run(check())
    assert proc.killed and proc.waited
