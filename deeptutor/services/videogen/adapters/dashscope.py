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

# Same shape as the image adapter: the submit route is
# ``video-generation/video-synthesis``. Without the trailing segment the
# gateway answers 400 "task can not be null".
_SUBMIT_PATH = "services/aigc/video-generation/video-synthesis"

_SIZES_BY_TIER = {
    "480p": {"16:9": "832*480", "9:16": "480*832", "1:1": "624*624"},
    "720p": {
        "16:9": "1280*720",
        "9:16": "720*1280",
        "1:1": "960*960",
        "4:3": "1088*832",
        "3:4": "832*1088",
    },
    "1080p": {
        "16:9": "1920*1080",
        "9:16": "1080*1920",
        "1:1": "1440*1440",
        "4:3": "1632*1248",
        "3:4": "1248*1632",
    },
}

_MODEL_TIERS = {
    "wanx2.1-t2v-turbo": ("720p", {"480p", "720p"}),
    "wanx2.1-t2v-plus": ("720p", {"720p"}),
    "wan2.2-t2v-plus": ("1080p", {"480p", "720p", "1080p"}),
    "wan2.5-t2v-preview": ("1080p", {"480p", "720p", "1080p"}),
    "wan2.6-t2v": ("1080p", {"720p", "1080p"}),
}
_FIXED_FIVE_SECOND_MODELS = {"wanx2.1-t2v-turbo", "wanx2.1-t2v-plus", "wan2.2-t2v-plus"}


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
        size = DashScopeVideogenAdapter._size(config)
        if size:
            parameters["size"] = size
        if config.duration:
            try:
                duration = int(config.duration)
            except ValueError as exc:
                raise GenerationProviderError(
                    f"Invalid DashScope video duration: {config.duration!r}"
                ) from exc
            if config.model in _FIXED_FIVE_SECOND_MODELS:
                if duration != 5:
                    raise GenerationProviderError(
                        f"DashScope model {config.model} only supports a 5-second video."
                    )
            else:
                parameters["duration"] = duration
        return {
            "model": config.model,
            "input": {"prompt": prompt},
            "parameters": parameters,
        }

    @staticmethod
    def _size(config: VideogenConfig) -> str:
        if not config.resolution and not config.aspect_ratio:
            return ""

        model_sizes = _MODEL_TIERS.get(config.model)
        resolution = config.resolution.strip().lower()
        ratio = config.aspect_ratio.strip() or "16:9"

        # Settings has a shared resolution field: accept either its usual tier
        # ("720p") or DashScope's exact width*height form.
        for tier, sizes in _SIZES_BY_TIER.items():
            if resolution in sizes.values():
                if config.aspect_ratio and sizes.get(ratio) != resolution:
                    raise GenerationProviderError(
                        f"DashScope video size {resolution!r} conflicts with aspect ratio {ratio!r}."
                    )
                selected_tier = tier
                selected_size = resolution
                break
        else:
            selected_tier = resolution or (model_sizes[0] if model_sizes else "")
            if not selected_tier:
                raise GenerationProviderError(
                    f"Set a video resolution when using aspect ratio with DashScope model {config.model}."
                )
            sizes = _SIZES_BY_TIER.get(selected_tier)
            if sizes is None or ratio not in sizes:
                raise GenerationProviderError(
                    f"Unsupported DashScope video resolution/aspect ratio: "
                    f"{selected_tier!r}, {ratio!r}."
                )
            selected_size = sizes[ratio]

        if model_sizes and selected_tier not in model_sizes[1]:
            raise GenerationProviderError(
                f"DashScope model {config.model} does not support {selected_tier} video."
            )
        return selected_size

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
