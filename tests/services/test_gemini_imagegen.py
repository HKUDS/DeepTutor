"""Regression checks for Gemini's native generateContent image output."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

import httpx

from deeptutor.api.routers import settings as settings_router
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.provider_runtime import resolve_imagegen_runtime_config
from deeptutor.services.generation_http import GenerationProviderError
from deeptutor.services.imagegen.adapters import get_imagegen_adapter
from deeptutor.services.imagegen.adapters.gemini import GeminiImagegenAdapter
from deeptutor.services.imagegen.adapters.openai_compat import OpenAICompatImagegenAdapter
from deeptutor.services.imagegen.config import ImagegenConfig

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


def gemini_image_response(
    images: list[tuple[bytes, str]] | None = None,
    *,
    mime_type: str = "image/jpeg",
    **extra: Any,
) -> dict[str, Any]:
    items = images if images is not None else [(b"\xff\xd8\xff\xe0JPEGDATA", mime_type)]
    parts = [
        {
            "inlineData": {
                "mimeType": item_mime,
                "data": base64.b64encode(raw).decode("ascii"),
            }
        }
        for raw, item_mime in items
    ]
    return {"candidates": [{"content": {"parts": parts}}], **extra}


class GeminiImagegenTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the Gemini imagegen protocol without making external requests."""

    async def invoke(
        self,
        config: ImagegenConfig,
        handler_or_response: Any,
        status: int = 200,
        *,
        n: int = 1,
        adapter: Any | None = None,
    ) -> tuple[list[tuple[bytes, str]], list[httpx.Request]]:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if callable(handler_or_response):
                return handler_or_response(request, len(requests))
            return httpx.Response(status, json=handler_or_response)

        client_class = httpx.AsyncClient
        with (
            patch(
                "deeptutor.services.imagegen.adapters.gemini.httpx.AsyncClient",
                side_effect=lambda **kwargs: client_class(
                    transport=httpx.MockTransport(handler), **kwargs
                ),
            ),
            patch(
                "deeptutor.services.imagegen.adapters.openai_compat.httpx.AsyncClient",
                side_effect=lambda **kwargs: client_class(
                    transport=httpx.MockTransport(handler), **kwargs
                ),
            ),
        ):
            impl = adapter or GeminiImagegenAdapter()
            result = await impl.generate("A sunny plaza", config, n=n)
        return result, requests

    def config(self, **kwargs: Any) -> ImagegenConfig:
        defaults: dict[str, Any] = {
            "model": "gemini-3.1-flash-image",
            "provider_name": "gemini",
            "adapter": "gemini",
            "base_url": API_ROOT,
            "api_key": "test-key",
        }
        return ImagegenConfig(**{**defaults, **kwargs})

    async def test_request_shape_and_inline_image_decode(self) -> None:
        raw = b"\xff\xd8\xff\xe0FAKEJPEG"
        result, requests = await self.invoke(
            self.config(), gemini_image_response([(raw, "image/jpeg")])
        )
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(
            str(request.url), f"{API_ROOT}/models/gemini-3.1-flash-image:generateContent"
        )
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(request.headers["x-goog-api-key"], "test-key")
        self.assertEqual(
            json.loads(request.content),
            {
                "contents": [{"parts": [{"text": "A sunny plaza"}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            },
        )
        self.assertEqual(result, [(raw, "image/jpeg")])

    async def test_model_prefixes_and_openai_suffix_are_normalized(self) -> None:
        for model_name, expected_id in (
            ("models/gemini-3-pro-image", "gemini-3-pro-image"),
            ("google/gemini-nano-banana-2.1", "gemini-nano-banana-2.1"),
            ("google/models/gemini-3.1-flash-lite-image", "gemini-3.1-flash-lite-image"),
        ):
            with self.subTest(model_name=model_name):
                config = self.config(
                    model=model_name,
                    base_url=f"{API_ROOT}/openai/",
                    response_format="",
                )
                result, requests = await self.invoke(config, gemini_image_response())
                self.assertEqual(
                    str(requests[0].url),
                    f"{API_ROOT}/models/{expected_id}:generateContent",
                )
                self.assertEqual(result[0][1], "image/jpeg")

    async def test_gateway_base_url_uses_bearer_auth(self) -> None:
        config = self.config(base_url="https://gateway.example.com/v1beta/openai/")
        _, requests = await self.invoke(config, gemini_image_response())
        self.assertEqual(
            str(requests[0].url),
            "https://gateway.example.com/v1beta/models/gemini-3.1-flash-image:generateContent",
        )
        self.assertNotIn("x-goog-api-key", requests[0].headers)
        self.assertEqual(requests[0].headers["Authorization"], "Bearer test-key")

    async def test_retries_with_text_and_image_modalities_on_400(self) -> None:
        def handler(_request: httpx.Request, attempt: int) -> httpx.Response:
            if attempt == 1:
                return httpx.Response(
                    400,
                    json={
                        "error": {"message": "Requested response modalities [IMAGE] not supported"}
                    },
                )
            return httpx.Response(200, json=gemini_image_response([(b"PNGDATA", "image/png")]))

        result, requests = await self.invoke(self.config(), handler)
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            json.loads(requests[1].content)["generationConfig"]["responseModalities"],
            ["TEXT", "IMAGE"],
        )
        self.assertEqual(result, [(b"PNGDATA", "image/png")])

    async def test_multiple_images_requested(self) -> None:
        result, requests = await self.invoke(
            self.config(),
            gemini_image_response([(b"IMG1", "image/png")]),
            n=2,
        )
        self.assertEqual(len(requests), 2)
        self.assertEqual(result, [(b"IMG1", "image/png"), (b"IMG1", "image/png")])

    async def test_imagen_models_use_openai_images_endpoint_with_default_b64_json(self) -> None:
        b64 = base64.b64encode(b"IMAGENPNG").decode("ascii")
        config = self.config(
            model="models/imagen-4.0-generate-001",
            base_url=f"{API_ROOT}/openai/",
            response_format="",
        )
        result, requests = await self.invoke(config, {"data": [{"b64_json": b64}]})
        self.assertEqual(len(requests), 1)
        self.assertEqual(str(requests[0].url), f"{API_ROOT}/openai/images/generations")
        self.assertEqual(
            json.loads(requests[0].content),
            {
                "model": "imagen-4.0-generate-001",
                "prompt": "A sunny plaza",
                "n": 1,
                "response_format": "b64_json",
            },
        )
        self.assertEqual(result, [(b"IMAGENPNG", "image/png")])

    async def test_legacy_custom_binding_on_google_host_uses_native_generate_content(self) -> None:
        config = ImagegenConfig(
            model="models/gemini-nano-banana-2.1",
            provider_name="custom",
            adapter="openai_compat",
            base_url=f"{API_ROOT}/openai/",
            api_key="test-key",
            response_format="",
        )
        result, requests = await self.invoke(
            config,
            gemini_image_response([(b"JPEGDATA", "image/jpeg")]),
            adapter=OpenAICompatImagegenAdapter(),
        )
        self.assertEqual(
            str(requests[0].url),
            f"{API_ROOT}/models/gemini-nano-banana-2.1:generateContent",
        )
        self.assertEqual(result, [(b"JPEGDATA", "image/jpeg")])

    async def test_bad_responses_blocked_prompt_and_http_errors(self) -> None:
        for response in (
            {},
            {"candidates": []},
            {"promptFeedback": {"blockReason": "SAFETY"}},
            {
                "candidates": [
                    {"content": {"parts": [{"text": "no image"}]}, "finishReason": "STOP"}
                ]
            },
            {"candidates": [{"content": {"parts": [{"inlineData": {"data": "not-base64!"}}]}}]},
        ):
            with self.subTest(response=response), self.assertRaises(GenerationProviderError):
                await self.invoke(self.config(), response)

        for status_code in (401, 404):
            with self.subTest(status_code=status_code), self.assertRaises(GenerationProviderError):
                await self.invoke(
                    self.config(), {"error": {"message": "failed"}}, status=status_code
                )

        for field, value in (("base_url", ""), ("model", ""), ("model", "models/")):
            bad_cfg = self.config(**{field: value})
            with (
                self.subTest(field=field, value=value),
                patch("deeptutor.services.imagegen.adapters.gemini.httpx.AsyncClient") as client,
            ):
                with self.assertRaises(GenerationProviderError):
                    await GeminiImagegenAdapter().generate("A sunny plaza", bad_cfg)
                client.assert_not_called()

    def test_linked_catalog_and_connection_targets_expose_gemini_imagegen(self) -> None:
        cases = [
            ("", {"connection_id": "gemini-conn", "binding": "gemini"}, API_ROOT),
            (
                f"{API_ROOT}/openai/",
                {"connection_id": "gemini-conn", "binding": "gemini"},
                f"{API_ROOT}/openai",
            ),
            (
                f"{API_ROOT}/openai/",
                {
                    "connection_id": "gemini-conn",
                    "binding": "gemini",
                    "default_base_url": API_ROOT,
                },
                API_ROOT,
            ),
        ]
        for connection_base_url, ref, expected_base in cases:
            with self.subTest(connection_base_url=connection_base_url, ref=ref):
                catalog = {
                    "connections": [
                        {
                            "id": "gemini-conn",
                            "provider": "gemini",
                            "source_service": "llm",
                            "base_url": connection_base_url,
                            "api_key": "test-key",
                        }
                    ],
                    "services": {
                        "imagegen": {
                            "active_profile_id": "profile",
                            "active_model_id": "model",
                            "profiles": [
                                {
                                    "id": "profile",
                                    "provider_ref": ref,
                                    "models": [
                                        {
                                            "id": "model",
                                            "model": "models/gemini-3-pro-image",
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
                    config = resolve_imagegen_runtime_config(catalog, service=service)
                self.assertEqual(config.provider_name, "gemini")
                self.assertEqual(config.adapter, "gemini")
                self.assertEqual(config.base_url, expected_base)
                self.assertIsInstance(get_imagegen_adapter(config.adapter), GeminiImagegenAdapter)

        targets = {item["provider"]: item for item in settings_router._connection_targets()}
        gemini_services = targets["gemini"]["services"]
        self.assertIn("imagegen", gemini_services)
        self.assertEqual(gemini_services["imagegen"]["provider"], "gemini")
        self.assertEqual(gemini_services["imagegen"]["base_url"], API_ROOT)
        self.assertEqual(gemini_services["imagegen"]["default_model"], "gemini-3.1-flash-image")


if __name__ == "__main__":
    unittest.main()
