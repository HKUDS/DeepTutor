"""Provider timestamps must remain finite before media timeline construction."""

from dataclasses import asdict
import json
import math
from typing import Any

import httpx
import pytest

from deeptutor.reading.ingestion import _clock, _rebase_cues, build_transcript_segments
from deeptutor.services.voice.adapters.openai_compat import OpenAICompatSTTAdapter, _parse_cues
from deeptutor.services.voice.config import STTConfig


@pytest.mark.parametrize("field", ["start", "end"])
@pytest.mark.parametrize(
    "value",
    ["NaN", "Infinity", "-Infinity", "1e10000", 10**400],
    ids=["nan", "positive-infinity", "negative-infinity", "overflowing-exponent", "giant-integer"],
)
def test_nonfinite_provider_timestamps_are_ignored(field: str, value: Any) -> None:
    """Numeric strings are accepted only when they represent finite seconds."""
    segment = {"start": "1", "end": "5", "text": "Invalid timing"}
    segment[field] = value
    response = httpx.Response(200, json={"segments": [segment]})
    assert _parse_cues(response) == []


@pytest.mark.parametrize(
    "start,end",
    [("0", "0"), ("1.25", "2.5"), ("1e2", "2e2"), (10.0, 20.0)],
)
def test_finite_timestamps_keep_their_original_precision(start: Any, end: Any) -> None:
    """Keep finite strings, numeric values, and zero-length spans supported."""
    response = httpx.Response(
        200, json={"segments": [{"start": start, "end": end, "text": "Keep me"}]}
    )
    cues = _parse_cues(response)
    assert len(cues) == 1
    assert (cues[0].start_seconds, cues[0].end_seconds) == (float(start), float(end))
    assert cues[0].timed
    json.dumps([asdict(cue) for cue in cues], allow_nan=False)


def test_invalid_neighbors_do_not_remove_valid_provider_segments() -> None:
    """Keep useful transcript rows rather than discarding an entire response."""
    response = httpx.Response(
        200,
        json={
            "segments": [
                {"start": "Infinity", "end": "Infinity", "text": "Bad first"},
                {"start": "1.25", "end": "2.5", "text": "First useful sentence."},
                {"start": "3", "end": "NaN", "text": "Bad middle"},
                {"start": 10**400, "end": 10**401, "text": "Bad giant integer"},
                {"start": "30", "end": "35", "text": "Second useful sentence."},
            ]
        },
    )
    cues = _parse_cues(response)
    assert [cue.text for cue in cues] == [
        "First useful sentence.",
        "Second useful sentence.",
    ]
    segments = build_transcript_segments(_rebase_cues(cues, 60.0, 120.0))
    assert [_clock(row.start_seconds) for row in segments] == ["01:01", "01:30"]
    json.dumps([asdict(row) for row in segments], allow_nan=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["Infinity", 10**400], ids=["infinity", "giant-integer"])
async def test_invalid_verbose_timing_falls_back_before_building_media_outline(
    monkeypatch: pytest.MonkeyPatch,
    invalid: Any,
) -> None:
    """The actual adapter fallback must yield a renderable, finite media span."""
    formats: list[str] = []

    async def post(_client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        response_format = kwargs["data"]["response_format"]
        formats.append(response_format)
        data = (
            {"segments": [{"start": invalid, "end": invalid, "text": "Bad timing"}]}
            if response_format == "verbose_json"
            else {"text": "Recovered transcript."}
        )
        return httpx.Response(200, json=data, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    cues = await OpenAICompatSTTAdapter().transcribe_cues(
        b"synthetic audio",
        STTConfig(model="whisper-test", base_url="https://speech.example/v1"),
    )
    segments = build_transcript_segments(_rebase_cues(cues, 60.0, 120.0))
    # This is the real clock/outline path that used to raise OverflowError.
    assert [_clock(row.start_seconds) for row in segments] == ["01:00"]
    assert formats == ["verbose_json", "json"]
    assert len(cues) == 1 and not cues[0].timed
    assert [(row.start_seconds, row.end_seconds) for row in segments] == [(60.0, 120.0)]
    assert all(
        math.isfinite(value) for row in segments for value in (row.start_seconds, row.end_seconds)
    )
    json.dumps([asdict(row) for row in segments], allow_nan=False)


def test_numeric_exponent_overflow_is_not_a_renderable_timestamp() -> None:
    """An otherwise valid JSON number can exceed the float range on decoding."""
    response = httpx.Response(
        200,
        content=b'{"segments":[{"start":1e10000,"end":1e10000,"text":"Too large"}]}',
        headers={"content-type": "application/json"},
    )
    assert _parse_cues(response) == []
