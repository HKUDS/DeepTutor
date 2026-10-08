"""Live voice discovery. No bundled voice IDs, guessed endpoints or static fallback.

MiniMax: https://platform.minimax.io/docs/api-reference/voice-management-get
DashScope: https://help.aliyun.com/en/model-studio/voice-clone-design-http-api
Only the selected connection is contacted; credentials never leave its host.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from urllib.parse import urlsplit, urlunsplit

import httpx

from deeptutor.services.config.provider_runtime import resolve_tts_runtime_config


class VoiceDiscoveryError(ValueError):
    """A public, credential-free failure message."""


def selected_catalog(catalog: dict, service: str, profile_id: str, model_id: str | None) -> dict:
    snapshot = deepcopy(catalog)
    bucket = snapshot.get("services", {}).get(service, {})
    profile = next((p for p in bucket.get("profiles", []) if p.get("id") == profile_id), None)
    if profile is None or (
        service != "search" and not any(m.get("id") == model_id for m in profile.get("models", []))
    ):
        raise ValueError("The selected service configuration no longer exists.")
    bucket["active_profile_id"], bucket["active_model_id"] = profile_id, model_id
    return snapshot


def discovery_url(base: str, provider: str) -> str:
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise VoiceDiscoveryError("Check the provider URL before fetching voices.")
    path = parsed.path.rstrip("/")
    if provider == "minimax":
        if path.endswith("/t2a_v2"):
            path = path[: -len("/t2a_v2")]
        path += "/get_voice"
    else:
        if path == "/compatible-mode/v1" and (parsed.hostname.endswith(".aliyuncs.com")):
            path = "/api/v1"
        for suffix in (
            "/services/aigc/multimodal-generation/generation",
            "/services/audio/tts/SpeechSynthesizer",
        ):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
        path += "/services/audio/tts/customization"
    return urlunsplit(parsed._replace(path=path, query="", fragment=""))


async def discover_voices(catalog: dict, profile_id: str, model_id: str) -> dict:
    config = resolve_tts_runtime_config(selected_catalog(catalog, "tts", profile_id, model_id))
    provider = config.provider_name
    # A vendor's speech API key is not permission to call its separately signed
    # control plane. Never fabricate a generic /voices API for compatible hosts.
    if provider not in {"minimax", "dashscope"}:
        return {"status": "unsupported", "voices": [], "scope": "none"}
    native = config.model.startswith(("cosyvoice-", "qwen-audio-"))
    qwen_custom = config.model.startswith("qwen") and any(
        x in config.model for x in ("-vc-", "-vd-")
    )
    if provider == "dashscope" and not (native or qwen_custom):
        return {"status": "unsupported", "voices": [], "scope": "none"}
    if not config.api_key or config.api_key == "***":
        raise VoiceDiscoveryError("Enter provider credentials before fetching voices.")
    url = discovery_url(config.base_url, provider)
    headers = {**config.extra_headers, "Authorization": f"Bearer {config.api_key}"}
    voices: dict[str, dict] = {}

    async def post(client, body):
        response = await client.post(url, headers=headers, json=body)
        if response.status_code in (401, 403):
            raise VoiceDiscoveryError(
                "Voice access was denied. Check credentials, region and permissions."
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("code") not in (None, "", 0, "0"):
            raise VoiceDiscoveryError(
                "The provider rejected voice discovery. Check the model and region."
            )
        return data

    def add(identifier, label=None, language=None):
        if not isinstance(identifier, str) or not identifier.strip():
            return
        voices[identifier] = {
            "id": identifier,
            "label": label or identifier,
            **({"languages": [language]} if isinstance(language, str) and language else {}),
        }

    try:
        async with (
            asyncio.timeout(25),
            httpx.AsyncClient(timeout=10, follow_redirects=False) as client,
        ):
            if provider == "minimax":
                data = await post(client, {"voice_type": "all"})
                if data.get("base_resp", {}).get("status_code") != 0:
                    raise VoiceDiscoveryError(
                        "The provider rejected voice discovery. Check credentials and permissions."
                    )
                if not any(
                    isinstance(data.get(k), list)
                    for k in ("system_voice", "voice_cloning", "voice_generation")
                ):
                    raise VoiceDiscoveryError("The provider returned an invalid voice list.")
                for group in ("system_voice", "voice_cloning", "voice_generation"):
                    for row in data.get(group) or []:
                        if isinstance(row, dict):
                            add(row.get("voice_id"), row.get("voice_name"))
                scope = "account"
            else:
                enrollment = "voice-enrollment" if native else "qwen-voice-enrollment"
                seen: set[str] = set()
                for page in range(100):
                    data = await post(
                        client,
                        {
                            "model": enrollment,
                            "input": {
                                "action": "list_voice" if native else "list",
                                "page_index": page,
                                "page_size": 100,
                            },
                        },
                    )
                    rows = data.get("output", {}).get("voice_list")
                    if not isinstance(rows, list):
                        raise VoiceDiscoveryError("The provider returned an invalid voice list.")
                    for row in rows:
                        if not isinstance(row, dict):
                            raise VoiceDiscoveryError(
                                "The provider returned an invalid voice list."
                            )
                        identifier = row.get("voice_id") or row.get("voice")
                        if not isinstance(identifier, str) or identifier in seen:
                            raise VoiceDiscoveryError(
                                "The provider returned an invalid or repeated voice page."
                            )
                        seen.add(identifier)
                        if native:
                            if row.get("status") != "OK":
                                continue
                            detail = await post(
                                client,
                                {
                                    "model": enrollment,
                                    "input": {"action": "query_voice", "voice_id": identifier},
                                },
                            )
                            row = {**row, **detail.get("output", {})}
                        if (
                            row.get("target_model") == config.model
                            and row.get("status", "OK") == "OK"
                        ):
                            add(identifier, language=row.get("language"))
                    if len(rows) < 100:
                        break
                else:
                    raise VoiceDiscoveryError(
                        "The voice list is too large. Please enter a voice ID manually."
                    )
                scope = "custom"
        return {"status": "ready", "scope": scope, "voices": list(voices.values())}
    except VoiceDiscoveryError:
        raise
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError) as exc:
        raise VoiceDiscoveryError(
            "Could not fetch voices. Check the connection and try again."
        ) from exc
