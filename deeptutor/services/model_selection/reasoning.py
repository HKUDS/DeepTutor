"""Reasoning choices accepted by the existing catalog-selection call path.

Managed catalog declarations take precedence over family defaults. Keep the
family defaults aligned with web/lib/reasoning-effort.ts; LightRAG consumes the
returned choices for both validation and its selectors.
"""

from __future__ import annotations

from typing import Any

from .llm import VALID_REASONING_EFFORTS


def supported_reasoning_efforts(
    binding: str, model: str, *, metadata: dict[str, Any] | None = None
) -> list[str]:
    metadata = metadata or {}
    declared = metadata.get("codex_supported_reasoning_levels")
    if isinstance(declared, list):
        return [level for level in (*VALID_REASONING_EFFORTS, "adaptive") if level in declared]
    capabilities = metadata.get("capabilities") or {}
    if capabilities.get("reasoning") is False:
        return []
    provider = binding.lower().replace("-", "_")
    provider = {
        "azure": "azure_openai",
        "azureopenai": "azure_openai",
        "google": "gemini",
        "google_genai": "gemini",
        "claude": "anthropic",
        "openai_compatible": "custom",
        "anthropic_compatible": "custom_anthropic",
    }.get(provider, provider)
    name = model.lower()
    levels: list[str] = []
    if provider == "gemini" or "gemini" in name:
        if "gemini-3" in name or "gemini-2.5-pro" in name:
            levels = ["minimal", "low", "medium", "high"]
        elif "gemini-2.5" in name:
            levels = ["none", "low", "medium", "high"]
        else:
            levels = ["low", "medium", "high"]
    elif provider in {"anthropic", "custom_anthropic"} or "claude" in name:
        if any(
            part in name
            for part in ("opus-4-7", "opus-4-8", "opus-5", "sonnet-5", "fable-5", "mythos-5")
        ):
            levels = ["none", "adaptive"]
        elif any(
            part in name
            for part in (
                "claude-3-7",
                "claude-4",
                "claude-sonnet-4",
                "claude-opus-4",
                "claude-haiku-4",
            )
        ):
            levels = ["none", "low", "medium", "high"]
    elif provider == "custom":
        levels = ["none", "low", "medium", "high"]
    elif provider in {
        "deepseek",
        "volcengine",
        "volcengine_coding_plan",
        "byteplus",
        "byteplus_coding_plan",
        "dashscope",
        "minimax",
    }:
        if provider == "minimax" or any(
            part in name
            for part in (
                "deepseek-reasoner",
                "deepseek-v4-pro",
                "qwen3",
                "qwen-3",
                "qwq",
                "qwen-plus",
            )
        ):
            levels = ["minimal", "high"]
    elif provider in {"openai", "azure_openai", "openai_codex", "github_copilot"}:
        if "gpt-5.6-sol" in name:
            levels = ["none", "low", "medium", "high", "xhigh", "max"]
        elif "gpt-5" in name or "codex" in name:
            levels = ["minimal", "low", "medium", "high", "xhigh"]
        elif any(part in name for part in ("o1", "o3", "o4")):
            levels = ["low", "medium", "high"]
    if not levels and capabilities.get("reasoning") is True:
        levels = ["none", "low", "medium", "high"]
    return levels
