"""Route local RAG SDK completions through DeepTutor's OAuth providers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.paths import user_context
from deeptutor.services.provider_registry import find_by_name

if TYPE_CHECKING:
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.services.llm.config import LLMConfig

OAUTH_PROVIDER = "deeptutor_oauth"
_REGISTRATION_LOCK = Lock()


def oauth_binding(config: Any) -> str | None:
    """Return the canonical binding for a provider managed by DeepTutor sign-in."""
    spec = find_by_name(getattr(config, "binding", None) or getattr(config, "provider_name", ""))
    return spec.name if spec and spec.is_oauth else None


@dataclass(frozen=True)
class OAuthCompletion:
    """An engine operation's model and owner, including calls made on SDK threads."""

    config: LLMConfig
    owner: CurrentUser

    @classmethod
    def for_current_user(cls, config: LLMConfig) -> OAuthCompletion:
        return cls(config, get_current_user())

    @contextmanager
    def activate(self) -> Iterator[None]:
        _register_oauth_provider()
        token = _ACTIVE_COMPLETION.set(self)
        try:
            yield
        finally:
            _ACTIVE_COMPLETION.reset(token)

    async def request(
        self, messages: list[dict[str, Any]], options: dict[str, Any], timeout: Any
    ) -> dict[str, Any]:
        from litellm.llms.custom_llm import CustomLLMError

        from deeptutor.services.llm.provider_factory import build_isolated_provider

        generation = {
            key: options[key] for key in ("temperature", "top_p") if options.get(key) is not None
        }
        max_tokens = options.get("max_completion_tokens") or options.get("max_tokens")
        if max_tokens is not None:
            generation["max_tokens"] = max_tokens

        with user_context(self.owner):
            try:
                provider = build_isolated_provider(self.config)
                try:
                    async with asyncio.timeout(
                        timeout if isinstance(timeout, int | float) else None
                    ):
                        result = await provider.chat(
                            messages=messages,
                            model=self.config.model,
                            reasoning_effort=self.config.reasoning_effort,
                            **generation,
                        )
                finally:
                    await provider.aclose()
            except Exception as error:
                status = getattr(error, "status_code", None)
                raise CustomLLMError(
                    status if isinstance(status, int) and 400 <= status <= 599 else 502,
                    "The OAuth completion failed. Check the model provider sign-in.",
                ) from None

        if result.finish_reason == "error":
            raise CustomLLMError(
                502, "The OAuth completion failed. Check the model provider sign-in."
            )

        content = result.content if result.content != result.reasoning_content else ""
        prompt_tokens = result.usage.get("prompt_tokens", 0)
        completion_tokens = result.usage.get("completion_tokens", 0)
        return {
            "message": {"role": "assistant", "content": content or ""},
            "finish_reason": "length"
            if result.finish_reason in {"length", "max_tokens"}
            else "stop",
            "index": 0,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": result.usage.get("total_tokens", prompt_tokens + completion_tokens),
            },
        }

    def request_sync(
        self, messages: list[dict[str, Any]], options: dict[str, Any], timeout: Any
    ) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.request(messages, options, timeout))
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(
                lambda: asyncio.run(self.request(messages, options, timeout))
            ).result()


_ACTIVE_COMPLETION: ContextVar[OAuthCompletion | None] = ContextVar(
    "deeptutor_rag_oauth_completion", default=None
)


def _active_completion(model: str) -> OAuthCompletion:
    from litellm.llms.custom_llm import CustomLLMError

    completion = _ACTIVE_COMPLETION.get()
    if completion is None or completion.config.model != model:
        raise CustomLLMError(403, "The OAuth model is not bound to this RAG operation.")
    return completion


def _completion_response(model: str, choice: dict[str, Any]) -> Any:
    from litellm import ModelResponse

    return ModelResponse(
        model=model,
        choices=[{key: value for key, value in choice.items() if key != "usage"}],
        usage=choice["usage"],
    )


def _completion_chunks(choice: dict[str, Any]) -> Iterator[dict[str, Any]]:
    # GraphRAG's non-streaming searches also consume SDK streams internally.
    yield {
        "text": choice["message"]["content"],
        "is_finished": False,
        "finish_reason": "",
        "usage": None,
    }
    yield {
        "text": "",
        "is_finished": True,
        "finish_reason": choice["finish_reason"],
        "usage": choice["usage"],
    }


def _register_oauth_provider() -> None:
    import litellm
    from litellm import CustomLLM

    with _REGISTRATION_LOCK:
        if any(entry["provider"] == OAUTH_PROVIDER for entry in litellm.custom_provider_map):
            return

        class DeepTutorOAuthProvider(CustomLLM):
            def completion(self, model, messages, optional_params, timeout=None, **_kwargs):
                choice = _active_completion(model).request_sync(messages, optional_params, timeout)
                return _completion_response(model, choice)

            async def acompletion(self, model, messages, optional_params, timeout=None, **_kwargs):
                choice = await _active_completion(model).request(messages, optional_params, timeout)
                return _completion_response(model, choice)

            def streaming(self, model, messages, optional_params, timeout=None, **_kwargs):
                choice = _active_completion(model).request_sync(messages, optional_params, timeout)
                return _completion_chunks(choice)

            def astreaming(self, model, messages, optional_params, timeout=None, **_kwargs):
                completion = _active_completion(model)

                async def chunks() -> AsyncIterator[dict[str, Any]]:
                    choice = await completion.request(messages, optional_params, timeout)
                    for chunk in _completion_chunks(choice):
                        yield chunk

                return chunks()

        litellm.custom_provider_map.append(
            {"provider": OAUTH_PROVIDER, "custom_handler": DeepTutorOAuthProvider()}
        )
