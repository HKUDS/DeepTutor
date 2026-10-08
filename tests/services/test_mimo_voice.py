"""Regression checks for MiMo's chat-based speech protocol."""

import base64
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

import httpx

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.provider_runtime import resolve_tts_runtime_config
from deeptutor.services.voice.adapters import get_tts_adapter
from deeptutor.services.voice.adapters.mimo import MiMoTTSAdapter
from deeptutor.services.voice.base import VoiceProviderError, VoiceProviderHTTPError
from deeptutor.services.voice.config import TTSConfig
from deeptutor.services.voice.options import voice_model_options


class MiMoTTSTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the MiMo wire protocol without making external requests."""

    async def invoke(
        self, config: TTSConfig, response: dict[str, Any], status: int = 200
    ) -> tuple[tuple[bytes, str], list[httpx.Request]]:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(status, json=response)

        client_class = httpx.AsyncClient
        with patch(
            "deeptutor.services.voice.adapters.mimo.httpx.AsyncClient",
            side_effect=lambda **kwargs: client_class(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        ):
            result = await MiMoTTSAdapter().synthesize("你好", config)
        return result, requests

    def config(self, **kwargs: Any) -> TTSConfig:
        return TTSConfig(
            model="mimo-v2.5-tts",
            base_url="https://api.xiaomimimo.com/v1",
            api_key="test-key",
            response_format="wav",
            **kwargs,
        )

    async def test_request_roles_voice_and_base64_decode(self) -> None:
        audio = b"RIFF-test-audio"
        result, requests = await self.invoke(
            self.config(voice="苏打", instructions="用平静的语气朗读"),
            {"choices": [{"message": {"audio": {"data": base64.b64encode(audio).decode()}}}]},
        )
        self.assertEqual(result, (audio, "audio/wav"))
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(str(request.url), "https://api.xiaomimimo.com/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")
        self.assertEqual(
            json.loads(request.content),
            {
                "model": "mimo-v2.5-tts",
                "messages": [
                    {"role": "user", "content": "用平静的语气朗读"},
                    {"role": "assistant", "content": "你好"},
                ],
                "audio": {"format": "wav", "voice": "苏打"},
                "stream": False,
            },
        )

    async def test_pcm_alias_preserves_explicit_voice(self) -> None:
        config = self.config()
        config.base_url += "/chat/completions"
        config.response_format = "pcm"
        config.voice = "account-voice"
        result, requests = await self.invoke(
            config, {"choices": [{"message": {"audio": {"data": "AAABAA=="}}}]}
        )
        self.assertEqual(result, (b"\x00\x00\x01\x00", "audio/pcm;rate=24000;channels=1"))
        self.assertEqual(
            json.loads(requests[0].content)["audio"], {"format": "pcm16", "voice": "account-voice"}
        )
        self.assertEqual(str(requests[0].url), config.base_url)

    async def test_bad_audio_and_http_failure(self) -> None:
        for response in [
            {},
            {"choices": []},
            {"choices": [{"message": {"audio": {"data": "not-base64!"}}}]},
            {"choices": [{"message": {"audio": {"data": ""}}}]},
            {"choices": [{"message": {"audio": {"data": None}}}]},
        ]:
            with self.subTest(response=response), self.assertRaises(VoiceProviderError):
                await self.invoke(self.config(), response)
        with self.assertRaises(VoiceProviderHTTPError) as raised:
            await self.invoke(self.config(), {"error": {"message": "unauthorized"}}, 401)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_unsupported_parameters_fail_before_request(self) -> None:
        for field, value in (
            ("model", "mimo-v2.5-tts-voiceclone"),
            ("response_format", "mp3"),
            ("speed", 1.2),
        ):
            config = self.config()
            setattr(config, field, value)
            with self.subTest(field=field):
                with patch("deeptutor.services.voice.adapters.mimo.httpx.AsyncClient") as client:
                    with self.assertRaises(VoiceProviderError):
                        await MiMoTTSAdapter().synthesize("你好", config)
                client.assert_not_called()

    def test_linked_catalog_selects_native_adapter_and_defaults(self) -> None:
        ref = {"connection_id": "mimo", "binding": "xiaomi_mimo"}
        catalog = {
            "connections": [
                {
                    "id": "mimo",
                    "provider": "xiaomi_mimo",
                    "source_service": "llm",
                    "base_url": "https://api.xiaomimimo.com/v1",
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
                                    "model": "mimo-v2.5-tts",
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
        self.assertEqual(config.provider_name, "xiaomi_mimo")
        self.assertEqual(config.adapter, "mimo_tts")
        self.assertEqual(config.voice, "")
        self.assertEqual(config.response_format, "wav")
        self.assertEqual(config.api_key, "test-key")
        self.assertIsInstance(get_tts_adapter(config.adapter), MiMoTTSAdapter)
        options = voice_model_options("xiaomi_mimo", "tts", config.model)
        self.assertEqual(options["voices"], [])
        self.assertTrue(options["instructions"])


if __name__ == "__main__":
    unittest.main()
