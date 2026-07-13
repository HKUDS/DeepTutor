"""
LLM Client
==========

Unified LLM client for all DeepTutor services.

Note: This is a legacy interface. Prefer using the factory functions directly:
    from deeptutor.services.llm import complete, stream
"""

from collections.abc import Awaitable, Callable
import logging
from typing import Any, cast

from .capabilities import supports_vision
from .config import LLMConfig, get_llm_config
from .utils import sanitize_url


class LLMClient:
    """
    Unified LLM client for all services.

    Wraps the LLM Factory with a class-based interface.
    Prefer using factory functions (complete, stream) directly for new code.
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        """
        Initialize LLM client.

        Args:
            config: LLM configuration. If None, loads from environment.
        """

        self.config = config or get_llm_config()
        self.logger = logging.getLogger(__name__)

        # Keep OPENAI_* env vars aligned for libraries that still read from env.
        self._setup_openai_env_vars()

    def _setup_openai_env_vars(self) -> None:
        """
        Set OpenAI environment variables for compatibility with OpenAI-style SDKs.
        """
        import os

        binding = getattr(self.config, "binding", "openai")

        # Only set env vars for OpenAI-compatible bindings
        if binding in ("openai", "azure_openai", "gemini"):
            if self.config.api_key:
                os.environ["OPENAI_API_KEY"] = self.config.api_key
                self.logger.debug("Set OPENAI_API_KEY env var")

            if self.config.base_url:
                from .utils import sanitize_url as _sanitize

                clean_url = _sanitize(self.config.base_url)
                os.environ["OPENAI_BASE_URL"] = clean_url
                self.logger.debug(f"Set OPENAI_BASE_URL env var to {clean_url}")

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: object,
    ) -> str:
        """
        Call LLM completion via Factory.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            history: Optional conversation history
            **kwargs: Additional arguments passed to the API

        Returns:
            LLM response text
        """
        from . import factory

        factory_complete = cast(Callable[..., Awaitable[str]], factory.complete)
        messages = history or None
        return await factory_complete(
            prompt=prompt,
            system_prompt=system_prompt or "You are a helpful assistant.",
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            api_version=getattr(self.config, "api_version", None),
            binding=getattr(self.config, "binding", "openai"),
            reasoning_effort=getattr(self.config, "reasoning_effort", None),
            extra_headers=getattr(self.config, "extra_headers", None),
            messages=messages,
            **kwargs,
        )

    def complete_sync(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: object,
    ) -> str:
        """
        Synchronous wrapper for complete().

        Use this when you need to call from non-async context.
        """
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop -> safe to run synchronously.
            return asyncio.run(self.complete(prompt, system_prompt, history, **kwargs))

        raise RuntimeError(
            "LLMClient.complete_sync() cannot be called from a running event loop. "
            "Use `await llm.complete(...)` instead."
        )

    def get_model_func(self) -> Callable[..., object]:
        """
        Get an async callable compatible with generic llm_model_func hooks.

        Returns:
            Callable that can be used as llm_model_func
        """
        return self._build_factory_model_func(allow_multimodal=False)

    def get_vision_model_func(self) -> Callable[..., object]:
        """
        Get an async callable compatible with vision_model_func hooks.

        Returns:
            Callable that can be used as vision_model_func
        """
        return self._build_factory_model_func(allow_multimodal=True)

    def supports_multimodal_images(self) -> bool:
        """Return whether the configured LLM can accept image input."""
        return supports_vision(getattr(self.config, "binding", "openai"), self.config.model)

    def _build_factory_model_func(self, allow_multimodal: bool) -> Callable[..., object]:
        """Build adapter callables on top of the unified factory.complete API."""
        from . import factory

        def _resolve_messages(
            prompt: str,
            system_prompt: str | None,
            history_messages: list[dict[str, object]] | None,
            messages: list[dict[str, object]] | None,
        ) -> list[dict[str, Any]] | None:
            if messages:
                return cast(list[dict[str, Any]], messages)
            if not history_messages:
                return None

            full_messages: list[dict[str, Any]] = []
            if system_prompt and not (
                history_messages and history_messages[0].get("role") == "system"
            ):
                full_messages.append({"role": "system", "content": system_prompt})
            full_messages.extend(cast(list[dict[str, Any]], history_messages))
            if prompt:
                full_messages.append({"role": "user", "content": prompt})
            return full_messages or None

        async def model_func(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, object]] | None = None,
            image_data: str | None = None,
            messages: list[dict[str, object]] | None = None,
            **kwargs: object,
        ) -> str:
            payload_kwargs: dict[str, object] = dict(kwargs)

            # Normalize aliases from legacy callsites.
            payload_kwargs.pop("history_messages", None)
            payload_kwargs.pop("messages", None)
            payload_kwargs.pop("prompt", None)
            payload_kwargs.pop("system_prompt", None)

            default_system_prompt = system_prompt or "You are a helpful assistant."
            resolved_messages = _resolve_messages(
                prompt,
                default_system_prompt,
                history_messages,
                messages,
            )

            if allow_multimodal and image_data is not None:
                payload_kwargs["image_data"] = image_data

            factory_complete = cast(Callable[..., Awaitable[str]], factory.complete)
            return await factory_complete(
                prompt=prompt,
                system_prompt=default_system_prompt,
                model=self.config.model,
                api_key=self.config.api_key,
                base_url=sanitize_url(self.config.base_url) if self.config.base_url else None,
                api_version=getattr(self.config, "api_version", None),
                binding=getattr(self.config, "binding", "openai"),
                reasoning_effort=getattr(self.config, "reasoning_effort", None),
                extra_headers=getattr(self.config, "extra_headers", None),
                messages=resolved_messages,
                **payload_kwargs,
            )

        return model_func


_client: LLMClient | None = None


def get_llm_client(config: LLMConfig | None = None) -> LLMClient:
    """
    Get or create the singleton LLM client.

    Args:
        config: Optional configuration. Only used on first call.

    Returns:
        LLMClient instance
    """
    global _client
    if _client is None:
        _client = LLMClient(config)
    return _client


def reset_llm_client() -> None:
    """Reset the singleton LLM client."""
    global _client
    _client = None
