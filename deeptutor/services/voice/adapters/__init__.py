"""Voice adapter registry.

Adapters are stateless singletons keyed by the ``adapter`` field on the
resolved config. The OpenAI-compatible pair covers OpenAI, Groq, SiliconFlow,
OpenRouter, Azure OpenAI and local vLLM/LM Studio; add bespoke providers
(DashScope native, ElevenLabs, Gemini, Deepgram) by registering new keys here.
"""

from __future__ import annotations

from deeptutor.services.voice.adapters.openai_compat import (
    OpenAICompatSTTAdapter,
    OpenAICompatTTSAdapter,
    OpenRouterTTSAdapter,
)
from deeptutor.services.voice.base import BaseSTTAdapter, BaseTTSAdapter, VoiceProviderError

TTS_ADAPTERS: dict[str, BaseTTSAdapter] = {
    "openai_compat": OpenAICompatTTSAdapter(),
    "openrouter_tts": OpenRouterTTSAdapter(),
}

STT_ADAPTERS: dict[str, BaseSTTAdapter] = {
    "openai_compat": OpenAICompatSTTAdapter(),
}


def get_tts_adapter(name: str) -> BaseTTSAdapter:
    adapter = TTS_ADAPTERS.get(name or "openai_compat")
    if adapter is None:
        raise VoiceProviderError(f"Unsupported TTS adapter: {name!r}")
    return adapter


def get_stt_adapter(name: str) -> BaseSTTAdapter:
    adapter = STT_ADAPTERS.get(name or "openai_compat")
    if adapter is None:
        raise VoiceProviderError(f"Unsupported STT adapter: {name!r}")
    return adapter


__all__ = [
    "TTS_ADAPTERS",
    "STT_ADAPTERS",
    "get_tts_adapter",
    "get_stt_adapter",
]
