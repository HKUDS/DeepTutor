"""Native Volcengine (Doubao / Seed-TTS) speech synthesis adapter.

Volcengine's speech services are not OpenAI-compatible: they authenticate with
``X-Api-Key`` (new console) or an ``X-Api-App-Id`` + ``X-Api-Access-Key`` pair
(legacy console), select the model version with an ``X-Api-Resource-Id`` header
rather than a request-body ``model``, and answer with a stream of JSON documents
whose ``data`` fields carry base64 audio.

The adapter therefore speaks the **V3 "HTTP Chunked 单向流式"** interface
(``POST /api/v3/tts/unidirectional``), which is the only interface that serves
the 2.0 voices (``*_uranus_bigtts``); the older ``/api/v1/tts`` endpoint rejects
them outright. The whole response is consumed and concatenated here so the
adapter keeps DeepTutor's ``(audio_bytes, content_type)`` contract — nothing
downstream needs to know the provider streams.

Docs: https://www.volcengine.com/docs/6561/1598757
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any
from urllib.parse import urlsplit
import uuid

import httpx

from deeptutor.services.voice.base import (
    BaseTTSAdapter,
    VoiceProviderError,
    VoiceProviderHTTPError,
)
from deeptutor.services.voice.config import TTSConfig

logger = logging.getLogger(__name__)

# The documented endpoint for one-shot text in, streamed audio out.
DEFAULT_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
_ENDPOINT_PATH = "/api/v3/tts/unidirectional"

# ``X-Api-Resource-Id`` picks the service version *and* the billing SKU. The
# resource id has to match the voice family — ``*_uranus_bigtts`` voices are
# 2.0 and only answer on ``seed-tts-2.0`` — otherwise the service replies
# `55000000 resource ID is mismatched`.
DEFAULT_RESOURCE_ID = "seed-tts-2.0"
# Prefixes that identify a documented resource id, so a model picked in the
# catalog can stand in for one.
_RESOURCE_ID_PREFIXES = ("seed-tts-", "seed-icl-")

# A finished synthesis is reported with this in-body code; anything else that
# is not 0 is an error.
_SUCCESS_CODE = 20000000
_AUDIO_CHUNK_CODE = 0

DEFAULT_SAMPLE_RATE = 24000

# ``response_format`` -> ``req_params.audio_params.format``. The service streams
# a fresh RIFF header with every wav chunk, which a concatenated body cannot
# carry, so wav is requested as raw PCM; the caller wraps it back into a
# container (see ``api/routers/voice.py``).
_REQUEST_FORMATS = {
    "mp3": "mp3",
    "opus": "ogg_opus",
    "ogg_opus": "ogg_opus",
    "pcm": "pcm",
    "wav": "pcm",
}

# Reported for raw PCM so the HTTP route can wrap it into a playable
# container; the rate and channel count have to match what the request asked
# the service for (16-bit mono).
_PCM_CONTENT_TYPE = f"audio/pcm;rate={DEFAULT_SAMPLE_RATE};channels=1"
_RESPONSE_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "ogg_opus": "audio/opus",
    "pcm": _PCM_CONTENT_TYPE,
    # wav was requested as PCM (see _REQUEST_FORMATS).
    "wav": _PCM_CONTENT_TYPE,
}

# A credential on either console flavour.
_LEGACY_AUTH_HEADERS = ("X-Api-App-Id", "X-Api-Access-Key")


def _endpoint(base_url: str) -> str:
    """Resolve the request URL from the configured base URL.

    The catalog's prefill is the full documented endpoint and is used verbatim,
    as is any other URL that already carries a path (e.g. the ``/sse`` variant).
    A bare origin gets the documented path appended.
    """
    base = (base_url or "").strip()
    if not base:
        raise VoiceProviderError("No endpoint URL configured for TTS.")
    head, sep, query = base.partition("?")
    if "/tts/" in head or urlsplit(head).path.strip("/"):
        return base
    joined = f"{head.rstrip('/')}{_ENDPOINT_PATH}"
    return f"{joined}?{query}" if sep else joined


def _header_value(headers: dict[str, str], name: str) -> str:
    """Case-insensitive lookup, because header names reach us from user JSON."""
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == wanted:
            return str(value)
    return ""


def _resource_id(config: TTSConfig) -> str:
    """Pick the ``X-Api-Resource-Id`` value.

    An explicit ``resource_id`` wins; otherwise a catalog model that names a
    documented resource id is used as-is, so switching the model in Settings is
    enough to move between the 1.0 and 2.0 voice families. The pinned default
    keeps a free-text model label from being sent as a resource id.
    """
    explicit = (config.resource_id or "").strip()
    if explicit:
        return explicit
    model = (config.model or "").strip()
    if model.startswith(_RESOURCE_ID_PREFIXES):
        return model
    return DEFAULT_RESOURCE_ID


def _request_format(response_format: str) -> str:
    """Map DeepTutor's output format onto the service's audio encoding."""
    fmt = (response_format or "mp3").strip().lower()
    try:
        return _REQUEST_FORMATS[fmt]
    except KeyError:
        raise VoiceProviderError(
            f"Volcengine TTS cannot produce `{fmt}` audio; use mp3, opus, pcm or wav."
        ) from None


def _response_content_type(response_format: str) -> str:
    return _RESPONSE_CONTENT_TYPES.get((response_format or "mp3").strip().lower(), "audio/mpeg")


def _speech_rate(speed: float | None) -> int:
    """Convert an OpenAI-style speed multiplier into ``speech_rate``.

    The service takes [-50, 100] where -50 is 0.5x, 0 is 1x and 100 is 2x, so
    the mapping is linear in ``speed - 1``. Out-of-range requests are clamped
    rather than rejected; 1x is reported as 0 and omitted from the body.
    """
    if speed is None:
        return 0
    try:
        scaled = round((float(speed) - 1.0) * 100)
    except (TypeError, ValueError):
        return 0
    return max(-50, min(100, scaled))


def _has_credentials(config: TTSConfig) -> bool:
    if (config.api_key or "").strip():
        return True
    if _header_value(config.extra_headers, "X-Api-Key"):
        return True
    return any(_header_value(config.extra_headers, name) for name in _LEGACY_AUTH_HEADERS)


def _build_headers(config: TTSConfig) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Api-Resource-Id": _resource_id(config),
        "X-Api-Request-Id": str(uuid.uuid4()),
    }
    if (config.api_key or "").strip():
        headers["X-Api-Key"] = config.api_key.strip()
    # Merged last so an operator can override the resource id, or supply the
    # legacy console's App ID / Access Key pair, from Extra Headers.
    headers.update(config.extra_headers or {})
    return headers


def _build_payload(text: str, config: TTSConfig, audio_format: str) -> dict[str, Any]:
    audio_params: dict[str, Any] = {
        "format": audio_format,
        "sample_rate": DEFAULT_SAMPLE_RATE,
    }
    rate = _speech_rate(config.speed)
    if rate:
        audio_params["speech_rate"] = rate
    # ``namespace`` and ``req_params.model`` are omitted deliberately: the
    # latter only applies to voice-cloning 2.0 (``seed-icl-2.0``) and would be
    # rejected or filtered for a plain 2.0 voice, and the former defaults to
    # the documented value.
    return {
        "user": {"uid": "deeptutor"},
        "req_params": {
            "text": text,
            "speaker": config.voice,
            "audio_params": audio_params,
        },
    }


def _drain_objects(buffer: str) -> tuple[list[dict[str, Any]], str]:
    """Pull the complete JSON objects out of a partly-received stream buffer.

    Returns the objects found and whatever tail is still incomplete. Scanning
    for ``{`` rather than splitting on newlines keeps this working for both the
    chunked body (concatenated documents) and the SSE variant (``data: {...}``
    lines).
    """
    objects: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = buffer.find("{", index)
        if start < 0:
            return objects, ""
        try:
            value, end = decoder.raw_decode(buffer, start)
        except ValueError:
            return objects, buffer[start:]
        index = end
        if isinstance(value, dict):
            objects.append(value)


def _log_id(response: httpx.Response) -> str:
    value = (response.headers.get("X-Tt-Logid") or "").strip()
    return f" (X-Tt-Logid: {value})" if value else ""


def _error_hint(code: int | str) -> str:
    """Attach the most likely cause to Volcengine's opaque status codes."""
    text = str(code)
    if text == "45000000":
        return (
            " The voice is probably not activated for this account — order it in the"
            " Volcengine console. The same code also covers a concurrency quota."
        )
    if text == "55000000":
        return (
            " The resource id and the voice family have to match:"
            " `seed-tts-2.0` serves the 2.0 voices (e.g. `*_uranus_bigtts`),"
            " `seed-tts-1.0` the 1.0 voices."
        )
    if text == "40402003":
        return " The text exceeded the service's per-request limit; send it in shorter parts."
    return ""


class VolcengineTTSAdapter(BaseTTSAdapter):
    """Synthesize with Volcengine's V3 one-way streaming HTTP interface.

    The stream is consumed to completion so the caller still receives one
    ``(audio_bytes, content_type)`` pair.
    """

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        if not config.base_url:
            raise VoiceProviderError("No endpoint URL configured for TTS.")
        if not (config.voice or "").strip():
            raise VoiceProviderError("No Volcengine voice (speaker) configured for TTS.")
        if not _has_credentials(config):
            raise VoiceProviderError(
                "No Volcengine credentials configured: set the API key, or supply"
                " X-Api-App-Id and X-Api-Access-Key as extra headers."
            )

        url = _endpoint(config.base_url)
        audio_format = _request_format(config.response_format)
        headers = _build_headers(config)
        payload = _build_payload(text, config, audio_format)

        logger.debug(
            "Volcengine TTS synthesize url=%s resource=%s voice=%s fmt=%s chars=%d",
            url,
            headers["X-Api-Resource-Id"],
            config.voice,
            audio_format,
            len(text),
        )

        audio: list[bytes] = []
        buffer = ""
        try:
            # The body is JSON, so it decodes as UTF-8 whatever content type the
            # service reports for the stream.
            async with httpx.AsyncClient(
                timeout=config.request_timeout, default_encoding="utf-8"
            ) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", errors="replace")
                        raise VoiceProviderHTTPError(
                            f"Volcengine TTS failed with HTTP {resp.status_code}"
                            f"{_log_id(resp)}: {body.strip()[:400]}",
                            status_code=resp.status_code,
                            body=body,
                        )
                    async for chunk in resp.aiter_text():
                        buffer += chunk
                        objects, buffer = _drain_objects(buffer)
                        self._collect(objects, audio)
        except VoiceProviderHTTPError:
            raise
        except httpx.HTTPError as exc:
            detail = str(exc) or exc.__class__.__name__
            raise VoiceProviderError(f"Volcengine TTS request error: {detail}") from exc
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise VoiceProviderError(
                f"Volcengine TTS returned an unreadable audio chunk: {exc}"
            ) from exc

        objects, _ = _drain_objects(buffer)
        self._collect(objects, audio)

        if not audio:
            raise VoiceProviderError("Volcengine TTS returned empty audio.")
        return b"".join(audio), _response_content_type(config.response_format)

    @staticmethod
    def _collect(objects: list[dict[str, Any]], audio: list[bytes]) -> None:
        """Append the base64 audio carried by one batch of stream documents."""
        for obj in objects:
            raw_code = obj.get("code")
            if raw_code == _SUCCESS_CODE:
                continue
            if raw_code not in (None, _AUDIO_CHUNK_CODE):
                message = str(obj.get("message") or "no detail provided")
                raise VoiceProviderError(
                    f"Volcengine TTS failed ({raw_code}): {message}" + _error_hint(raw_code)
                )
            data = obj.get("data")
            if isinstance(data, str) and data:
                audio.append(base64.b64decode(data))


__all__ = ["VolcengineTTSAdapter", "DEFAULT_ENDPOINT", "DEFAULT_RESOURCE_ID"]
