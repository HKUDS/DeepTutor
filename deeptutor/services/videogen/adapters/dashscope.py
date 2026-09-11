"""Aliyun DashScope native text-to-video adapter."""

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
from deeptutor.services.videogen.base import BaseVideogenAdapter, ProgressFn
from deeptutor.services.videogen.config import VideogenConfig

logger = logging.getLogger(__name__)

_SUBMIT_PATH = "services/aigc/video-generation"


class DashScopeVideogenAdapter(BaseVideogenAdapter):
    """Run a DashScope video-generation task and download the rendered file."""

    async def submit_task(self, prompt: str, config: VideogenConfig) -> str:
        if not config.base_url:
            raise GenerationProviderError("No endpoint URL configured for video generation.")
        submit_url = join_api_path(config.base_url, _SUBMIT_PATH)
        logger.debug("DashScope video submit url=%s model=%s", submit_url, config.model)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(
                    submit_url, headers=self._headers(config), json=self._payload(prompt, config)
                )
                raise_for_provider(resp, "DashScope video task submission")
                return self._task_id(resp)
        except httpx.HTTPError as exc:
            raise GenerationProviderError(f"DashScope video submission error: {exc}") from exc

    async def generate(
        self,
        prompt: str,
        config: VideogenConfig,
        *,
        progress: ProgressFn | None = None,
    ) -> tuple[bytes, str]:
        task_id = await self.submit_task(prompt, config)
        await self._notify(progress, f"Submitted DashScope video task (id={task_id}).")
        headers = self._headers(config)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                video_url = await self._poll(client, config, headers, task_id, progress)
                await self._notify(progress, "Downloading rendered DashScope video...")
                resp = await client.get(video_url)
                raise_for_provider(resp, "DashScope video download")
        except httpx.HTTPError as exc:
            raise GenerationProviderError(f"DashScope video request error: {exc}") from exc
        if not resp.content:
            raise GenerationProviderError("DashScope video download returned empty data.")
        content_type = resp.headers.get("content-type") or "video/mp4"
        if not content_type.startswith("video/"):
            content_type = "video/mp4"
        return resp.content, content_type

    @staticmethod
    def _headers(config: VideogenConfig) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }

    @staticmethod
    def _payload(prompt: str, config: VideogenConfig) -> dict[str, Any]:
        parameters: dict[str, Any] = {}
        if config.aspect_ratio:
            parameters["ratio"] = config.aspect_ratio
        if config.duration:
            try:
                parameters["duration"] = int(config.duration)
            except ValueError as exc:
                raise GenerationProviderError(
                    f"Invalid DashScope video duration: {config.duration!r}"
                ) from exc
        if config.resolution:
            parameters["resolution"] = config.resolution
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
            raise GenerationProviderError("Malformed DashScope video submission response.")
        DashScopeVideogenAdapter._raise_dashscope_error(data, "DashScope video task submission")
        output = data.get("output")
        if isinstance(output, dict) and isinstance(output.get("task_id"), str):
            return output["task_id"]
        raise GenerationProviderError("DashScope video submission returned no task id.")

    async def _poll(
        self,
        client: httpx.AsyncClient,
        config: VideogenConfig,
        headers: dict[str, str],
        task_id: str,
        progress: ProgressFn | None,
    ) -> str:
        poll_url = join_api_path(config.base_url, f"tasks/{task_id}")
        deadline = time.monotonic() + config.poll_timeout
        polls = 0
        while True:
            resp = await client.get(poll_url, headers=headers)
            raise_for_provider(resp, "DashScope video task status")
            data = resp.json()
            if not isinstance(data, dict):
                raise GenerationProviderError("Malformed DashScope video task response.")
            self._raise_dashscope_error(data, "DashScope video task status")
            output = data.get("output")
            if not isinstance(output, dict):
                raise GenerationProviderError("Malformed DashScope video task response.")
            status = str(output.get("task_status") or "").lower()
            video_url = output.get("video_url")
            if status in {"succeeded", "success"}:
                if not isinstance(video_url, str) or not video_url:
                    raise GenerationProviderError("Successful DashScope video task had no URL.")
                return video_url
            if status in {"failed", "canceled", "cancelled", "expired", "unknown"}:
                message = output.get("message") or "no detail provided"
                raise GenerationProviderError(f"DashScope video task {status}: {message}")
            if time.monotonic() >= deadline:
                raise GenerationProviderError(
                    f"DashScope video task {task_id} timed out after {config.poll_timeout}s "
                    f"(last status: {status or 'unknown'})."
                )
            polls += 1
            if polls % 3 == 0:
                await self._notify(
                    progress, f"Still rendering video... (status: {status or 'pending'})"
                )
            await asyncio.sleep(config.poll_interval)

    @staticmethod
    async def _notify(progress: ProgressFn | None, message: str) -> None:
        if progress is not None:
            await progress(message)


__all__ = ["DashScopeVideogenAdapter"]
