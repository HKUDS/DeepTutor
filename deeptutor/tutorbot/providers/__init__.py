"""LLM provider abstraction module."""

from deeptutor.tutorbot.providers.base import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse", "LiteLLMProvider"]


def __getattr__(name: str):
    if name == "LiteLLMProvider":
        from deeptutor.tutorbot.providers.litellm_provider import LiteLLMProvider
        return LiteLLMProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
