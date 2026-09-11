"""Native Aliyun DashScope voice adapters."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import urlsplit
import uuid

import aiohttp
import httpx

from deeptutor.services.voice.base import (
    BaseSTTAdapter,
    BaseTTSAdapter,
    VoiceProviderError,
    VoiceProviderHTTPError,
    build_auth_headers,
    join_audio_path,
)
from deeptutor.services.voice.config import STTConfig, TTSConfig

_TTS_PATH = "services/aigc/multimodal-generation/generation"
_AUDIO_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/opus",
    "pcm": "audio/pcm",
}


def _provider_error(resp: httpx.Response, action: str) -> None:
    if resp.status_code < 400:
        return
    detail = (resp.text or "").strip()[:400]
    raise VoiceProviderHTTPError(
        f"{action} failed with HTTP {resp.status_code}" + (f": {detail}" if detail else "."),
        status_code=resp.status_code,
        body=resp.text,
    )


def _dashscope_error(data: dict[str, Any], action: str) -> None:
    if data.get("code") not in (None, "", 0, "0") or data.get("success") is False:
        code = data.get("code") or "unknown"
        message = data.get("message") or "no detail provided"
        raise VoiceProviderError(f"{action} failed ({code}): {message}")


class DashScopeTTSAdapter(BaseTTSAdapter):
    """Generate speech with Qwen TTS and download the returned audio URL."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        if not config.base_url:
            raise VoiceProviderError("No endpoint URL configured for TTS.")
        url = join_audio_path(config.base_url, _TTS_PATH)
        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        payload: dict[str, Any] = {
            "model": config.model,
            "input": {"text": text},
        }
        if config.voice:
            payload["input"]["voice"] = config.voice

        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                _provider_error(resp, "DashScope TTS")
                data = self._json_object(resp)
                _dashscope_error(data, "DashScope TTS")
                audio_url = self._audio_url(data)
                audio_resp = await client.get(audio_url)
                _provider_error(audio_resp, "DashScope audio download")
        except (httpx.HTTPError, ValueError) as exc:
            raise VoiceProviderError(f"DashScope TTS request error: {exc}") from exc

        if not audio_resp.content:
            raise VoiceProviderError("DashScope TTS returned empty audio.")
        content_type = audio_resp.headers.get("content-type") or self._url_content_type(
            audio_url, config.response_format
        )
        if not content_type.startswith("audio/"):
            content_type = _AUDIO_CONTENT_TYPES.get(
                (config.response_format or "wav").lower(), "audio/wav"
            )
        return audio_resp.content, content_type

    @staticmethod
    def _json_object(resp: httpx.Response) -> dict[str, Any]:
        data = resp.json()
        if not isinstance(data, dict):
            raise VoiceProviderError("DashScope TTS returned a malformed response.")
        return data

    @staticmethod
    def _audio_url(data: dict[str, Any]) -> str:
        output = data.get("output")
        if isinstance(output, dict):
            audio = output.get("audio")
            if isinstance(audio, dict):
                url = audio.get("url")
                if isinstance(url, str) and url:
                    return url
        raise VoiceProviderError("DashScope TTS response had no audio URL.")

    @staticmethod
    def _url_content_type(url: str, response_format: str) -> str:
        suffix = Path(urlsplit(url).path).suffix.lstrip(".").lower()
        return _AUDIO_CONTENT_TYPES.get(suffix) or _AUDIO_CONTENT_TYPES.get(
            (response_format or "wav").lower(), "audio/wav"
        )


class DashScopeSTTAdapter(BaseSTTAdapter):
    """Transcribe local audio over DashScope's native recognition WebSocket."""

    async def transcribe(
        self,
        audio: bytes,
        config: STTConfig,
        *,
        filename: str = "audio.webm",
        content_type: str = "application/octet-stream",
    ) -> str:
        if not audio:
            raise VoiceProviderError("No audio data to transcribe.")
        wav_audio = await self._prepare_wav(audio, filename, content_type)
        if not wav_audio:
            raise VoiceProviderError("Audio conversion returned an empty file.")
        if not config.api_key:
            raise VoiceProviderError("No API key configured for DashScope STT.")

        timeout = aiohttp.ClientTimeout(total=config.request_timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
                async with session.ws_connect(
                    self._websocket_url(config.base_url),
                    headers={
                        "Authorization": f"Bearer {config.api_key}",
                        **(config.extra_headers or {}),
                    },
                    heartbeat=30,
                ) as websocket:
                    return await self._run_recognition(websocket, wav_audio, config)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise VoiceProviderError(f"DashScope STT request error: {exc}") from exc

    async def _prepare_wav(self, audio: bytes, filename: str, content_type: str) -> bytes:
        source_suffix = self._audio_suffix(filename, content_type)
        if self._is_canonical_wav(audio):
            return audio
        with tempfile.TemporaryDirectory(prefix="deeptutor-dashscope-stt-") as directory:
            source = Path(directory) / f"audio.{source_suffix}"
            target = Path(directory) / "audio.wav"
            source.write_bytes(audio)
            try:
                process = await asyncio.create_subprocess_exec(
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(source),
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(target),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                raise VoiceProviderError(
                    "ffmpeg is required to normalize audio for DashScope STT."
                ) from exc
            _, stderr = await process.communicate()
            if process.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace").strip()[:400]
                raise VoiceProviderError(
                    "Could not convert browser audio to WAV for DashScope STT"
                    + (f": {detail}" if detail else ".")
                )
            return target.read_bytes()

    @staticmethod
    def _is_canonical_wav(audio: bytes) -> bool:
        if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            return False
        sample_rate = int.from_bytes(audio[24:28], "little")
        channels = int.from_bytes(audio[22:24], "little")
        bits_per_sample = int.from_bytes(audio[34:36], "little")
        return sample_rate == 16000 and channels == 1 and bits_per_sample == 16

    @staticmethod
    def _audio_suffix(filename: str, content_type: str) -> str:
        suffix = Path(filename).suffix.lstrip(".").lower()
        if suffix in {"wav", "mp3", "aac", "ogg", "opus", "flac", "m4a", "webm"}:
            return suffix
        media_type = (content_type or "").split(";", 1)[0].strip().lower()
        return {
            "audio/wav": "wav",
            "audio/mpeg": "mp3",
            "audio/aac": "aac",
            "audio/ogg": "ogg",
            "audio/opus": "opus",
            "audio/webm": "webm",
            "audio/mp4": "m4a",
        }.get(media_type, "webm")

    @staticmethod
    def _websocket_url(base_url: str) -> str:
        parsed = urlsplit((base_url or "").strip())
        if not parsed.netloc:
            raise VoiceProviderError("No endpoint URL configured for DashScope STT.")
        if parsed.scheme in {"ws", "wss"}:
            return base_url
        if "/api-ws/" in parsed.path:
            return parsed._replace(scheme="wss").geturl()
        return f"wss://{parsed.netloc}/api-ws/v1/inference"

    @staticmethod
    def _start_payload(
        config: STTConfig, task_id: str, *, sample_rate: int = 16000
    ) -> dict[str, Any]:
        return {
            "header": {
                "task_id": task_id,
                "action": "run-task",
                "streaming": "duplex",
            },
            "payload": {
                "model": config.model,
                "task_group": "audio",
                "task": "asr",
                "function": "recognition",
                "input": {},
                "parameters": {"format": "wav", "sample_rate": sample_rate},
            },
        }

    async def _run_recognition(
        self,
        websocket: Any,
        audio: bytes,
        config: STTConfig,
    ) -> str:
        task_id = uuid.uuid4().hex
        await websocket.send_str(self._json(self._start_payload(config, task_id)))

        started = await websocket.receive()
        self._require_started(started, task_id)

        for offset in range(0, len(audio), 12800):
            await websocket.send_bytes(audio[offset : offset + 12800])
        await websocket.send_str(
            self._json(
                {
                    "header": {
                        "task_id": task_id,
                        "action": "finish-task",
                        "streaming": "duplex",
                    },
                    "payload": {"input": {}},
                }
            )
        )

        texts: list[str] = []
        while True:
            message = await websocket.receive()
            message_type = getattr(message, "type", None)
            if message_type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                raise VoiceProviderError("DashScope STT websocket closed unexpectedly.")
            if message_type != aiohttp.WSMsgType.TEXT:
                continue
            data = message.json()
            if not isinstance(data, dict):
                raise VoiceProviderError("DashScope STT returned a malformed websocket event.")
            header = data.get("header") or {}
            event = header.get("event")
            if event == "result-generated":
                texts.extend(self._sentence_texts((data.get("payload") or {}).get("output")))
            elif event == "task-failed":
                code = header.get("error_code") or "unknown"
                detail = header.get("error_message") or "no detail provided"
                raise VoiceProviderError(f"DashScope STT failed ({code}): {detail}")
            elif event == "task-finished":
                texts.extend(self._sentence_texts((data.get("payload") or {}).get("output")))
                break
        return "".join(texts).strip()

    @staticmethod
    def _sentence_texts(output: Any) -> list[str]:
        if isinstance(output, dict):
            sentence = output.get("sentence")
            values = sentence if isinstance(sentence, list) else [sentence]
            return [
                text
                for item in values
                if isinstance(item, dict)
                for text in [item.get("text")]
                if isinstance(text, str)
            ]
        return []

    @staticmethod
    def _require_started(message: Any, task_id: str) -> None:
        if getattr(message, "type", None) != aiohttp.WSMsgType.TEXT:
            raise VoiceProviderError("DashScope STT websocket closed before task started.")
        data = message.json()
        header = data.get("header") or {}
        if header.get("task_id") != task_id:
            raise VoiceProviderError("DashScope STT returned an unexpected task id.")
        if header.get("event") == "task-failed":
            raise VoiceProviderError(
                "DashScope STT failed to start: "
                + str(header.get("error_message") or "no detail provided")
            )
        if header.get("event") != "task-started":
            raise VoiceProviderError("DashScope STT returned an unexpected start event.")

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False)


__all__ = ["DashScopeSTTAdapter", "DashScopeTTSAdapter"]
