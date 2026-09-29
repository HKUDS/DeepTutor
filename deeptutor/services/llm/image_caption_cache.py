"""Best-effort, workspace-scoped caching for individual image descriptions.

Only successful, nonempty captions are cached. The digest covers the complete
request and model identity; only the digest and caption are written to disk,
never image bytes, prompts, endpoint URLs, headers, or credentials. Removing
``<workspace>/parse_cache/image_captions`` safely discards this derived cache.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import get_path_service

from .client import LLMClient
from .config import LLMConfig, get_llm_config

logger = logging.getLogger(__name__)
_CACHE_VERSION = 1
_CONFIG_FIELDS = (
    "model",
    "api_key",
    "base_url",
    "effective_url",
    "binding",
    "provider_name",
    "provider_mode",
    "api_version",
    "extra_headers",
    "wire_api",
    "api_format",
    "reasoning_effort",
    "context_window",
    "max_tokens",
    "temperature",
)


def _cache_path(client: Any, request: dict[str, str]) -> Path | None:
    config = getattr(client, "config", None)
    if not isinstance(config, LLMConfig):
        # Unknown client adapters must not share an incomplete model identity.
        return None
    try:
        configs = [config]
        if isinstance(client, LLMClient) and type(client).complete is LLMClient.complete:
            # The legacy facade inherits protocol/header defaults from the
            # current runtime config. Isolated clients own their full config.
            configs.append(get_llm_config())
        identity = [{key: getattr(item, key) for key in _CONFIG_FIELDS} for item in configs]
        request_identity = {key: value for key, value in request.items() if key != "image_data"}
        request_identity["image_sha256"] = hashlib.sha256(
            request["image_data"].encode("ascii")
        ).hexdigest()
        payload = json.dumps(
            {"version": _CACHE_VERSION, "config": identity, "request": request_identity},
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        root = get_path_service().get_parse_cache_root() / "image_captions"
        return root / digest[:2] / f"{digest}.json"
    except Exception:  # noqa: BLE001 - inability to cache must not break captioning
        logger.debug("Image caption cache identity unavailable; bypassing cache")
        return None


def _read_caption(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != _CACHE_VERSION:
            return None
        caption = payload.get("caption")
        if isinstance(caption, str) and caption.strip():
            return caption.strip()
    except (OSError, ValueError, UnicodeError):
        # Missing, unreadable, or malformed entries are ordinary cache misses.
        pass
    return None


def _write_caption(path: Path, caption: str) -> None:
    try:
        atomic_write_json(path, {"version": _CACHE_VERSION, "caption": caption})
    except OSError:
        logger.debug("Image caption cache write failed; retaining generated caption")


async def complete_image_caption(
    client: Any,
    prompt: str,
    *,
    system_prompt: str,
    image_data: str,
    image_mime_type: str,
    image_filename: str,
    force: bool = False,
) -> str:
    """Reuse a matching caption, or call the client and cache successful text.

    ``force`` bypasses reads and replaces the matching entry on success.
    Provider errors and cancellation propagate to the caller's existing
    per-image timeout/failure handling. Concurrent misses may both call the
    provider; atomic replacement prevents partially written cache entries.
    """
    request = {
        "prompt": prompt,
        "system_prompt": system_prompt,
        "image_data": image_data,
        "image_mime_type": image_mime_type,
        "image_filename": image_filename,
    }
    path = await asyncio.to_thread(_cache_path, client, request)
    if path is not None and not force:
        cached = await asyncio.to_thread(_read_caption, path)
        if cached is not None:
            return cached
    caption = (await client.complete(**request) or "").strip()
    if path is not None and caption:
        await asyncio.to_thread(_write_caption, path, caption)
    return caption
