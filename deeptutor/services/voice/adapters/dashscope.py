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

from deeptutor.services.voice.audio import FFMPEG_STT_INSTALL_HINT
from deeptutor.services.voice.base import (
    BaseSTTAdapter,
    BaseTTSAdapter,
    VoiceProviderError,
    VoiceProviderHTTPError,
    VoiceProviderTimeout,
    build_auth_headers,
    join_audio_path,
)
from deeptutor.services.voice.config import STTConfig, TTSConfig
from deeptutor.services.voice.options import is_qwen_audio_tts

_TTS_PATH = "services/aigc/multimodal-generation/generation"
_QWEN_AUDIO_TTS_PATH = "services/audio/tts/SpeechSynthesizer"
_AUDIO_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/opus",
    "pcm": "audio/pcm",
}


def _provider_error(
    resp: httpx.Response, action: str, *, public_message: str | None = None
) -> None:
    if resp.status_code < 400:
        return
    detail = (resp.text or "").strip()[:400]
    raise VoiceProviderHTTPError(
        f"{action} failed with HTTP {resp.status_code}" + (f": {detail}" if detail else "."),
        status_code=resp.status_code,
        body=resp.text,
        public_message=public_message,
    )


def _dashscope_error(data: dict[str, Any], action: str) -> None:
    if data.get("code") not in (None, "", 0, "0") or data.get("success") is False:
        code = data.get("code") or "unknown"
        message = data.get("message") or "no detail provided"
        raise VoiceProviderError(
            f"{action} failed ({code}): {message}",
            public_message=(
                "Speech parameters were rejected. Check the model, voice, language and audio format."
                if code == "InvalidParameter"
                else None
            ),
        )


def _tts_url(config: TTSConfig) -> str:
    """Select the model's native route while preserving explicit endpoints."""
    parsed = urlsplit(config.base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Speech synthesis requires an HTTP or HTTPS provider URL.")
    if config.model.startswith("qwen") and "realtime" in config.model:
        raise ValueError(
            "Realtime speech models are not supported here. Select a non-realtime TTS model."
        )
    native_audio = is_qwen_audio_tts(config.model)
    host = parsed.hostname.lower()
    official_host = host in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    } or host.endswith(".maas.aliyuncs.com")
    if native_audio and (
        host in {"dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"}
        or (
            host.endswith(".maas.aliyuncs.com")
            and not host.endswith(".cn-beijing.maas.aliyuncs.com")
        )
    ):
        raise ValueError(
            "Qwen-Audio TTS is available only in Beijing. Use a Beijing API key and provider URL."
        )
    # Shared chat connections may carry DashScope's OpenAI-compatible base.
    # Translate only official hosts; gateway overrides retain their own paths.
    if official_host and parsed.path.rstrip("/") == "/compatible-mode/v1":
        parsed = parsed._replace(path="/api/v1")
    suffix = _QWEN_AUDIO_TTS_PATH if native_audio else _TTS_PATH
    other = _TTS_PATH if native_audio else _QWEN_AUDIO_TTS_PATH
    if parsed.path.rstrip("/").endswith("/" + other):
        if official_host:
            raise ValueError(
                "The configured speech endpoint does not match this model. Use the provider API base URL to select the endpoint automatically."
            )
        return parsed.geturl()
    return join_audio_path(parsed.geturl(), suffix)


def _tts_input(text: str, config: TTSConfig) -> dict[str, Any]:
    native_audio = is_qwen_audio_tts(config.model)
    inputs: dict[str, Any] = {"text": text}
    if config.voice:
        inputs["voice"] = config.voice
    elif native_audio:
        raise ValueError("Enter a voice ID supported by the selected Qwen-Audio TTS model.")
    if config.language:
        if native_audio:
            language = {"Chinese": "zh", "English": "en", "Auto": ""}.get(
                config.language, config.language
            )
            if language:
                inputs["language_hints"] = [language]
        else:
            inputs["language_type"] = config.language
    if config.instructions:
        inputs["instruction" if native_audio else "instructions"] = config.instructions
    if native_audio:
        audio_format = (config.response_format or "mp3").lower()
        if audio_format not in _AUDIO_CONTENT_TYPES:
            raise ValueError("Qwen-Audio TTS supports MP3, WAV, Opus and PCM audio formats.")
        rates = {8000, 12000, 16000, 24000, 48000}
        if audio_format != "opus":
            rates |= {22050, 44100}
        if config.sample_rate not in rates:
            raise ValueError(
                "The selected sample rate is not supported for this Qwen-Audio TTS audio format."
            )
        if config.speed is not None and not 0.5 <= config.speed <= 2:
            raise ValueError("Qwen-Audio TTS speed must be between 0.5 and 2.")
        inputs.update(format=audio_format, sample_rate=config.sample_rate)
        if config.speed is not None:
            inputs["rate"] = config.speed
    return inputs


class DashScopeTTSAdapter(BaseTTSAdapter):
    """Generate speech with Qwen TTS and download the returned audio URL."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        if not config.base_url:
            raise VoiceProviderError("No endpoint URL configured for TTS.")
        url = _tts_url(config)
        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        payload: dict[str, Any] = {
            "model": config.model,
            "input": _tts_input(text, config),
        }

        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                _provider_error(resp, "DashScope TTS")
                data = self._json_object(resp)
                _dashscope_error(data, "DashScope TTS")
                audio_url = self._audio_url(data)
                download_hint = "Speech was generated, but the audio download failed. Try again or check the network connection."
                try:
                    audio_resp = await client.get(audio_url)
                except httpx.HTTPError as exc:
                    raise VoiceProviderError(
                        f"DashScope audio download error: {exc}", public_message=download_hint
                    ) from exc
                _provider_error(
                    audio_resp, "DashScope audio download", public_message=download_hint
                )
        except httpx.TimeoutException as exc:
            raise VoiceProviderTimeout() from exc
        except httpx.HTTPError as exc:
            raise VoiceProviderError(
                f"DashScope TTS request error: {exc}",
                public_message="Could not connect to the speech provider. Check the provider URL and network connection.",
            ) from exc
        except ValueError as exc:
            raise VoiceProviderError(
                f"DashScope TTS response error: {exc}",
                public_message="The speech provider returned an invalid response. Check the provider URL.",
            ) from exc

        if not audio_resp.content:
            raise VoiceProviderError(
                "DashScope TTS returned empty audio.",
                public_message="The speech provider returned empty audio. Try another text or voice.",
            )
        content_type = audio_resp.headers.get("content-type") or self._url_content_type(
            audio_url, config.response_format
        )
        if not content_type.startswith("audio/"):
            content_type = _AUDIO_CONTENT_TYPES.get(
                (config.response_format or "wav").lower(), "audio/wav"
            )
        if is_qwen_audio_tts(config.model) and config.response_format.lower() == "pcm":
            content_type = f"audio/pcm;rate={config.sample_rate};channels=1"
        return audio_resp.content, content_type

    @staticmethod
    def _json_object(resp: httpx.Response) -> dict[str, Any]:
        data = resp.json()
        if not isinstance(data, dict):
            raise VoiceProviderError(
                "DashScope TTS returned a malformed response.",
                public_message="The speech provider returned an invalid response. Check the provider URL.",
            )
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
        raise VoiceProviderError(
            "DashScope TTS response had no audio URL.",
            public_message="The speech provider returned an invalid response. Check the provider URL.",
        )

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
        if config.model in {"paraformer-realtime-8k-v1", "paraformer-realtime-8k-v2"}:
            raise VoiceProviderError(
                "DashScope 8k realtime models require 8000 Hz audio; "
                "select paraformer-realtime-v2 for the 16000 Hz voice adapter."
            )
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
                    "ffmpeg is required to normalize audio for DashScope STT. "
                    + FFMPEG_STT_INSTALL_HINT
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
                "parameters": {
                    "format": "wav",
                    "sample_rate": sample_rate,
                    **({"language_hints": [config.language]} if config.language else {}),
                },
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
