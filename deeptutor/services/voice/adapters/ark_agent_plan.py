"""Ark Agent Plan speech, using its dedicated key and /api/v3/plan endpoints.

Wire reference:
https://ark.volcengine.com/region:cn-beijing/docs/agent-plan-personal-voice-model.md
TTS returns newline-delimited JSON rather than Speech's SSE. ASR uses the
documented gzip-compressed, sequenced binary WebSocket protocol. The public
DeepTutor API continues to accept complete recordings and return final text.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import gzip
import io
import json
import logging
import struct
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
import wave
import zlib

import aiohttp

from ..audio import normalize_wav
from ..base import VoiceProviderError
from ..config import STTConfig, TTSConfig
from .volcengine import VolcengineSTTAdapter, VolcengineTTSAdapter

logger = logging.getLogger(__name__)
_ASR_RESOURCE = "volc.seedasr.sauc.duration"
_ASR_PATH = "sauc/bigmodel_nostream"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def _plan_headers(config: TTSConfig | STTConfig, resource: str) -> dict[str, str]:
    if not config.api_key or config.api_key == "***":
        raise VoiceProviderError("Configure an Ark Agent Plan dedicated API key.")
    request_id = str(uuid4())
    return {
        **config.extra_headers,
        "X-Api-Key": config.api_key,
        "X-Api-Resource-Id": resource,
        "X-Api-Request-Id": request_id,
        "X-Api-Connect-Id": request_id,
    }


class ArkAgentPlanTTSAdapter(VolcengineTTSAdapter):
    endpoint_path = "tts/unidirectional"
    event_prefix = ""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        if not config.voice.strip():
            message = "Enter a speaker ID before previewing this speech model."
            raise VoiceProviderError(message, public_message=message)
        return await super().synthesize(text, config)

    def request_headers(self, config: TTSConfig) -> dict[str, str]:
        return {
            **_plan_headers(config, config.resource_id or config.model),
            "Content-Type": "application/json",
        }

    def request_error(self, code: object, config: TTSConfig) -> VoiceProviderError:
        code = str(code) if str(code).isdigit() else "invalid status"
        return VoiceProviderError(
            f"Ark Agent Plan synthesis failed (code {code}). Check the dedicated API key, "
            "speech resource, model and voice settings."
        )


def _asr_url(base: str) -> str:
    parsed = urlsplit(base.strip())
    if (
        parsed.scheme not in {"https", "http", "wss", "ws"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise VoiceProviderError("Ark Agent Plan requires a valid speech provider URL.")
    path = parsed.path.rstrip("/")
    if not path.endswith(("/sauc/bigmodel_nostream", "/sauc/bigmodel_async")):
        path += "/" + _ASR_PATH
    scheme = {"https": "wss", "http": "ws"}.get(parsed.scheme, parsed.scheme)
    return urlunsplit(parsed._replace(scheme=scheme, path=path))


def _request_frame(message_type: int, sequence: int, payload: bytes, *, last=False) -> bytes:
    flags = 3 if last else 1
    serialization = 1 if message_type == 1 else 0
    compressed = gzip.compress(payload)
    header = bytes((0x11, (message_type << 4) | flags, (serialization << 4) | 1, 0))
    return (
        header + struct.pack(">iI", -sequence if last else sequence, len(compressed)) + compressed
    )


def _response_frame(message: bytes) -> tuple[dict, bool]:
    """Validate framing before decoding JSON; never expose upstream error bodies."""
    if len(message) < 4 or message[0] >> 4 != 1:
        raise ValueError("Invalid ASR header")
    offset = (message[0] & 15) * 4
    message_type, flags = message[1] >> 4, message[1] & 15
    serialization, compression = message[2] >> 4, message[2] & 15
    if offset < 4 or offset > len(message) or message_type not in {9, 15}:
        raise ValueError("Unsupported ASR frame")
    if flags & 1:
        if offset + 4 > len(message):
            raise ValueError("Missing ASR sequence")
        sequence = struct.unpack_from(">i", message, offset)[0]
        offset += 4
    else:
        sequence = 0
    if flags & 4:
        offset += 4  # Optional event identifier.
    if message_type == 15:
        if offset + 4 > len(message):
            raise ValueError("Missing ASR error code")
        code = struct.unpack_from(">I", message, offset)[0]
        raise VoiceProviderError(
            f"Ark Agent Plan recognition failed (code {code}). "
            "Check the dedicated API key and speech resource entitlement."
        )
    if offset + 4 > len(message):
        raise ValueError("Missing ASR payload length")
    size = struct.unpack_from(">I", message, offset)[0]
    payload = message[offset + 4 :]
    if len(payload) != size or size > _MAX_RESPONSE_BYTES:
        raise ValueError("Invalid ASR payload length")
    if compression == 1:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
            payload = compressed.read(_MAX_RESPONSE_BYTES + 1)
    elif compression != 0:
        raise ValueError("Unsupported ASR compression")
    if len(payload) > _MAX_RESPONSE_BYTES or serialization != 1:
        raise ValueError("Invalid ASR response encoding")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Invalid ASR response")
    code = data.get("code")
    if code == 20000003:
        data["result"] = {"text": "", "utterances": []}
    elif code not in (None, 0, 1000, 20000000):
        raise VoiceProviderError(
            "Ark Agent Plan rejected recognition. Check the dedicated key and model settings."
        )
    return data, bool(flags & 2) or sequence < 0


class ArkAgentPlanSTTAdapter(VolcengineSTTAdapter):
    """Reuse transcript/timestamp extraction, replacing only the wire transport."""

    async def _recognize(self, audio: bytes, config: STTConfig) -> dict:
        if not audio:
            raise VoiceProviderError("No audio data to transcribe.")
        headers = _plan_headers(config, config.resource_id or _ASR_RESOURCE)
        url = _asr_url(config.base_url)
        try:
            async with asyncio.timeout(config.request_timeout):
                wav_audio = await normalize_wav(audio)
                with wave.open(io.BytesIO(wav_audio)) as wav:
                    pcm = wav.readframes(wav.getnframes())
                if not pcm:
                    raise VoiceProviderError("No audio samples to transcribe.")
                params = {
                    "format": "pcm",
                    "codec": "raw",
                    "rate": 16000,
                    "bits": 16,
                    "channel": 1,
                }
                if config.language:
                    params["language"] = config.language
                payload = {
                    "user": {"uid": "deeptutor"},
                    "audio": params,
                    "request": {
                        "model_name": config.model,
                        "enable_itn": True,
                        "enable_punc": True,
                        "show_utterances": True,
                    },
                }
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        url, headers=headers, max_msg_size=_MAX_RESPONSE_BYTES
                    ) as socket:
                        log_id = socket._response.headers.get("X-Tt-Logid")
                        if log_id:
                            logger.debug("Ark Agent Plan ASR connected; log ID: %s", log_id)
                        await socket.send_bytes(
                            _request_frame(1, 1, json.dumps(payload).encode("utf-8"))
                        )

                        async def send_audio():
                            # 200 ms of mono 16 kHz signed PCM per frame.
                            for offset in range(0, len(pcm), 6400):
                                last = offset + 6400 >= len(pcm)
                                await socket.send_bytes(
                                    _request_frame(
                                        2,
                                        2 + offset // 6400,
                                        pcm[offset : offset + 6400],
                                        last=last,
                                    )
                                )
                                await asyncio.sleep(0)  # Receive results while uploading.

                        sender = asyncio.create_task(send_audio())
                        result = None
                        try:
                            async for message in socket:
                                if message.type != aiohttp.WSMsgType.BINARY:
                                    raise VoiceProviderError(
                                        "Ark Agent Plan ASR connection closed."
                                    )
                                data, final = _response_frame(message.data)
                                candidate = data.get("result")
                                if isinstance(candidate, dict) and isinstance(
                                    candidate.get("text"), str
                                ):
                                    result = candidate
                                if final:
                                    await sender
                                    if result is None:
                                        raise VoiceProviderError(
                                            "Ark Agent Plan ASR returned no transcript."
                                        )
                                    return result
                            # Never return a partial transcript after an interrupted connection.
                            raise VoiceProviderError(
                                "Ark Agent Plan ASR ended before recognition completed."
                            )
                        finally:
                            sender.cancel()
                            with suppress(asyncio.CancelledError):
                                await sender
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise VoiceProviderError(
                "Ark Agent Plan recognition connection failed or timed out."
            ) from exc
        except (ValueError, OSError, EOFError, wave.Error, struct.error, zlib.error) as exc:
            raise VoiceProviderError("Malformed Ark Agent Plan recognition response.") from exc
