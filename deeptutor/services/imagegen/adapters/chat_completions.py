"""Chat-completions image-generation adapter (OpenRouter-style).

Some gateways generate images through the chat endpoint rather than the OpenAI
Images API: ``POST {base}/chat/completions`` with ``modalities: ["image",
"text"]`` returns the image inside the assistant message::

    {"choices": [{"message": {"images": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]}}]}

This covers OpenRouter image models (Flux, Gemini image, …). Images are usually
base64 data URIs; an http URL is downloaded as a fallback.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from deeptutor.services.generation_http import (
    GenerationProviderError,
    build_auth_headers,
    join_api_path,
    raise_for_provider,
)
from deeptutor.services.imagegen.base import BaseImagegenAdapter
from deeptutor.services.imagegen.config import ImagegenConfig

logger = logging.getLogger(__name__)


class ChatCompletionsImagegenAdapter(BaseImagegenAdapter):
    """POST ``{base}/chat/completions`` with image modalities; collect image bytes."""

    async def generate(
        self, prompt: str, config: ImagegenConfig, *, n: int = 1
    ) -> list[tuple[bytes, str]]:
        if not config.base_url:
            raise GenerationProviderError("No endpoint URL configured for image generation.")
        url = join_api_path(config.base_url, "chat/completions")
        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image", "text"],
        }

        logger.debug("imagegen(chat) url=%s model=%s", url, config.model)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                raise_for_provider(resp, "Image generation")
                images = [
                    await self._materialize(client, src) for src in self._extract_sources(resp)
                ]
        except httpx.HTTPError as exc:
            raise GenerationProviderError(f"Image generation request error: {exc}") from exc
        if not images:
            raise GenerationProviderError(
                "Chat model returned no image. Check the model supports image output "
                "(its output modalities must include `image`)."
            )
        return images

    @staticmethod
    def _extract_sources(resp: httpx.Response) -> list[str]:
        """Pull image URLs / data URIs out of the assistant message."""
        data = resp.json()
        sources: list[str] = []
        choices = data.get("choices") if isinstance(data, dict) else None
        for choice in choices or []:
            message = (choice or {}).get("message") or {}
            for image in message.get("images") or []:
                if not isinstance(image, dict):
                    continue
                src = (image.get("image_url") or {}).get("url") or image.get("url")
                if isinstance(src, str) and src:
                    sources.append(src)
            # Fallback: some variants nest images in the content parts array.
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    src = (part.get("image_url") or {}).get("url") or part.get("url")
                    if isinstance(src, str) and src.startswith(("data:image", "http")):
                        sources.append(src)
        if not sources:
            raise GenerationProviderError("Image response had no image in the assistant message.")
        return sources

    async def _materialize(self, client: httpx.AsyncClient, src: str) -> tuple[bytes, str]:
        if src.startswith("data:"):
            header, _, encoded = src.partition(",")
            if not encoded:
                raise GenerationProviderError("Malformed image data URI.")
            content_type = header[5:].split(";", 1)[0].strip() or "image/png"
            return base64.b64decode(encoded), content_type
        resp = await client.get(src)
        raise_for_provider(resp, "Image download")
        content_type = resp.headers.get("content-type") or "image/png"
        if not content_type.startswith("image/"):
            content_type = "image/png"
        return resp.content, content_type


__all__ = ["ChatCompletionsImagegenAdapter"]
