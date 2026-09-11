"""Aliyun DashScope native text-to-image adapter."""

from __future__ import annotations

import asyncio
import logging
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

_SUBMIT_PATH = "services/aigc/image-synthesis"


class DashScopeImagegenAdapter(BaseImagegenAdapter):
    """Submit a DashScope image task, poll it, and materialize image bytes."""

    async def generate(
        self, prompt: str, config: ImagegenConfig, *, n: int = 1
    ) -> list[tuple[bytes, str]]:
        if not config.base_url:
            raise GenerationProviderError("No endpoint URL configured for image generation.")
        headers = self._headers(config)
        payload = self._submit_payload(prompt, config, n=max(1, n))
        submit_url = join_api_path(config.base_url, _SUBMIT_PATH)
        logger.debug("DashScope image submit url=%s model=%s", submit_url, config.model)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(submit_url, headers=headers, json=payload)
                raise_for_provider(resp, "DashScope image task submission")
                task_id = self._task_id(resp)
                results = await self._poll(client, config, headers, task_id)
                images = []
                for result in results:
                    images.append(await self._materialize(client, result))
        except httpx.HTTPError as exc:
            raise GenerationProviderError(f"DashScope image request error: {exc}") from exc
        if not images:
            raise GenerationProviderError("DashScope image task returned no images.")
        return images

    @staticmethod
    def _headers(config: ImagegenConfig) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }

    @staticmethod
    def _submit_payload(prompt: str, config: ImagegenConfig, *, n: int) -> dict[str, Any]:
        parameters: dict[str, Any] = {"n": max(1, n)}
        if config.size:
            parameters["size"] = config.size.lower().replace("x", "*")
        if config.style:
            parameters["style"] = config.style
        return {
            "model": config.model,
            "input": {"prompt": prompt},
            "parameters": parameters,
        }

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

    async def _poll(
        self,
        client: httpx.AsyncClient,
        config: ImagegenConfig,
        headers: dict[str, str],
        task_id: str,
    ) -> list[dict[str, Any]]:
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
                results = output.get("results")
                if not isinstance(results, list):
                    raise GenerationProviderError("Successful DashScope image task had no results.")
                return [item for item in results if isinstance(item, dict)]
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
    async def _materialize(client: httpx.AsyncClient, result: dict[str, Any]) -> tuple[bytes, str]:
        url = result.get("url")
        if not isinstance(url, str) or not url:
            raise GenerationProviderError("DashScope image result had no URL.")
        resp = await client.get(url)
        raise_for_provider(resp, "DashScope image download")
        if not resp.content:
            raise GenerationProviderError("DashScope image download returned empty data.")
        content_type = resp.headers.get("content-type") or "image/png"
        if not content_type.startswith("image/"):
            content_type = "image/png"
        return resp.content, content_type


__all__ = ["DashScopeImagegenAdapter"]
