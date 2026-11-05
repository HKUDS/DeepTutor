"""xAI Grok Imagine video-generation adapter.

xAI uses the same submit → poll → download lifecycle as the generic async-task
adapter, but with different paths and payload shapes:

* ``POST {base}/videos/generations`` → ``{"request_id": ...}``
* ``GET  {base}/videos/{request_id}`` → ``{"status": "done", "video": {"url": ...}}``

Only the provider-specific shaping is overridden; polling and downloading stay
in :class:`AsyncTaskVideogenAdapter`.
"""

from __future__ import annotations

from typing import Any

import httpx

from deeptutor.services.generation_http import GenerationProviderError, join_api_path
from deeptutor.services.videogen.adapters.async_task import AsyncTaskVideogenAdapter
from deeptutor.services.videogen.config import VideogenConfig


class XaiVideogenAdapter(AsyncTaskVideogenAdapter):
    """Submit a Grok Imagine video task, poll it, and download the result."""

    @staticmethod
    def _submit_path() -> str:
        return "videos/generations"

    @staticmethod
    def _status_url(config: VideogenConfig, task_id: str) -> str:
        return join_api_path(config.base_url, f"videos/{task_id}")

    @staticmethod
    def _build_submit_payload(prompt: str, config: VideogenConfig) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": config.model, "prompt": prompt}
        if config.duration:
            try:
                payload["duration"] = int(config.duration)
            except ValueError:
                payload["duration"] = config.duration
        if config.aspect_ratio:
            payload["aspect_ratio"] = config.aspect_ratio
        if config.resolution:
            payload["resolution"] = config.resolution
        return payload

    @staticmethod
    def _extract_task_id(resp: httpx.Response) -> str:
        data = resp.json()
        request_id = data.get("request_id") if isinstance(data, dict) else None
        if not isinstance(request_id, str) or not request_id:
            raise GenerationProviderError("xAI video submission returned no request_id.")
        return request_id

    @staticmethod
    def _extract_status(resp: httpx.Response) -> tuple[str, str, str]:
        data = resp.json()
        if not isinstance(data, dict):
            raise GenerationProviderError("xAI video status returned an invalid payload.")
        status = str(data.get("status") or "")
        video = data.get("video")
        url = video.get("url") if isinstance(video, dict) else None
        error = data.get("error") or data.get("message") or ""
        return status, url if isinstance(url, str) else "", str(error)


__all__ = ["XaiVideogenAdapter"]
