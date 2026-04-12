"""LLM provider adapter that reuses DeepTutor's LLM configuration.

When TutorBot runs in-process inside the DeepTutor server, this provider
reads api_key / model / base_url from DeepTutor's unified config and
delegates to the standard LiteLLMProvider, avoiding duplicate configuration.
"""

from __future__ import annotations

from deeptutor.tutorbot.providers.litellm_provider import LiteLLMProvider


def create_deeptutor_provider() -> LiteLLMProvider:
    """Build a LiteLLMProvider pre-configured from DeepTutor's LLMConfig."""
    from deeptutor.services.llm.config import get_llm_config

    cfg = get_llm_config()
    return LiteLLMProvider(
        api_key=cfg.api_key or None,
        api_base=cfg.effective_url or cfg.base_url or None,
        default_model=cfg.model,
        extra_headers=cfg.extra_headers or {},
        provider_name=cfg.provider_name or None,
    )
