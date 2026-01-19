# -*- coding: utf-8 -*-
"""
LLM Client
==========

Unified LLM client for all DeepTutor services.

Note: This is a legacy interface. Prefer using the factory functions directly:
    from src.services.llm import complete, stream
"""

from typing import Any, Dict, List, Optional

from src.logging import get_logger

from .capabilities import system_in_messages
from .config import LLMConfig, get_llm_config


class LLMClient:
    """
    Unified LLM client for all services.

    Wraps the LLM Factory with a class-based interface.
    Prefer using factory functions (complete, stream) directly for new code.
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        """
        Initialize LLM client.

        Args:
            config: LLM configuration. If None, loads from environment.
        """

        self.config = config or get_llm_config()
        self.logger = get_logger("LLMClient")

        # Set environment variables for LightRAG compatibility
        # LightRAG's internal functions (openai_complete_if_cache, etc.) read from
        # os.environ["OPENAI_API_KEY"] even when api_key is passed as parameter.
        # We must set these env vars early to ensure all LightRAG operations work.
        self._setup_openai_env_vars()

    def _setup_openai_env_vars(self):
        """
        Set OpenAI environment variables for LightRAG compatibility.

        LightRAG's internal functions read from os.environ["OPENAI_API_KEY"]
        even when api_key is passed as parameter. This method ensures the
        environment variables are set for all LightRAG operations.
        """
        import os

        binding = getattr(self.config, "binding", "openai")

        # Only set env vars for OpenAI-compatible bindings
        if binding in ("openai", "azure_openai", "gemini"):
            if self.config.api_key:
                os.environ["OPENAI_API_KEY"] = self.config.api_key
                self.logger.debug("Set OPENAI_API_KEY env var for LightRAG compatibility")

            if self.config.base_url:
                os.environ["OPENAI_BASE_URL"] = self.config.base_url
                self.logger.debug(f"Set OPENAI_BASE_URL env var to {self.config.base_url}")

    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        **kwargs: Any,
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

        # Delegate to factory for unified routing and retry handling
        return await factory.complete(
            prompt=prompt,
            system_prompt=system_prompt or "You are a helpful assistant.",
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            api_version=getattr(self.config, "api_version", None),
            binding=getattr(self.config, "binding", "openai"),
            **kwargs,
        )

    def complete_sync(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        **kwargs: Any,
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

    def get_model_func(self):
        """
        Get a function compatible with LightRAG's llm_model_func parameter.

        Returns:
            Callable that can be used as llm_model_func
        """
        binding = getattr(self.config, "binding", "openai")

        # Use capabilities to determine if provider uses OpenAI-style messages
        uses_openai_style = system_in_messages(binding, self.config.model)

        # For non-OpenAI-compatible providers (e.g., Anthropic), use Factory
        if not uses_openai_style:
            from . import factory

            def llm_model_func_via_factory(
                prompt: str,
                system_prompt: Optional[str] = None,
                history_messages: Optional[List[Dict]] = None,
                **kwargs: Any,
            ):
                return factory.complete(
                    prompt=prompt,
                    system_prompt=system_prompt or "You are a helpful assistant.",
                    model=self.config.model,
                    api_key=self.config.api_key,
                    base_url=self.config.base_url,
                    binding=binding,
                    history_messages=history_messages,
                    **kwargs,
                )

            return llm_model_func_via_factory

        # OpenAI-compatible bindings use lightrag (has caching)
        # Note: Environment variables are already set in __init__ via _setup_openai_env_vars()
        from lightrag.llm.openai import openai_complete_if_cache

        def llm_model_func(
            prompt: str,
            system_prompt: Optional[str] = None,
            history_messages: Optional[List[Dict]] = None,
            **kwargs: Any,
        ):
            # Only pass api_version if set (for Azure OpenAI)
            lightrag_kwargs = {
                "system_prompt": system_prompt,
                "history_messages": history_messages or [],
                "api_key": self.config.api_key,
                "base_url": self.config.base_url,
                **kwargs,
            }
            api_version = getattr(self.config, "api_version", None)
            if api_version:
                lightrag_kwargs["api_version"] = api_version
            return openai_complete_if_cache(
                self.config.model,
                prompt,
                **lightrag_kwargs,
            )

        return llm_model_func

    def get_vision_model_func(self):
        """
        Get a function compatible with RAG-Anything's vision_model_func parameter.

        Returns:
            Callable that can be used as vision_model_func
        """
        binding = getattr(self.config, "binding", "openai")

        # Use capabilities to determine if provider uses OpenAI-style messages
        uses_openai_style = system_in_messages(binding, self.config.model)

        # For non-OpenAI-compatible providers, use Factory
        if not uses_openai_style:
            from . import factory

            def vision_model_func_via_factory(
                prompt: str,
                system_prompt: Optional[str] = None,
                history_messages: Optional[List[Dict]] = None,
                image_data: Optional[str] = None,
                messages: Optional[List[Dict]] = None,
                **kwargs: Any,
            ):
                # Use factory for unified handling
                return factory.complete(
                    prompt=prompt,
                    system_prompt=system_prompt or "You are a helpful assistant.",
                    model=self.config.model,
                    api_key=self.config.api_key,
                    base_url=self.config.base_url,
                    binding=binding,
                    messages=messages,
                    history_messages=history_messages,
                    image_data=image_data,
                    **kwargs,
                )

            return vision_model_func_via_factory

        # OpenAI-compatible bindings
        # Note: Environment variables are already set in __init__ via _setup_openai_env_vars()
        from lightrag.llm.openai import openai_complete_if_cache

        # Get api_version once for reuse
        api_version = getattr(self.config, "api_version", None)

        def vision_model_func(
            prompt: str,
            system_prompt: Optional[str] = None,
            history_messages: Optional[List[Dict]] = None,
            image_data: Optional[str] = None,
            messages: Optional[List[Dict]] = None,
            **kwargs: Any,
        ):
            # Handle multimodal messages
            if messages:
                clean_kwargs = {
                    k: v
                    for k, v in kwargs.items()
                    if k not in ["messages", "prompt", "system_prompt", "history_messages"]
                }
                lightrag_kwargs = {
                    "messages": messages,
                    "api_key": self.config.api_key,
                    "base_url": self.config.base_url,
                    **clean_kwargs,
                }
                if api_version:
                    lightrag_kwargs["api_version"] = api_version
                return openai_complete_if_cache(
                    self.config.model,
                    prompt="",
                    **lightrag_kwargs,
                )

            # Handle image data
            if image_data:
                # Build image message
                image_message = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                        },
                    ],
                }
                lightrag_kwargs = {
                    "messages": [image_message],
                    "api_key": self.config.api_key,
                    "base_url": self.config.base_url,
                    **kwargs,
                }
                if api_version:
                    lightrag_kwargs["api_version"] = api_version
                return openai_complete_if_cache(
                    self.config.model,
                    prompt="",
                    **lightrag_kwargs,
                )

            # Fallback to regular completion
            lightrag_kwargs = {
                "system_prompt": system_prompt,
                "history_messages": history_messages or [],
                "api_key": self.config.api_key,
                "base_url": self.config.base_url,
                **kwargs,
            }
            if api_version:
                lightrag_kwargs["api_version"] = api_version
            return openai_complete_if_cache(
                self.config.model,
                prompt,
                **lightrag_kwargs,
            )

        return vision_model_func


# Singleton instance
_client: Optional[LLMClient] = None


def get_llm_client(config: Optional[LLMConfig] = None) -> LLMClient:
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


def reset_llm_client():
    """Reset the singleton LLM client."""
    global _client
    _client = None
