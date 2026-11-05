"""Build an agent bound to the Settings task model (the fast model for small, targeted calls)."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

A = TypeVar("A")


def task_model_agent(factory: Callable[..., A]) -> A | None:
    """``factory(api_key=, base_url=, api_version=)`` on the task model, at its reasoning level.

    Returns None when no task model is configured or it cannot be resolved, so callers can
    fall back to their main-model agent.
    """
    try:
        from deeptutor.services.config.model_catalog import get_model_catalog_service
        from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
        from deeptutor.services.model_selection.runtime import llm_config_from_resolved
        from deeptutor.services.model_selection.tasks import (
            TASK_SERVICE,
            catalog_for_task,
            task_service_configured,
        )

        catalog = catalog_for_task(get_model_catalog_service().load(), None)
        if not task_service_configured(catalog):
            return None
        config = llm_config_from_resolved(
            resolve_llm_runtime_config(catalog, service_name=TASK_SERVICE)
        )
    except Exception:
        return None
    agent: Any = factory(
        api_key=config.api_key,
        base_url=config.base_url,
        api_version=getattr(config, "api_version", None),
    )
    agent.model = config.model
    agent.binding = getattr(config, "binding", None) or agent.binding
    effort = getattr(config, "reasoning_effort", None)
    if effort:
        stream = agent.stream_llm

        def _stream_llm(*args: Any, reasoning_effort: str | None = None, **kwargs: Any):
            return stream(*args, reasoning_effort=reasoning_effort or effort, **kwargs)

        agent.stream_llm = _stream_llm
    return agent


__all__ = ["task_model_agent"]
