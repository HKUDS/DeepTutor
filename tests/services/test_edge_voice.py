"""Edge read-aloud speech: keyless catalog resolution and the edge-tts call, offline."""

import sys
import types

import pytest

from deeptutor.services.config.provider_runtime import TTS_PROVIDERS, resolve_tts_runtime_config
from deeptutor.services.voice import synthesize_speech
from deeptutor.services.voice.adapters.edge import edge_rate
from deeptutor.services.voice.base import VoiceProviderError


def catalog(**model):
    """The connection Settings stores for Edge: no API key."""
    return {
        "version": 1,
        "connections": [{"id": "speech", "provider": "edge"}],
        "services": {
            "tts": {
                "active_profile_id": "p",
                "active_model_id": "m",
                "profiles": [
                    {
                        "id": "p",
                        "provider_ref": {"connection_id": "speech", "binding": "edge"},
                        "models": [{"id": "m", "model": "edge-tts", **model}],
                    }
                ],
            }
        },
    }


@pytest.fixture
def fake_edge(monkeypatch):
    calls = []

    class Communicate:
        def __init__(self, text, voice, *, rate="+0%"):
            calls.append({"text": text, "voice": voice, "rate": rate})

        async def stream(self):
            yield {"type": "SentenceBoundary", "offset": 0, "duration": 1, "text": "hi"}
            yield {"type": "audio", "data": b"ID3"}
            yield {"type": "audio", "data": b"abc"}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Communicate))
    return calls


def test_edge_resolves_without_an_api_key() -> None:
    resolved = resolve_tts_runtime_config(catalog())
    assert resolved.provider_name == resolved.adapter == "edge"
    assert resolved.model == TTS_PROVIDERS["edge"].default_model
    assert resolved.response_format == "mp3"


@pytest.mark.asyncio
async def test_edge_speaks_with_the_configured_voice_and_speed(fake_edge) -> None:
    audio = await synthesize_speech(
        "Hello", catalog=catalog(voice="en-US-AvaNeural", speed=1.25), math_speak=False
    )
    assert audio == (b"ID3abc", "audio/mpeg")
    assert fake_edge == [{"text": "Hello", "voice": "en-US-AvaNeural", "rate": "+25%"}]


@pytest.mark.asyncio
async def test_edge_defaults_to_a_chinese_voice(fake_edge) -> None:
    await synthesize_speech("你好", catalog=catalog(), math_speak=False)
    assert fake_edge[0]["voice"] == "zh-CN-XiaoxiaoNeural"


def test_edge_rate_bounds() -> None:
    assert edge_rate(None) == "+0%"
    assert edge_rate(0.8) == "-20%"
    with pytest.raises(VoiceProviderError):
        edge_rate(3)
