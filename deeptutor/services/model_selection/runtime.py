"""Runtime helpers for request-scoped model selection."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from deeptutor.services.config.provider_runtime import ResolvedLLMConfig, resolve_llm_runtime_config
from deeptutor.services.llm import config as llm_config_module
from deeptutor.services.llm.config import LLMConfig

from deeptutor.multi_user.execution_source import (
    ExecutionSource,
    reset_execution_source,
    set_execution_source,
)

_ACTIVE_SOURCE_TOKEN: ContextVar[Token[Any] | None] = ContextVar(
    "deeptutor_llm_source_token", default=None
)


def llm_config_from_resolved(resolved: ResolvedLLMConfig) -> LLMConfig:
    """Convert provider-runtime output into the LLM service config shape."""
    return LLMConfig(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        effective_url=resolved.effective_url,
        binding=resolved.binding,
        provider_name=resolved.provider_name,
        provider_mode=resolved.provider_mode,
        api_version=resolved.api_version,
        extra_headers=resolved.extra_headers,
        reasoning_effort=resolved.reasoning_effort,
        context_window=resolved.context_window,
    )


def resolve_llm_config_for_selection(selection: Any) -> LLMConfig:
    """Resolve the LLM config for a chat/session selection reference."""
    if selection is None:
        from deeptutor.multi_user.context import get_current_user

        if not get_current_user().is_admin:
            from deeptutor.multi_user.model_access import default_llm_selection

            selection = default_llm_selection()
            if selection is None:
                raise PermissionError("No LLM model is assigned to your account.")
    return llm_config_from_resolved(resolve_llm_runtime_config(llm_selection=selection))


def activate_llm_selection(selection: Any) -> tuple[LLMConfig, Token[LLMConfig | None]]:
    """Resolve and install a scoped LLM config for the current async context."""
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.model_access import apply_allowed_llm_selection
    from deeptutor.services.model_selection import LLMSelection

    normalized = LLMSelection.from_payload(selection)
    if normalized is not None and not get_current_user().is_admin:
        normalized = LLMSelection.from_payload(
            apply_allowed_llm_selection(normalized.to_dict())
        )
    if normalized is None and not get_current_user().is_admin:
        from deeptutor.multi_user.model_access import default_llm_selection

        normalized = LLMSelection.from_payload(default_llm_selection())
    config = resolve_llm_config_for_selection(normalized)
    token = llm_config_module.set_scoped_llm_config(config)
    source = normalized or LLMSelection(profile_id="", model_id=None)
    source_token = set_execution_source(
        ExecutionSource(
            source=source.source,
            service="llm",
            user_id=get_current_user().id,
            profile_id=source.profile_id if source.source == "byok" else None,
            profile_generation=source.generation if source.source == "byok" else None,
            usage_origin=source.source,
        )
    )
    _ACTIVE_SOURCE_TOKEN.set(source_token)
    return config, token


def reset_llm_selection(token: Token[LLMConfig | None] | None) -> None:
    if token is not None:
        llm_config_module.reset_scoped_llm_config(token)
    source_token = _ACTIVE_SOURCE_TOKEN.get()
    if source_token is not None:
        reset_execution_source(source_token)
        _ACTIVE_SOURCE_TOKEN.set(None)


__all__ = [
    "activate_llm_selection",
    "llm_config_from_resolved",
    "reset_llm_selection",
    "resolve_llm_config_for_selection",
]
