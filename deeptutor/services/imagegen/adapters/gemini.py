"""Native Gemini image generation through ``generateContent`` multimodal output.

Gemini image models (e.g. ``gemini-3.1-flash-image``, ``gemini-3-pro-image``,
``gemini-2.5-flash-image``) are not served reliably on the OpenAI-compatible
``/images/generations`` or ``/chat/completions`` endpoints; they use the native
``generateContent`` API with ``responseModalities: ["IMAGE"]``.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from deeptutor.services.generation_http import (
    GenerationProviderError,
    build_auth_headers,
    decode_base64_media,
    raise_for_provider,
)
from deeptutor.services.imagegen.base import BaseImagegenAdapter
from deeptutor.services.imagegen.config import ImagegenConfig

logger = logging.getLogger(__name__)

GEMINI_API_HOST = "generativelanguage.googleapis.com"


def _model_id(model: str) -> str:
    """Normalize discovery (``models/gemini-...``) and gateway (``google/...``) ids."""
    stripped = (model or "").strip().strip("/")
    while True:
        if stripped in {"models", "google"}:
            stripped = ""
            break
        for prefix in ("models/", "google/"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :].lstrip("/")
                break
        else:
            break
    if not stripped:
        raise GenerationProviderError("Enter a Gemini image model such as gemini-3.1-flash-image.")
    return stripped


def _native_base_url(base_url: str) -> str:
    """Normalize a configured API base URL for native Gemini endpoints."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise GenerationProviderError("No endpoint URL configured for image generation.")
    for suffix in ("/images/generations", "/chat/completions"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
    if base.endswith("/openai"):
        base = base[: -len("/openai")].rstrip("/")
    return base


def _auth_headers(base_url: str, config: ImagegenConfig) -> dict[str, str]:
    """Use Google's native key header on ``generativelanguage.googleapis.com``, Bearer elsewhere."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if config.api_key and config.api_key != "***":
        if (urlsplit(base_url).hostname or "").lower() == GEMINI_API_HOST:
            headers["x-goog-api-key"] = config.api_key
        else:
            headers.update(build_auth_headers(config.auth_style, config.api_key))
    return headers


class GeminiImagegenAdapter(BaseImagegenAdapter):
    """Generate images via Google's native ``:generateContent`` API."""

    async def generate(
        self, prompt: str, config: ImagegenConfig, *, n: int = 1
    ) -> list[tuple[bytes, str]]:
        model_id = _model_id(config.model)
        base = _native_base_url(config.base_url)

        if model_id.lower().startswith("imagen-"):
            from deeptutor.services.imagegen.adapters.openai_compat import (
                OpenAICompatImagegenAdapter,
            )

            openai_base = (
                f"{base}/openai"
                if (urlsplit(base).hostname or "").lower() == GEMINI_API_HOST
                else base
            )
            imagen_cfg = replace(
                config,
                model=model_id,
                base_url=openai_base,
                response_format=config.response_format or "b64_json",
            )
            return await OpenAICompatImagegenAdapter()._generate_openai_images(
                prompt, imagen_cfg, n=n
            )

        url = f"{base}/models/{model_id}:generateContent"
        headers = {**_auth_headers(base, config), **(config.extra_headers or {})}
        contents = [{"parts": [{"text": prompt}]}]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        target_count = max(1, n)
        images: list[tuple[bytes, str]] = []
        logger.debug("gemini imagegen url=%s model=%s n=%d", url, model_id, target_count)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                for _ in range(target_count):
                    if len(images) >= target_count:
                        break
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 400 and "modalit" in (resp.text or "").lower():
                        fallback_payload = {
                            "contents": contents,
                            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
                        }
                        resp = await client.post(url, headers=headers, json=fallback_payload)
                    raise_for_provider(resp, "Gemini image generation")
                    try:
                        data = resp.json()
                    except ValueError as exc:
                        raise GenerationProviderError(
                            "Gemini image generation returned invalid JSON."
                        ) from exc
                    batch = self._extract_images(data)
                    if not batch:
                        reason = self._failure_reason(data)
                        suffix = f" ({reason})" if reason else ""
                        raise GenerationProviderError(
                            f"Gemini image generation returned no image data{suffix}."
                        )
                    images.extend(batch)
        except httpx.HTTPError as exc:
            raise GenerationProviderError(f"Gemini image generation request error: {exc}") from exc
        if not images:
            raise GenerationProviderError("Gemini image generation returned no images.")
        return images[:target_count]

    @staticmethod
    def _extract_images(data: Any) -> list[tuple[bytes, str]]:
        if not isinstance(data, dict):
            return []
        candidates = data.get("candidates")
        if not isinstance(candidates, list):
            return []
        results: list[tuple[bytes, str]] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData") or part.get("inline_data")
                if not isinstance(inline, dict):
                    continue
                b64 = inline.get("data")
                if not isinstance(b64, str) or not b64:
                    continue
                raw_mime = str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
                mime_type = raw_mime.split(";", 1)[0].strip().lower() or "image/png"
                if not mime_type.startswith("image/"):
                    mime_type = "image/png"
                results.append((decode_base64_media(b64, "Gemini image generation"), mime_type))
        return results

    @staticmethod
    def _failure_reason(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        feedback = data.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            return f"blockReason={feedback['blockReason']}"
        candidates = data.get("candidates")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            if isinstance(first, dict) and first.get("finishReason"):
                return f"finishReason={first['finishReason']}"
        return ""


__all__ = ["GeminiImagegenAdapter"]
