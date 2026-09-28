"""Doubao Speech HTTP v3, separate from Volcengine Ark.

Wire references (checked 2026-09-17):
https://www.volcengine.com/docs/6561/1598757 (TTS SSE)
https://www.volcengine.com/docs/6561/1631584 (ASR Base64 uploads)
https://www.volcengine.com/docs/6561/2608628 (ASR languages/timestamps)
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import math
from typing import Any
from uuid import uuid4

import httpx

from ..audio import normalize_wav, pcm_to_wav
from ..base import (
    BaseSTTAdapter,
    BaseTTSAdapter,
    TranscriptCue,
    VoiceProviderError,
    join_audio_path,
)
from ..config import STTConfig, TTSConfig


def _headers(config: TTSConfig | STTConfig, resource: str) -> dict[str, str]:
    if not config.api_key or config.api_key == "***":
        raise VoiceProviderError("Configure a Volcengine Speech API key or legacy access token.")
    headers = {
        **config.extra_headers,
        "Content-Type": "application/json",
        "X-Api-Resource-Id": resource,
        "X-Api-Request-Id": str(uuid4()),
    }
    # ASR and TTS legacy protocols deliberately spell the application header differently.
    if config.app_id:
        headers["X-Api-App-Id" if isinstance(config, TTSConfig) else "X-Api-App-Key"] = (
            config.app_id
        )
        headers["X-Api-Access-Key"] = config.api_key
    else:
        headers["X-Api-Key"] = config.api_key
    return headers


def _failure(code: object, config: TTSConfig | STTConfig) -> VoiceProviderError:
    code = str(code) if str(code).isdigit() else "invalid status"
    # Do not echo provider response bodies: gateways can echo credentials or input text.
    return VoiceProviderError(
        f"Volcengine Speech request failed (code {code}). "
        "Check the Speech credentials, resource entitlement, model and voice."
    )


class VolcengineTTSAdapter(BaseTTSAdapter):
    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        if not config.voice:
            raise VoiceProviderError("Choose a Volcengine speaker ID for this model version.")
        fmt = config.response_format or "mp3"
        if fmt not in {"mp3", "wav", "pcm", "ogg_opus"}:
            raise VoiceProviderError("Volcengine TTS supports mp3, wav, pcm, or ogg_opus.")
        if config.sample_rate not in {8000, 16000, 22050, 24000, 32000, 44100, 48000}:
            raise VoiceProviderError("Unsupported Volcengine TTS sample rate.")
        params = {"format": "pcm" if fmt == "wav" else fmt, "sample_rate": config.sample_rate}
        if config.speed is not None:
            if not math.isfinite(config.speed) or not 0.5 <= config.speed <= 2:
                raise VoiceProviderError("Volcengine speech speed must be between 0.5 and 2.")
            params["speech_rate"] = round((config.speed - 1) * 100)
        req = {"text": text, "speaker": config.voice, "audio_params": params}
        additions: dict[str, Any] = {}
        if config.language:
            additions["explicit_language"] = config.language
        if config.instructions:
            additions["context_texts"] = [config.instructions]
        if additions:
            req["additions"] = json.dumps(additions, ensure_ascii=False)
        headers = _headers(config, config.resource_id or config.model)
        url = join_audio_path(config.base_url, "tts/unidirectional/sse")
        chunks: list[bytes] = []
        complete = False
        try:
            async with asyncio.timeout(config.request_timeout):
                async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                    async with client.stream(
                        "POST",
                        url,
                        headers=headers,
                        json={"user": {"uid": "deeptutor"}, "req_params": req},
                    ) as response:
                        if response.status_code >= 400:
                            raise _failure(response.status_code, config)
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            event = json.loads(line[5:].strip())
                            if not isinstance(event, dict):
                                raise VoiceProviderError("Malformed Volcengine TTS event.")
                            code = event.get("code")
                            if code not in (0, 20000000):
                                raise _failure(code, config)
                            if event.get("data"):
                                chunks.append(base64.b64decode(event["data"], validate=True))
                            if code == 20000000:
                                complete = True
                                break
        except (httpx.HTTPError, TimeoutError) as exc:
            raise VoiceProviderError("Volcengine TTS connection failed or timed out.") from exc
        except (ValueError, TypeError, binascii.Error) as exc:
            raise VoiceProviderError("Malformed Volcengine TTS audio response.") from exc
        if not complete:
            raise VoiceProviderError("Volcengine TTS stream ended before synthesis completed.")
        audio = b"".join(chunks)
        if not audio:
            raise VoiceProviderError("Volcengine TTS returned empty audio.")
        if fmt == "wav":
            return pcm_to_wav(audio, config.sample_rate), "audio/wav"
        return audio, {
            "mp3": "audio/mpeg",
            "pcm": f"audio/pcm;rate={config.sample_rate};channels=1",
            "ogg_opus": "audio/ogg",
        }[fmt]


class VolcengineSTTAdapter(BaseSTTAdapter):
    async def _recognize(self, audio: bytes, config: STTConfig) -> dict:
        if not audio:
            raise VoiceProviderError("No audio data to transcribe.")
        headers = _headers(config, config.resource_id or "volc.bigasr.auc_turbo")
        headers["X-Api-Sequence"] = "-1"
        audio = await normalize_wav(audio)
        payload: dict[str, Any] = {
            "user": {"uid": "deeptutor"},
            "audio": {
                "data": base64.b64encode(audio).decode("ascii"),
                "format": "wav",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
            },
            "request": {"model_name": config.model, "show_utterances": True},
        }
        if config.language:
            payload["audio"]["language"] = config.language
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                response = await client.post(
                    join_audio_path(config.base_url, "auc/bigmodel/recognize/flash"),
                    headers=headers,
                    json=payload,
                )
            if response.status_code >= 400:
                raise _failure(response.status_code, config)
            code = response.headers.get("X-Api-Status-Code")
            if code == "20000003":  # Valid silent audio: an empty transcript is success.
                return {"text": "", "utterances": []}
            if code != "20000000":
                raise _failure(code or "missing status", config)
            data = response.json()
        except (httpx.HTTPError, TimeoutError) as exc:
            raise VoiceProviderError("Volcengine STT connection failed or timed out.") from exc
        except ValueError as exc:
            raise VoiceProviderError("Malformed Volcengine STT response.") from exc
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise VoiceProviderError("Volcengine STT response has no transcript.")
        return result

    async def transcribe(
        self,
        audio: bytes,
        config: STTConfig,
        *,
        filename="audio.webm",
        content_type="application/octet-stream",
    ) -> str:
        return (await self._recognize(audio, config))["text"].strip()

    async def transcribe_cues(
        self,
        audio: bytes,
        config: STTConfig,
        *,
        filename="audio.webm",
        content_type="application/octet-stream",
    ) -> list[TranscriptCue]:
        result = await self._recognize(audio, config)
        cues = []
        for row in result.get("utterances") or []:
            if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                continue
            try:
                start, end = float(row["start_time"]) / 1000, float(row["end_time"]) / 1000
            except (KeyError, ValueError, TypeError):
                continue
            if math.isfinite(start) and math.isfinite(end) and 0 <= start <= end:
                cues.append(TranscriptCue(start, end, row["text"]))
        return cues or (
            [TranscriptCue(0, 0, result["text"].strip(), timed=False)]
            if result["text"].strip()
            else []
        )
