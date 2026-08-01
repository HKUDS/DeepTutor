"""Resolve DeepTutor model bindings at the GraphRAG/LiteLLM boundary."""

from __future__ import annotations

from typing import Any

from deeptutor.services.llm.reasoning_params import build_openai_compatible_reasoning_kwargs
from deeptutor.services.provider_registry import find_by_name, strip_provider_prefix

from .errors import GraphRagUnsupportedProviderError

COMPLETION_TYPE = "deeptutor_litellm"


def _runtime_binding(llm_cfg: Any) -> str:
    return str(
        getattr(llm_cfg, "binding", None) or getattr(llm_cfg, "provider_name", None) or "openai"
    ).strip()


def resolve_completion_provider(llm_cfg: Any) -> str:
    """Map a resolved DeepTutor provider to the narrow LiteLLM transport GraphRAG needs."""
    binding = _runtime_binding(llm_cfg)
    spec = find_by_name(binding)
    if spec is None:
        return "openai"
    if spec.backend == "anthropic":
        return "anthropic"
    if spec.backend == "azure_openai":
        return "azure"
    if spec.backend in {"openai_codex", "github_copilot"} or spec.is_oauth:
        raise GraphRagUnsupportedProviderError(
            "GraphRAG cannot use this OAuth-only model provider. Choose an API-key profile."
        )
    if spec.backend == "openai_compat":
        # DeepSeek's LiteLLM provider owns its parameter compatibility logic.
        # Other DeepTutor OpenAI-compatible profiles already expose an OpenAI
        # chat-completions endpoint and are safest on the generic transport.
        return "deepseek" if spec.name == "deepseek" else "openai"
    raise GraphRagUnsupportedProviderError(
        "GraphRAG does not support the selected model provider transport."
    )


def resolve_completion_model(llm_cfg: Any) -> str:
    """Return the model identifier expected by the selected LiteLLM transport."""
    model = str(getattr(llm_cfg, "model", "") or "")
    spec = find_by_name(_runtime_binding(llm_cfg))
    return strip_provider_prefix(model, spec)


def resolve_completion_call_args(llm_cfg: Any) -> dict[str, Any]:
    """Return the request options shared by GraphRAG probes and indexing."""
    call_args: dict[str, Any] = {}
    extra_headers = getattr(llm_cfg, "extra_headers", None)
    if isinstance(extra_headers, dict) and extra_headers:
        call_args["extra_headers"] = dict(extra_headers)

    binding = _runtime_binding(llm_cfg)
    spec = find_by_name(binding)
    reasoning_effort = getattr(llm_cfg, "reasoning_effort", None)
    if spec is not None and spec.backend == "openai_compat":
        call_args.update(
            build_openai_compatible_reasoning_kwargs(
                spec=spec,
                binding=binding,
                model=resolve_completion_model(llm_cfg),
                reasoning_effort=reasoning_effort,
            )
        )
    elif reasoning_effort:
        # Preserve the existing GraphRAG behavior for Anthropic, Azure, and
        # unknown transports; the OpenAI-compatible normalizer is not valid for
        # those backends.
        call_args["reasoning_effort"] = reasoning_effort
    return call_args


def resolve_persisted_completion_provider(model_config: Any) -> str:
    """Recover a provider for old DeepTutor GraphRAG settings without rewriting them."""
    current = str(getattr(model_config, "model_provider", "") or "openai")
    if current != "openai":
        return current

    model = str(getattr(model_config, "model", "") or "")
    api_base = str(getattr(model_config, "api_base", "") or "").rstrip("/")
    try:
        from deeptutor.services.config import (
            get_model_catalog_service,
            resolve_llm_runtime_config,
        )

        service = get_model_catalog_service()
        catalog = service.load()
        profiles = catalog.get("services", {}).get("llm", {}).get("profiles", [])
        matches: list[tuple[str, str]] = []
        for profile in profiles:
            profile_base = str(profile.get("base_url") or "").rstrip("/")
            if profile_base != api_base:
                continue
            for candidate in profile.get("models", []):
                if str(candidate.get("model") or "") == model:
                    matches.append((str(profile.get("id") or ""), str(candidate.get("id") or "")))
        if len(matches) == 1:
            profile_id, model_id = matches[0]
            resolved = resolve_llm_runtime_config(
                catalog=catalog,
                service=service,
                llm_selection={"profile_id": profile_id, "model_id": model_id},
            )
            return resolve_completion_provider(resolved)
    except GraphRagUnsupportedProviderError:
        raise
    except Exception:
        # Old settings remain usable even when the catalog is unavailable.
        pass

    if "api.deepseek.com" in api_base.lower():
        return "deepseek"
    return current


__all__ = [
    "COMPLETION_TYPE",
    "resolve_completion_call_args",
    "resolve_completion_model",
    "resolve_completion_provider",
    "resolve_persisted_completion_provider",
]
