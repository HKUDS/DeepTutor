"""OpenAI-compatible image-generation adapter.

Covers OpenAI DALL·E / gpt-image, Volcengine Ark Seedream and any gateway that
exposes ``POST {base}/images/generations``. Handles both response shapes —
``data[].b64_json`` (preferred: bytes inline) and ``data[].url`` (downloaded) —
so the caller always receives raw bytes and never has to deal with expiring
provider URLs.
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


class OpenAICompatImagegenAdapter(BaseImagegenAdapter):
    """POST ``{base}/images/generations`` with a JSON body, returning image bytes."""

    async def generate(
        self, prompt: str, config: ImagegenConfig, *, n: int = 1
    ) -> list[tuple[bytes, str]]:
        if not config.base_url:
            raise GenerationProviderError("No endpoint URL configured for image generation.")
        url = join_api_path(config.base_url, "images/generations")
        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        payload: dict[str, Any] = {"model": config.model, "prompt": prompt, "n": max(1, n)}
        if config.size:
            payload["size"] = config.size
        if config.quality:
            payload["quality"] = config.quality
        if config.style:
            payload["style"] = config.style
        if config.response_format:
            payload["response_format"] = config.response_format

        logger.debug(
            "imagegen url=%s model=%s n=%d size=%s", url, config.model, max(1, n), config.size
        )
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                raise_for_provider(resp, "Image generation")
                images = [
                    await self._materialize(client, item) for item in self._extract_items(resp)
                ]
        except httpx.HTTPError as exc:
            raise GenerationProviderError(f"Image generation request error: {exc}") from exc
        if not images:
            raise GenerationProviderError("Image provider returned no images.")
        return images

    @staticmethod
    def _extract_items(resp: httpx.Response) -> list[dict[str, Any]]:
        data = resp.json()
        if isinstance(data, dict):
            items = data.get("data")
            if isinstance(items, list) and items:
                return [item for item in items if isinstance(item, dict)]
        raise GenerationProviderError("Image response had no `data` array.")

    async def _materialize(
        self, client: httpx.AsyncClient, item: dict[str, Any]
    ) -> tuple[bytes, str]:
        b64 = item.get("b64_json")
        if isinstance(b64, str) and b64:
            return base64.b64decode(b64), "image/png"
        src = item.get("url")
        if isinstance(src, str) and src:
            resp = await client.get(src)
            raise_for_provider(resp, "Image download")
            content_type = resp.headers.get("content-type") or "image/png"
            if not content_type.startswith("image/"):
                content_type = "image/png"
            return resp.content, content_type
        raise GenerationProviderError("Image item had neither `b64_json` nor `url`.")


__all__ = ["OpenAICompatImagegenAdapter"]
