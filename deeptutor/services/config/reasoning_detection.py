"""Read explicit model reasoning metadata without generation probes or settings writes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp

from deeptutor.core.reasoning_efforts import VALID_REASONING_EFFORTS
from deeptutor.services.keypool import primary_api_key
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.openai_http_client import disable_ssl_verify_enabled
from deeptutor.services.llm.reasoning_params import build_openai_compatible_reasoning_kwargs
from deeptutor.services.llm.utils import build_auth_headers, sanitize_url
from deeptutor.services.model_selection.reasoning import supported_reasoning_efforts
from deeptutor.services.provider_registry import (
    ANTHROPIC_EFFORT_BASED_FAMILIES,
    effective_backend,
    find_by_name,
)


@dataclass(frozen=True)
class ReasoningDetection:
    levels: list[str] | None
    source: str
    detected_at: str
    selectable_levels: list[str] | None = None


def _levels(value: Any) -> list[str] | None:
    if not isinstance(value, list) or len(value) > 64:
        return None
    values = [item.get("effort") if isinstance(item, Mapping) else item for item in value]
    if any(not isinstance(item, str) or not item or len(item) > 128 for item in values):
        return None
    return [level for level in VALID_REASONING_EFFORTS if level in values] + [
        level for level in dict.fromkeys(values) if level not in VALID_REASONING_EFFORTS
    ]


def _record_levels(record: Mapping[str, Any]) -> list[str] | None:
    for key in ("supported_reasoning_efforts", "supported_reasoning_levels"):
        if key in record:
            return _levels(record[key])
    reasoning = record.get("reasoning")
    if isinstance(reasoning, Mapping) and "supported_efforts" in reasoning:
        return _levels(reasoning["supported_efforts"])
    capabilities = record.get("capabilities")
    effort = capabilities.get("effort") if isinstance(capabilities, Mapping) else None
    if isinstance(effort, Mapping):
        if effort.get("supported") is False:
            thinking = capabilities.get("thinking")
            return (
                [] if isinstance(thinking, Mapping) and thinking.get("supported") is False else None
            )
        if effort.get("supported") is True:
            return (
                _levels(
                    [
                        level
                        for level, support in effort.items()
                        if isinstance(support, Mapping) and support.get("supported") is True
                    ]
                )
                or None
            )
    return None


def extract_reasoning_levels(
    payload: Any, model: str, *, resolved_model: bool = False
) -> list[str] | None:
    """Match list entries exactly; a single-model endpoint may resolve an alias."""
    if not isinstance(payload, Mapping):
        return None
    if resolved_model and isinstance(payload.get("id"), str) and payload["id"]:
        return _record_levels(payload)
    records = payload.get("data", payload.get("models", [payload]))
    if not isinstance(records, list):
        return None
    matches = [
        item
        for item in records
        if isinstance(item, Mapping) and item.get("id", item.get("slug")) == model
    ]
    if not matches:
        return None
    results = [_record_levels(item) for item in matches]
    return results[0] if all(result == results[0] for result in results) else None


def compatible_reasoning_levels(config: LLMConfig, levels: list[str] | None) -> list[str] | None:
    if not levels:
        return levels
    spec = find_by_name(config.binding)
    if effective_backend(spec, config.api_format) == "anthropic":
        return [level for level in levels if level in {"low", "medium", "high", "xhigh", "max"}]
    if config.api_format == "openai_responses" or config.wire_api == "responses":
        # The Responses adapter currently omits reasoning for `none`.
        return [level for level in levels if level in VALID_REASONING_EFFORTS and level != "none"]
    allowed = supported_reasoning_efforts(
        config.binding, config.model, metadata={"codex_supported_reasoning_levels": levels}
    )
    # Do not offer several distinct labels for a transport's one binary switch.
    selectable = []
    for level in levels:
        if level not in VALID_REASONING_EFFORTS or level not in allowed:
            continue
        mapped = build_openai_compatible_reasoning_kwargs(
            spec=spec, binding=config.binding, model=config.model, reasoning_effort=level
        )
        if mapped and mapped.get("reasoning_effort", level) == level:
            selectable.append(level)
    return selectable


async def detect_reasoning_levels(
    config: LLMConfig, model: Mapping[str, Any] | None = None
) -> ReasoningDetection:
    detected_at = datetime.now(timezone.utc).isoformat()
    model = model or {}
    if config.binding == "openai_codex":
        levels = _levels(model.get("codex_supported_reasoning_levels"))
        return ReasoningDetection(
            levels,
            "managed_catalog" if levels is not None else "unknown",
            detected_at,
            [level for level in levels if level in VALID_REASONING_EFFORTS]
            if levels is not None
            else None,
        )

    spec = find_by_name(config.binding)
    if spec and spec.is_oauth:
        return ReasoningDetection(None, "unknown", detected_at)
    # Other native protocols need their own metadata reader; do not guess
    # endpoints or forward their credentials to an OpenAI-compatible route.
    backend = effective_backend(spec, config.api_format)
    if backend not in {"openai_compat", "anthropic"}:
        return ReasoningDetection(None, "unknown", detected_at)
    base = sanitize_url(config.base_url or config.effective_url or "").rstrip("/")
    if not base:
        return ReasoningDetection(None, "unknown", detected_at)
    # The standard OpenAI Models API exposes identity, not effort levels.
    if spec and spec.name == "openai" and urlsplit(base).hostname == "api.openai.com":
        return ReasoningDetection(None, "unknown", detected_at)
    anthropic = backend == "anthropic"
    # Older/unknown Anthropic families use budget-based thinking. Their effort
    # metadata cannot describe the controls our adapter actually sends.
    if anthropic and not any(
        family in config.model.lower() for family in ANTHROPIC_EFFORT_BASED_FAMILIES
    ):
        return ReasoningDetection(None, "unknown", detected_at)
    request_model = config.model
    if anthropic:
        # Match the SDK adapter: normalize /v1 once and strip only its known prefix.
        if base.endswith("/v1"):
            base = base[:-3]
        request_model = request_model.removeprefix("anthropic/")
        url = f"{base}/v1/models/{quote(request_model, safe='')}"
    else:
        url = f"{base}/models"
    headers = build_auth_headers(
        primary_api_key(config.api_key), "anthropic" if anthropic else config.binding
    )
    headers.update(config.extra_headers or {})
    connector = aiohttp.TCPConnector(ssl=False) if disable_ssl_verify_enabled() else None
    levels = None
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=12), connector=connector, trust_env=True
        ) as session:
            # Never follow redirects with provider credentials. Bound responses
            # and leave an unavailable/malformed catalog as unknown, not unsupported.
            async with session.get(url, headers=headers, allow_redirects=False) as response:
                if response.status == 200:
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        raw.extend(chunk)
                        if len(raw) > 2_000_000:
                            break
                    if len(raw) <= 2_000_000:
                        levels = extract_reasoning_levels(
                            json.loads(raw), request_model, resolved_model=anthropic
                        )
    except (aiohttp.ClientError, TimeoutError, ValueError, RecursionError):
        pass
    return ReasoningDetection(
        levels,
        "provider_metadata" if levels is not None else "unknown",
        detected_at,
        compatible_reasoning_levels(config, levels),
    )
