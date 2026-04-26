"""Detect or suggest a model context window during settings diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

import aiohttp

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.context_window import (
    coerce_positive_int,
    default_context_window_for_model,
)
from deeptutor.services.llm.utils import build_auth_headers

logger = logging.getLogger(__name__)

_CONTEXT_WINDOW_KEYS = (
    "context_window",
    "context_window_tokens",
    "context_length",
    "max_context_tokens",
    "max_input_tokens",
    "input_token_limit",
    "max_prompt_tokens",
    "max_model_len",
    "max_sequence_length",
)


@dataclass(frozen=True)
class ContextWindowDetectionResult:
    """Structured context-window detection output."""

    context_window: int
    source: str
    detail: str
    detected_at: str


def _model_aliases(model: str) -> set[str]:
    value = (model or "").strip().lower()
    if not value:
        return set()
    aliases = {value}
    if "/" in value:
        aliases.add(value.split("/", 1)[1])
    if ":" in value:
        aliases.add(value.split(":", 1)[1])
    return {item for item in aliases if item}


def _record_identities(item: Mapping[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("id", "model", "name"):
        aliases.update(_model_aliases(str(item.get(key, "") or "")))
    return aliases


def _recursive_context_window(value: Any) -> int | None:
    if isinstance(value, Mapping):
        for key in _CONTEXT_WINDOW_KEYS:
            parsed = coerce_positive_int(value.get(key))
            if parsed is not None:
                return parsed
        for nested in value.values():
            parsed = _recursive_context_window(nested)
            if parsed is not None:
                return parsed
    elif isinstance(value, list):
        for nested in value:
            parsed = _recursive_context_window(nested)
            if parsed is not None:
                return parsed
    return None


def _iter_model_records(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, Mapping):
                yield item
        return
    if not isinstance(payload, Mapping):
        return
    for key in ("data", "models", "result", "items"):
        items = payload.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, Mapping):
                    yield item


def _extract_context_window_from_payload(payload: Any, model: str) -> int | None:
    target_aliases = _model_aliases(model)
    if not target_aliases:
        return None

    exact_matches: list[Mapping[str, Any]] = []
    partial_matches: list[Mapping[str, Any]] = []
    for item in _iter_model_records(payload):
        identities = _record_identities(item)
        if not identities:
            continue
        if identities & target_aliases:
            exact_matches.append(item)
            continue
        if any(
            item_identity.endswith(f"/{alias}") or alias.endswith(f"/{item_identity}")
            for item_identity in identities
            for alias in target_aliases
        ):
            partial_matches.append(item)

    for item in [*exact_matches, *partial_matches]:
        parsed = _recursive_context_window(item)
        if parsed is not None:
            return parsed
    return None


async def _detect_from_models_endpoint(
    llm_config: LLMConfig,
    *,
    on_log: Callable[[str], None] | None = None,
) -> int | None:
    base_url = str(llm_config.base_url or llm_config.effective_url or "").strip()
    if not base_url:
        return None

    url = f"{base_url.rstrip('/')}/models"
    headers = build_auth_headers(llm_config.api_key, llm_config.binding)
    headers.pop("Content-Type", None)

    timeout = aiohttp.ClientTimeout(total=12)
    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            trust_env=True,
        ) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    if on_log is not None:
                        on_log(
                            f"`GET {url}` returned HTTP {response.status}; skipping metadata detection."
                        )
                    return None
                payload = await response.json()
    except Exception as exc:
        logger.debug("Context-window metadata request failed for %s: %s", url, exc)
        if on_log is not None:
            on_log(f"Could not read `{url}` for context-window metadata: {exc}")
        return None

    return _extract_context_window_from_payload(payload, llm_config.model)


async def detect_context_window(
    llm_config: LLMConfig,
    *,
    on_log: Callable[[str], None] | None = None,
) -> ContextWindowDetectionResult:
    """Detect the current model's context window or fall back to the runtime default."""
    detected_at = datetime.now(timezone.utc).isoformat()
    metadata_window = await _detect_from_models_endpoint(llm_config, on_log=on_log)
    if metadata_window is not None:
        return ContextWindowDetectionResult(
            context_window=metadata_window,
            source="metadata",
            detail="Detected from provider `/models` metadata.",
            detected_at=detected_at,
        )

    fallback = default_context_window_for_model(
        model=llm_config.model,
        max_tokens=llm_config.max_tokens,
    )
    return ContextWindowDetectionResult(
        context_window=fallback,
        source="default",
        detail="Provider metadata did not expose a window; using the runtime fallback.",
        detected_at=detected_at,
    )


__all__ = ["ContextWindowDetectionResult", "detect_context_window"]
