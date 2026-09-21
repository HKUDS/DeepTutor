"""A transient TTS audition: explicit draft selection and no runtime writes."""

from copy import deepcopy

from .adapters import get_tts_adapter
from .audio import _parse_pcm_content_type, _pcm16_to_wav
from .base import VoiceProviderError


async def synthesize_preview(catalog: dict, profile_id: str, model_id: str, text: str):
    from deeptutor.services.config.provider_runtime import resolve_tts_runtime_config

    text = text.strip()
    if not text or len(text) > 500:
        raise ValueError("Enter between 1 and 500 characters of preview text.")
    snapshot = deepcopy(catalog)
    bucket = snapshot.get("services", {}).get("tts", {})
    profile = next((p for p in bucket.get("profiles", []) if p.get("id") == profile_id), None)
    if profile is None or not any(m.get("id") == model_id for m in profile.get("models", [])):
        raise ValueError("The selected speech model no longer exists.")
    bucket["active_profile_id"], bucket["active_model_id"] = profile_id, model_id
    config = resolve_tts_runtime_config(snapshot)
    if config.api_key == "***" or any(v == "***" for v in config.extra_headers.values()):
        raise ValueError("Saved speech credentials were not found. Enter them again.")
    if len(text) > config.max_input_chars:
        raise ValueError(f"This speech model accepts at most {config.max_input_chars} characters.")
    config.request_timeout = min(config.request_timeout, 60)
    audio, content_type = await get_tts_adapter(config.adapter).synthesize(text, config)
    if not audio:
        raise VoiceProviderError("The provider returned empty audio.")
    pcm = _parse_pcm_content_type(content_type)
    if pcm:
        audio = _pcm16_to_wav(audio, sample_rate=pcm[0], channels=pcm[1])
        content_type = "audio/wav"
    return audio, content_type
