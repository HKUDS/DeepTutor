"""Aliyun DashScope native text-to-image adapter.

DashScope serves image models through two request protocols:

* **Legacy ``text2image``** (``wan2.5`` and earlier, ``qwen-image-plus`` /
  ``qwen-image``): ``POST .../services/aigc/text2image/image-synthesis`` with
  ``input.prompt``; polled results carry ``output.results[].url``.
* **Multimodal generation** (``wan2.6`` / ``wan2.7``, ``qwen-image-3.0`` and
  ``qwen-image-2.1``): ``POST .../services/aigc/image-generation/generation``
  with a single ``input.messages`` user turn; polled results carry
  ``output.choices[].message.content[].image``.

Both are asynchronous and share ``GET .../tasks/{task_id}`` for polling, so the
only differences are the submit route, the payload shape and where the image
URLs live. Sending a multimodal-only model to the legacy route answers
``400 InvalidParameter: url error`` (issue #2422).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
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

# The prompt-style image API lives under the ``text2image`` namespace; dropping
# that segment falls through to a generic async route that answers
# 400 "task can not be null" for every model.
_LEGACY_SUBMIT_PATH = "services/aigc/text2image/image-synthesis"
# The newer models use the shared multimodal-generation route. It is async-only
# for HTTP callers, so the request keeps the ``X-DashScope-Async`` header.
_MULTIMODAL_SUBMIT_PATH = "services/aigc/image-generation/generation"

#: Model families served by the multimodal-generation protocol. IDs are matched
#: by prefix so dated snapshots (``wan2.7-image-2026xxxx``) route the same way; a
#: new family is one entry here. Everything else stays on the legacy route, so a
#: configuration that works today never changes protocol silently.
_MULTIMODAL_MODEL_PREFIXES = ("wan2.6", "wan2.7", "qwen-image-3", "qwen-image-2.1")

#: Only wan2.7 accepts resolution tiers; wan2.6 and qwen-image take pixels.
_TIER_MODEL_PREFIX = "wan2.7"
#: Within wan2.7, 4K text-to-image is Pro only — ``wan2.7-image`` stops at 2K.
_PRO_4K_MODEL = "wan2.7-image-pro"
_SIZE_TIERS = {"1k": "1K", "2k": "2K", "4k": "4K"}
_SIZE_PATTERN = re.compile(r"^(\d+)\s*[x*×]\s*(\d+)$", re.IGNORECASE)


def _is_multimodal(model: str) -> bool:
    """Whether ``model`` is served by the multimodal-generation protocol."""
    return model.strip().lower().startswith(_MULTIMODAL_MODEL_PREFIXES)


class DashScopeImagegenAdapter(BaseImagegenAdapter):
    """Submit a DashScope image task, poll it, and materialize image bytes."""

    async def generate(
        self, prompt: str, config: ImagegenConfig, *, n: int = 1
    ) -> list[tuple[bytes, str]]:
        if not config.base_url:
            raise GenerationProviderError("No endpoint URL configured for image generation.")
        headers = self._headers(config)
        payload = self._submit_payload(prompt, config, n=max(1, n))
        submit_url = join_api_path(config.base_url, self._submit_path(config.model))
        logger.debug("DashScope image submit url=%s model=%s", submit_url, config.model)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(submit_url, headers=headers, json=payload)
                raise_for_provider(resp, "DashScope image task submission")
                task_id = self._task_id(resp)
                urls = await self._poll(client, config, self._poll_headers(config), task_id)
                images = [await self._materialize(client, url) for url in urls]
        except httpx.HTTPError as exc:
            raise GenerationProviderError(f"DashScope image request error: {exc}") from exc
        if not images:
            raise GenerationProviderError("DashScope image task returned no images.")
        return images

    @staticmethod
    def _headers(config: ImagegenConfig) -> dict[str, str]:
        """Headers for the submit POST — the async switch is required here."""
        return {
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }

    @staticmethod
    def _poll_headers(config: ImagegenConfig) -> dict[str, str]:
        """Headers for the poll GET — never carry the async switch.

        ``X-DashScope-Async`` selects the asynchronous submission mode, which
        only the POST routes implement. Replaying it on ``GET /tasks/{id}`` makes
        the gateway look for an async capability the caller may not have: some
        workspace-scoped keys answer ``403 AccessDenied: current user api does
        not support asynchronous calls`` for every poll, so a task that succeeded
        upstream is reported as a failure.
        """
        return {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }

    @staticmethod
    def _submit_path(model: str) -> str:
        """The submit route for ``model``'s protocol."""
        return _MULTIMODAL_SUBMIT_PATH if _is_multimodal(model) else _LEGACY_SUBMIT_PATH

    @staticmethod
    def _submit_payload(prompt: str, config: ImagegenConfig, *, n: int) -> dict[str, Any]:
        parameters: dict[str, Any] = {"n": max(1, n)}
        size = DashScopeImagegenAdapter._size(config.model, config.size)
        if size:
            parameters["size"] = size
        if _is_multimodal(config.model):
            # The prompt is the single text part of one user turn. ``style`` is
            # not a parameter on this protocol and is dropped; the thinking
            # switch is left at the upstream default rather than sent, because
            # its name differs per family (``thinking_mode`` on wan2.7,
            # ``enable_thinking`` on qwen-image) and wan2.6 rejects both.
            return {
                "model": config.model,
                "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
                "parameters": parameters,
            }
        if config.style:
            parameters["style"] = config.style
        return {
            "model": config.model,
            "input": {"prompt": prompt},
            "parameters": parameters,
        }

    @staticmethod
    def _size(model: str, size: str) -> str:
        """Normalize a configured size into the spelling ``model`` accepts.

        Settings keeps one ``size`` string for every image provider, so it can
        arrive as ``1024x1024`` (the OpenAI spelling) or as a ``1K``/``2K`` tier.
        DashScope writes pixels as ``W*H`` and only wan2.7 takes tiers.
        """
        raw = (size or "").strip()
        if not raw:
            return ""
        pixels = _SIZE_PATTERN.match(raw)
        if pixels:
            return f"{int(pixels.group(1))}*{int(pixels.group(2))}"
        tier = _SIZE_TIERS.get(raw.lower())
        if tier is None:
            # Unknown spelling: leave it to the provider to accept or reject.
            return raw
        if not model.strip().lower().startswith(_TIER_MODEL_PREFIX):
            raise GenerationProviderError(
                f"DashScope model {model} needs an explicit width*height size such as "
                f"1280*1280; the {tier} resolution tiers are wan2.7 only."
            )
        if tier == "4K" and not model.strip().lower().startswith(_PRO_4K_MODEL):
            raise GenerationProviderError(
                f"DashScope model {model} does not support 4K output; 4K text-to-image is "
                "available only on wan2.7-image-pro. Use 1K or 2K, or a width*height size."
            )
        return tier

    @staticmethod
    def _raise_dashscope_error(data: dict[str, Any], action: str) -> None:
        if data.get("code") not in (None, "", 0, "0") or data.get("success") is False:
            code = data.get("code") or "unknown"
            message = data.get("message") or "no detail provided"
            raise GenerationProviderError(f"{action} failed ({code}): {message}")

    @staticmethod
    def _task_id(resp: httpx.Response) -> str:
        data = resp.json()
        if not isinstance(data, dict):
            raise GenerationProviderError("Malformed DashScope image submission response.")
        DashScopeImagegenAdapter._raise_dashscope_error(data, "DashScope image task submission")
        output = data.get("output")
        if isinstance(output, dict) and isinstance(output.get("task_id"), str):
            return output["task_id"]
        raise GenerationProviderError("DashScope image submission returned no task id.")

    @staticmethod
    def _result_urls(output: dict[str, Any]) -> list[str]:
        """Image URLs from a completed task under either protocol's ``output``."""
        results = output.get("results")
        if isinstance(results, list):
            # Legacy text2image: successful entries carry a URL, failed ones a
            # code/message pair.
            urls: list[str] = []
            for item in results:
                url = item.get("url") if isinstance(item, dict) else None
                if isinstance(url, str) and url:
                    urls.append(url)
            if urls:
                return urls
        urls = []
        for choice in output.get("choices") or []:
            message = choice.get("message") if isinstance(choice, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            for part in content or []:
                url = part.get("image") if isinstance(part, dict) else None
                if isinstance(url, str) and url:
                    urls.append(url)
        return urls

    async def _poll(
        self,
        client: httpx.AsyncClient,
        config: ImagegenConfig,
        headers: dict[str, str],
        task_id: str,
    ) -> list[str]:
        poll_url = join_api_path(config.base_url, f"tasks/{task_id}")
        deadline = time.monotonic() + config.poll_timeout
        while True:
            resp = await client.get(poll_url, headers=headers)
            raise_for_provider(resp, "DashScope image task status")
            data = resp.json()
            if not isinstance(data, dict):
                raise GenerationProviderError("Malformed DashScope image task response.")
            self._raise_dashscope_error(data, "DashScope image task status")
            output = data.get("output")
            if not isinstance(output, dict):
                raise GenerationProviderError("Malformed DashScope image task response.")
            status = str(output.get("task_status") or "").lower()
            if status in {"succeeded", "success"}:
                urls = self._result_urls(output)
                if not urls:
                    raise GenerationProviderError(
                        "Successful DashScope image task had no image URLs."
                    )
                return urls
            if status in {"failed", "canceled", "cancelled", "expired", "unknown"}:
                message = output.get("message") or "no detail provided"
                raise GenerationProviderError(f"DashScope image task {status}: {message}")
            if time.monotonic() >= deadline:
                raise GenerationProviderError(
                    f"DashScope image task {task_id} timed out after {config.poll_timeout}s "
                    f"(last status: {status or 'unknown'})."
                )
            await asyncio.sleep(config.poll_interval)

    @staticmethod
    async def _materialize(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
        resp = await client.get(url)
        raise_for_provider(resp, "DashScope image download")
        if not resp.content:
            raise GenerationProviderError("DashScope image download returned empty data.")
        content_type = resp.headers.get("content-type") or "image/png"
        if not content_type.startswith("image/"):
            content_type = "image/png"
        return resp.content, content_type


__all__ = ["DashScopeImagegenAdapter"]
