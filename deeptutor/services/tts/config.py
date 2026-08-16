from __future__ import annotations

"""TTS configuration loading and defaults."""

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
from typing import Any

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


@dataclass
class TTSConfig:
    """Runtime configuration for text-to-speech providers.

    Attributes:
        provider: TTS provider name, one of ``dashscope``, ``openai``, or ``edge``.
        model: Provider-specific model name.
        voice: Explicit voice override.
        voices: Language-to-voice mapping, for example ``{"zh": "...", "en": "..."}``.
        api_key: Provider API key when required.
        base_url: Optional custom API endpoint for compatible providers.
    """

    provider: str = "dashscope"
    model: str = ""
    voice: str = ""
    voices: dict[str, str] = field(default_factory=dict)
    api_key: str = ""
    base_url: str = ""


def _settings_file() -> Path:
    """Return the TTS settings file path."""
    return get_path_service().get_settings_file("tts")


def _read_json_file(path: Path) -> dict[str, Any]:
    """Read a JSON file safely.

    Args:
        path: JSON file path.

    Returns:
        Parsed dictionary, or an empty dict when unavailable/invalid.
    """
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to parse JSON config: %s", path, exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_provider(value: str | None) -> str:
    """Normalize provider aliases.

    Args:
        value: Raw provider value.

    Returns:
        Canonical provider name.
    """
    provider = (value or "").strip().lower()
    alias_map = {
        "azure": "openai",
        "azure_openai": "openai",
        "openai-compatible": "openai",
        "openai_compatible": "openai",
        "ms": "edge",
        "edge_tts": "edge",
    }
    normalized = alias_map.get(provider, provider)
    if normalized in {"dashscope", "openai", "edge"}:
        return normalized
    return "dashscope"


def _load_default_from_model_catalog() -> TTSConfig:
    """Build a default TTS config from model catalog active LLM profile.

    Returns:
        Baseline TTS config inferred from ``model_catalog.json``.
    """
    catalog = _read_json_file(get_path_service().get_settings_file("model_catalog"))
    services = catalog.get("services") if isinstance(catalog, dict) else {}
    llm_service = services.get("llm") if isinstance(services, dict) else {}
    profiles = llm_service.get("profiles") if isinstance(llm_service, dict) else []
    active_profile_id = (
        llm_service.get("active_profile_id") if isinstance(llm_service, dict) else None
    )

    profile: dict[str, Any] = {}
    if isinstance(profiles, list):
        for item in profiles:
            if isinstance(item, dict) and item.get("id") == active_profile_id:
                profile = item
                break
        if not profile:
            for item in profiles:
                if isinstance(item, dict):
                    profile = item
                    break

    binding = _normalize_provider(str(profile.get("binding") or "")) if profile else "dashscope"

    if binding == "openai":
        return TTSConfig(
            provider="openai",
            model="tts-1",
            voices={"zh": "alloy", "en": "nova"},
            api_key=str(profile.get("api_key") or ""),
            base_url=str(profile.get("base_url") or "https://api.openai.com/v1"),
        )

    if binding == "edge":
        return TTSConfig(
            provider="edge",
            model="",
            voices={"zh": "zh-CN-XiaoxiaoNeural", "en": "en-US-JennyNeural"},
            api_key="",
            base_url="",
        )

    return TTSConfig(
        provider="dashscope",
        model="cosyvoice-v3-flash",
        voices={"zh": "longxiaochun_v3", "en": "loongbella_v3"},
        api_key=str(profile.get("api_key") or ""),
        base_url=str(profile.get("base_url") or ""),
    )


def _resolve_api_key_with_fallback(config: TTSConfig) -> str:
    """Resolve API key with fallback ordering.

    Resolution order follows project requirements:
    ``tts.json`` -> ``model_catalog.json`` (already included in defaults) -> environment.

    Args:
        config: Current merged config.

    Returns:
        Resolved API key string.
    """
    if config.api_key:
        return config.api_key

    env_name = "DASHSCOPE_API_KEY" if config.provider == "dashscope" else "OPENAI_API_KEY"
    return os.environ.get(env_name, "") if config.provider in {"dashscope", "openai"} else ""


def load_tts_config() -> TTSConfig:
    """Load TTS configuration from settings with provider-aware defaults.

    Returns:
        Resolved ``TTSConfig`` instance.
    """
    defaults = _load_default_from_model_catalog()
    raw = _read_json_file(_settings_file())

    provider = _normalize_provider(str(raw.get("provider") or defaults.provider))
    model = str(raw.get("model") or defaults.model)
    voice = str(raw.get("voice") or "")
    base_url = str(raw.get("base_url") or defaults.base_url)

    voices_payload = raw.get("voices", defaults.voices)
    voices: dict[str, str] = {}
    if isinstance(voices_payload, dict):
        voices = {
            str(language).strip().lower(): str(v)
            for language, v in voices_payload.items()
            if str(language).strip() and str(v).strip()
        }

    config = TTSConfig(
        provider=provider,
        model=model,
        voice=voice,
        voices=voices or defaults.voices,
        api_key=str(raw.get("api_key") or defaults.api_key),
        base_url=base_url,
    )
    config.api_key = _resolve_api_key_with_fallback(config)
    return config


__all__ = ["TTSConfig", "load_tts_config"]
