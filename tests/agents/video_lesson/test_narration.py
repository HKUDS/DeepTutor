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
