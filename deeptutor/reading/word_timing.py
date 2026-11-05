"""Word-timed speech for Immersive Reading (NaturalReader-style highlighting).

The plain ``read-aloud`` endpoint returns audio with no timing metadata, so the
reader can only highlight a whole paragraph. This module adds per-word timing on
top of the existing voice stack:

* Edge voices expose ``WordBoundary`` events (offset/duration in 100-ns ticks).
* Providers that cannot report boundaries still return audio; the client then
  falls back to a proportional estimate.

Everything here is additive: when a provider has no timing support the response
is still valid audio, and the caller keeps working.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import Any

from deeptutor.services.voice import VoiceProviderError, synthesize_speech

logger = logging.getLogger(__name__)

# Word boundaries are timed in 100-nanosecond ticks (Windows file time units).
TICKS_PER_SECOND = 10_000_000

# A horizontal rule / code fence / markdown table pipe is not speakable text.
_UNSPEAKABLE = re.compile(r"^[\s\-_=*#>`|~\[\](){}]+$")


@dataclass(slots=True)
class TimedWord:
    """One spoken word and the moment it starts."""

    word: str
    start: float
    duration: float

    def as_dict(self) -> dict[str, Any]:
        return {"word": self.word, "start": round(self.start, 3), "duration": round(self.duration, 3)}


def _ticks_to_seconds(ticks: Any) -> float:
    try:
        return float(ticks) / TICKS_PER_SECOND
    except (TypeError, ValueError):
        return 0.0


def align_words_to_text(
    text: str, boundary_times: list[tuple[str, float, float]]
) -> list[TimedWord]:
    """Project TTS boundary strings onto the reader's own word tokens.

    The speech engine may normalise or split words differently from the source
    text ("$12" -> "twelve dollars", "e.g." -> "e g"). Highlighting needs one
    entry per *visible* token, in reading order, so boundaries are matched
    forward against the source tokens instead of being used verbatim.

    A boundary that cannot be matched is skipped rather than shifting every
    later word; unmatched source tokens inherit the current playback position.
    """
    tokens = [
        (match.start(), match.group(0))
        for match in re.finditer(r"[^\s]+", text)
        if match.group(0) and not _UNSPEAKABLE.match(match.group(0))
    ]
    if not tokens:
        return []

    out: list[TimedWord] = []
    cursor = 0
    last_start = 0.0

    for raw_word, start, duration in boundary_times:
        wanted = re.sub(r"[^\w']+", "", raw_word).casefold()
        if not wanted:
            continue
        matched_at = -1
        for index in range(cursor, len(tokens)):
            candidate = re.sub(r"[^\w']+", "", tokens[index][1]).casefold()
            if candidate == wanted:
                matched_at = index
                break
            # Partial match: a boundary word may span tokens ("24/7" -> 24, 7).
            if wanted.startswith(candidate) and candidate:
                matched_at = index
                break
        if matched_at < 0:
            continue
        for index in range(cursor, matched_at):
            out.append(TimedWord(tokens[index][1], last_start, max(0.0, start - last_start)))
        out.append(TimedWord(tokens[matched_at][1], start, duration))
        last_start = start
        cursor = matched_at + 1

    # Trailing tokens the engine never reported: hold them at the last position.
    for index in range(cursor, len(tokens)):
        out.append(TimedWord(tokens[index][1], last_start, 0.0))

    # Sort defensively so the client can walk the list monotonically.
    out.sort(key=lambda item: item.start)
    return out


async def synthesize_with_word_timings(
    text: str, *, voice: str | None = None, speed: float | None = None
) -> dict[str, Any]:
    """Return base64 audio plus per-word timings for ``text``.

    Raises ``VoiceProviderError`` when the configured provider cannot synthesise
    the text at all; a provider that simply has no boundary events is *not* an
    error, it just yields ``words == []``.
    """
    boundaries: list[tuple[str, float, float]] = []

    # Edge is the only built-in adapter that reports WordBoundary events, and it
    # needs ``boundary="WordBoundary"`` to emit them at all.
    from deeptutor.services.config.provider_runtime import resolve_tts_runtime_config

    config = resolve_tts_runtime_config()
    provider = (config.provider_name or "").lower()
    if provider in {"", "edge", "edge_tts", "microsoft_edge"}:
        from deeptutor.services.voice.adapters.edge import EDGE_DEFAULT_VOICE, edge_rate

        try:
            import edge_tts
        except ImportError:
            edge_tts = None
        if edge_tts is not None:
            communicate = edge_tts.Communicate(
                text,
                voice or config.voice or EDGE_DEFAULT_VOICE,
                rate=edge_rate(speed if speed is not None else config.speed),
                boundary="WordBoundary",
            )
            audio = bytearray()
            try:
                async for chunk in communicate.stream():
                    kind = chunk.get("type")
                    if kind == "audio":
                        audio += chunk["data"]
                    elif kind == "WordBoundary":
                        boundaries.append(
                            (
                                str(chunk.get("text", "")),
                                _ticks_to_seconds(chunk.get("offset")),
                                _ticks_to_seconds(chunk.get("duration")),
                            )
                        )
            except Exception as exc:  # edge-tts raises its own and aiohttp errors
                raise VoiceProviderError(
                    f"Edge TTS request failed: {type(exc).__name__}."
                ) from exc
            if audio:
                words = align_words_to_text(text, boundaries)
                return {
                    "audio_base64": base64.b64encode(bytes(audio)).decode("ascii"),
                    "mime": "audio/mpeg",
                    "words": [word.as_dict() for word in words],
                    "timed": bool(words),
                }

    # Any other configured provider: plain audio, no timings.
    audio, content_type = await synthesize_speech(text)
    from deeptutor.services.voice.audio import _parse_pcm_content_type, _pcm16_to_wav

    pcm = _parse_pcm_content_type(content_type)
    if pcm:
        audio = _pcm16_to_wav(audio, sample_rate=pcm[0], channels=pcm[1])
        content_type = "audio/wav"
    return {
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "mime": content_type,
        "words": [],
        "timed": False,
    }


__all__ = [
    "TICKS_PER_SECOND",
    "TimedWord",
    "align_words_to_text",
    "synthesize_with_word_timings",
]
