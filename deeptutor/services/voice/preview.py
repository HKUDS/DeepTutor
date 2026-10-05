"""A transient TTS audition: explicit draft selection and no runtime writes."""

from copy import deepcopy

from .adapters import get_tts_adapter
from .audio import _parse_pcm_content_type, _pcm16_to_wav
from .base import VoiceProviderError, VoiceProviderHTTPError, synthesize_with_timeout


def preview_failure_message(error: VoiceProviderError) -> str:
    """Give an actionable diagnosis without echoing upstream text or secrets."""
    if error.public_message:
        return error.public_message
    if isinstance(error, VoiceProviderHTTPError):
        if error.status_code == 401:
            return "Speech authentication failed. Check the API key and its region."
        if error.status_code == 403:
            return "Speech access was denied. Check model and voice permissions and the API key region."
        if error.status_code == 404:
            return "Speech endpoint or model was not found. Check the provider URL and model ID."
        if error.status_code in {400, 422}:
            return "Speech parameters were rejected. Check the model, voice, language and audio format."
        if error.status_code == 429:
            return "Speech quota or rate limit was reached. Check your balance and quota, or retry later."
        if error.status_code >= 500:
            return "The speech provider is temporarily unavailable. Try again later."
    return (
        "Voice preview failed. Check the provider credentials, model, voice, language and format."
    )


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
    audio, content_type = await synthesize_with_timeout(
        get_tts_adapter(config.adapter), text, config
    )
    if not audio:
        raise VoiceProviderError("The provider returned empty audio.")
    pcm = _parse_pcm_content_type(content_type)
    if pcm:
        audio = _pcm16_to_wav(audio, sample_rate=pcm[0], channels=pcm[1])
        content_type = "audio/wav"
    return audio, content_type
