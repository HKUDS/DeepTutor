"""Regression checks for Gemini's native generateContent speech protocol."""

import base64
import io
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch
import wave

import httpx

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.provider_runtime import resolve_tts_runtime_config
from deeptutor.services.voice.adapters import get_tts_adapter
from deeptutor.services.voice.adapters.gemini import GeminiTTSAdapter
from deeptutor.services.voice.base import VoiceProviderError, VoiceProviderHTTPError
from deeptutor.services.voice.config import TTSConfig
from deeptutor.services.voice.options import voice_model_options

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


def gemini_response(chunks: list[bytes], **extra: Any) -> dict[str, Any]:
    parts = [
        {
            "inlineData": {
                "mimeType": "audio/L16;codec=pcm;rate=24000",
                "data": base64.b64encode(chunk).decode("ascii"),
            }
        }
        for chunk in chunks
    ]
    return {"candidates": [{"content": {"parts": parts}}], **extra}


class GeminiTTSTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the Gemini wire protocol without making external requests."""

    async def invoke(
        self, config: TTSConfig, response: dict[str, Any], status: int = 200
    ) -> tuple[tuple[bytes, str], list[httpx.Request]]:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(status, json=response)

        client_class = httpx.AsyncClient
        with patch(
            "deeptutor.services.voice.adapters.gemini.httpx.AsyncClient",
            side_effect=lambda **kwargs: client_class(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        ):
            result = await GeminiTTSAdapter().synthesize("你好", config)
        return result, requests

    def config(self, **kwargs: Any) -> TTSConfig:
        defaults: dict[str, Any] = {
            "model": "gemini-2.5-flash-preview-tts",
            "base_url": API_ROOT,
            "api_key": "test-key",
            "voice": "Kore",
            "response_format": "wav",
        }
        return TTSConfig(**{**defaults, **kwargs})

    async def test_request_shape_and_wav_wrap(self) -> None:
        pcm = b"\x00\x01" * 12
        result, requests = await self.invoke(self.config(), gemini_response([pcm]))
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(
            str(request.url), f"{API_ROOT}/models/gemini-2.5-flash-preview-tts:generateContent"
        )
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(request.headers["x-goog-api-key"], "test-key")
        self.assertEqual(
            json.loads(request.content),
            {
                "contents": [{"parts": [{"text": "你好"}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}},
                },
            },
        )
        audio, content_type = result
        self.assertEqual(content_type, "audio/wav")
        with wave.open(io.BytesIO(audio), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.readframes(wav.getnframes()), pcm)

    async def test_model_prefixes_and_openai_suffix_are_normalized(self) -> None:
        config = self.config(
            model="models/gemini-3.1-flash-tts-preview",
            base_url=f"{API_ROOT}/openai/",
        )
        _, requests = await self.invoke(config, gemini_response([b"\x00\x00"]))
        self.assertEqual(
            str(requests[0].url),
            f"{API_ROOT}/models/gemini-3.1-flash-tts-preview:generateContent",
        )

    async def test_gateway_base_url_uses_bearer_auth(self) -> None:
        config = self.config(base_url="https://gateway.example.com/gemini")
        _, requests = await self.invoke(config, gemini_response([b"\x00\x00"]))
        self.assertNotIn("x-goog-api-key", requests[0].headers)
        self.assertEqual(requests[0].headers["Authorization"], "Bearer test-key")

    async def test_instructions_prefix_and_pcm_passthrough(self) -> None:
        pcm = b"\x01\x02"
        config = self.config(instructions="Say cheerfully", response_format="pcm16", speed=None)
        result, requests = await self.invoke(config, gemini_response([pcm]))
        self.assertEqual(result, (pcm, "audio/pcm;rate=24000;channels=1"))
        self.assertEqual(
            json.loads(requests[0].content)["contents"][0]["parts"][0]["text"],
            "Say cheerfully: 你好",
        )

    async def test_multi_part_audio_is_concatenated(self) -> None:
        chunks = [b"\x00\x01", b"\x02\x03", b"\x04\x05"]
        result, _ = await self.invoke(self.config(), gemini_response(chunks))
        with wave.open(io.BytesIO(result[0]), "rb") as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), b"".join(chunks))

    async def test_bad_audio_and_http_failure(self) -> None:
        for response in [
            {},
            {"candidates": []},
            {"candidates": [{"content": {"parts": [{"text": "no audio"}]}}]},
            gemini_response([b""]),
            {"candidates": [{"content": {"parts": [{"inlineData": {"data": "not-base64!"}}]}}]},
        ]:
            with self.subTest(response=response), self.assertRaises(VoiceProviderError):
                await self.invoke(self.config(), response)
        with self.assertRaises(VoiceProviderHTTPError) as raised:
            await self.invoke(self.config(), {"error": {"message": "unauthorized"}}, 401)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_unsupported_parameters_fail_before_request(self) -> None:
        for field, value in (
            ("response_format", "mp3"),
            ("speed", 1.2),
            ("voice", ""),
            ("base_url", ""),
        ):
            config = self.config()
            setattr(config, field, value)
            with self.subTest(field=field):
                with patch("deeptutor.services.voice.adapters.gemini.httpx.AsyncClient") as client:
                    with self.assertRaises(VoiceProviderError):
                        await GeminiTTSAdapter().synthesize("你好", config)
                client.assert_not_called()

    def test_linked_catalog_selects_native_adapter_and_defaults(self) -> None:
        ref = {"connection_id": "gemini-conn", "binding": "gemini"}
        catalog = {
            "connections": [
                {
                    "id": "gemini-conn",
                    "provider": "gemini",
                    "source_service": "llm",
                    "base_url": "",
                    "api_key": "test-key",
                }
            ],
            "services": {
                "tts": {
                    "active_profile_id": "profile",
                    "active_model_id": "model",
                    "profiles": [
                        {
                            "id": "profile",
                            "provider_ref": ref,
                            "models": [
                                {
                                    "id": "model",
                                    "model": "models/gemini-2.5-flash-preview-tts",
                                    "voice": "Kore",
                                    "provider_ref": ref,
                                }
                            ],
                        }
                    ],
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            service = ModelCatalogService(Path(directory) / "catalog.json")
            config = resolve_tts_runtime_config(catalog, service=service)
        self.assertEqual(config.provider_name, "gemini")
        self.assertEqual(config.adapter, "gemini")
        self.assertEqual(config.base_url, API_ROOT)
        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.voice, "Kore")
        self.assertEqual(config.response_format, "wav")
        self.assertIsInstance(get_tts_adapter(config.adapter), GeminiTTSAdapter)
        options = voice_model_options("gemini", "tts", config.model)
        self.assertIn("wav", options["formats"])
        self.assertTrue(options["instructions"])


if __name__ == "__main__":
    unittest.main()
