"""Route local RAG SDK completions through DeepTutor's OAuth providers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any

from deeptutor.multi_user.context import get_current_user_or_none
from deeptutor.multi_user.paths import user_context
from deeptutor.services.provider_registry import find_by_name

if TYPE_CHECKING:
    from litellm.llms.custom_llm import CustomLLMError

    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.llm.provider_core.base import LLMResponse

OAUTH_PROVIDER = "deeptutor_oauth"
_REGISTRATION_LOCK = Lock()
_CALLER_LOOP: ContextVar[asyncio.AbstractEventLoop | None] = ContextVar(
    "deeptutor_rag_oauth_caller_loop", default=None
)


def oauth_binding(config: Any) -> str | None:
    """Return the canonical binding for a provider managed by DeepTutor sign-in."""
    spec = find_by_name(getattr(config, "binding", None) or getattr(config, "provider_name", ""))
    return spec.name if spec and spec.is_oauth else None


@contextmanager
def oauth_caller_loop() -> Iterator[None]:
    """Keep native OAuth clients on the caller's loop across SDK worker threads."""
    token = _CALLER_LOOP.set(asyncio.get_running_loop())
    try:
        yield
    finally:
        _CALLER_LOOP.reset(token)


class OAuthModelAccessError(RuntimeError):
    """The initiating user cannot use this OAuth model."""


def _require_owner() -> CurrentUser:
    owner = get_current_user_or_none()
    if owner is None:
        raise OAuthModelAccessError("OAuth completions require an explicit DeepTutor user.")
    return owner


def _matching_models(owner: CurrentUser, binding: str | None, model: str) -> list[dict[str, Any]]:
    from deeptutor.multi_user.model_access import allowed_llm_options
    from deeptutor.services.provider_registry import canonical_provider_name

    if not owner.is_admin and binding in {"claude_code", "codebuddy"}:
        raise OAuthModelAccessError("This provider uses the deployment operator's local sign-in.")
    return [
        option
        for option in allowed_llm_options()["options"]
        if option["model"] == model
        and canonical_provider_name(option["provider"]) == binding
        and (owner.is_admin or option.get("source") == "personal")
    ]


def _model_access_error() -> OAuthModelAccessError:
    return OAuthModelAccessError(
        "This OAuth model is unavailable to your account. Check the provider sign-in and catalog."
    )


@dataclass(frozen=True)
class OAuthCompletion:
    """The resolved configuration, credential owner and loop for an SDK operation."""

    config: LLMConfig
    owner: CurrentUser
    loop: asyncio.AbstractEventLoop

    @classmethod
    def for_current_user(cls, config: LLMConfig) -> OAuthCompletion:
        owner = _require_owner()
        if not owner.is_admin:
            binding = oauth_binding(config)
            if binding is None:
                raise _model_access_error()
            return cls.for_saved_model(binding, config.model, config.reasoning_effort)
        return cls(config, owner, _CALLER_LOOP.get() or asyncio.get_running_loop())

    @classmethod
    def for_saved_model(
        cls, binding: str, model: str, reasoning_effort: str | None
    ) -> OAuthCompletion:
        """Resolve stored model identity through the current user's model catalog."""
        from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection

        owner = _require_owner()
        current = _ACTIVE_COMPLETION.get()
        if (
            current is not None
            and current.owner.id == owner.id
            and current.config.model == model
            and oauth_binding(current.config) == binding
        ):
            return current

        options = _matching_models(owner, binding, model)
        option = next((row for row in options if row["is_active_default"]), None)
        if option is None:
            if len(options) != 1:
                raise _model_access_error()
            option = options[0]

        config = resolve_llm_config_for_selection(
            {
                "profile_id": option["profile_id"],
                "model_id": option["model_id"],
                "reasoning_effort": reasoning_effort,
            }
        )
        if config.model != model or oauth_binding(config) != binding:
            raise _model_access_error()
        return cls(config, owner, _CALLER_LOOP.get() or asyncio.get_running_loop())

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
    ) -> LLMResponse:
        if asyncio.get_running_loop() is self.loop:
            return await self._request(messages, options, timeout)
        future = asyncio.run_coroutine_threadsafe(
            self._request(messages, options, timeout), self.loop
        )
        return await asyncio.wrap_future(future)

    def request_sync(
        self, messages: list[dict[str, Any]], options: dict[str, Any], timeout: Any
    ) -> LLMResponse:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self.loop:
            raise RuntimeError("Synchronous OAuth completion requires an SDK worker thread.")
        return asyncio.run_coroutine_threadsafe(
            self._request(messages, options, timeout), self.loop
        ).result()

    async def _request(
        self, messages: list[dict[str, Any]], options: dict[str, Any], timeout: Any
    ) -> LLMResponse:
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
                raise _completion_error(error) from None

        if result.finish_reason == "error":
            raise _completion_error(RuntimeError(result.content or ""))
        return result


_ACTIVE_COMPLETION: ContextVar[OAuthCompletion | None] = ContextVar(
    "deeptutor_rag_oauth_completion", default=None
)


def _active_completion(model: str) -> OAuthCompletion:
    from litellm.llms.custom_llm import CustomLLMError

    completion = _ACTIVE_COMPLETION.get()
    if completion is None or completion.config.model != model:
        raise CustomLLMError(403, "The OAuth model is not bound to this RAG operation.")
    return completion


def _completion_error(error: Exception) -> CustomLLMError:
    from litellm.llms.custom_llm import CustomLLMError

    from deeptutor.services.llm.error_mapping import map_error
    from deeptutor.services.llm.exceptions import LLMTimeoutError
    from deeptutor.services.llm.provider_core.base import LLMProvider

    mapped = map_error(error)
    status = getattr(mapped, "status_code", None)
    if isinstance(mapped, LLMTimeoutError):
        status = 504
    if status is None:
        # Some native providers return a public error message instead of raising.
        detail = str(error).lower()
        status = LLMProvider._status_code_from_message(detail)
        if status is None and "not allowed to make the requested call" in detail:
            status = 403
        if status is None and any(
            marker in detail
            for marker in (
                "sign in",
                "signed in",
                "sign-in",
                "logged in",
                "login",
                "authentication",
            )
        ):
            status = 401
    if not isinstance(status, int) or not 400 <= status <= 599:
        status = 502
    message = {
        401: "Sign in to the OAuth model provider and try again.",
        403: "The OAuth model provider denied access to this model.",
        429: "The OAuth model provider rate limit was reached.",
        504: "The OAuth model provider did not respond in time.",
    }.get(status, "The OAuth model provider request failed.")
    return CustomLLMError(status, message)


def _content(result: LLMResponse) -> str:
    return result.content if result.content and result.content != result.reasoning_content else ""


def _finish_reason(result: LLMResponse) -> str:
    return "length" if result.finish_reason in {"length", "max_tokens"} else "stop"


def _usage(result: LLMResponse) -> dict[str, int]:
    prompt_tokens = result.usage.get("prompt_tokens", 0)
    completion_tokens = result.usage.get("completion_tokens", 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": result.usage.get("total_tokens", prompt_tokens + completion_tokens),
    }


def _completion_response(model: str, result: LLMResponse) -> Any:
    from litellm import ModelResponse

    return ModelResponse(
        model=model,
        choices=[
            {
                "message": {"role": "assistant", "content": _content(result)},
                "finish_reason": _finish_reason(result),
                "index": 0,
            }
        ],
        usage=_usage(result),
    )


def _completion_chunks(result: LLMResponse) -> Iterator[dict[str, Any]]:
    # GraphRAG also consumes SDK streams for some non-streaming search results.
    yield {"text": _content(result), "is_finished": False, "finish_reason": "", "usage": None}
    yield {
        "text": "",
        "is_finished": True,
        "finish_reason": _finish_reason(result),
        "usage": _usage(result),
    }


def _register_oauth_provider() -> None:
    import litellm
    from litellm import CustomLLM

    with _REGISTRATION_LOCK:
        if any(entry["provider"] == OAUTH_PROVIDER for entry in litellm.custom_provider_map):
            return

        class DeepTutorOAuthProvider(CustomLLM):
            def completion(self, model, messages, optional_params, timeout=None, **_kwargs):
                result = _active_completion(model).request_sync(messages, optional_params, timeout)
                return _completion_response(model, result)

            async def acompletion(self, model, messages, optional_params, timeout=None, **_kwargs):
                result = await _active_completion(model).request(messages, optional_params, timeout)
                return _completion_response(model, result)

            def streaming(self, model, messages, optional_params, timeout=None, **_kwargs):
                result = _active_completion(model).request_sync(messages, optional_params, timeout)
                return _completion_chunks(result)

            def astreaming(self, model, messages, optional_params, timeout=None, **_kwargs):
                completion = _active_completion(model)

                async def chunks() -> AsyncIterator[dict[str, Any]]:
                    result = await completion.request(messages, optional_params, timeout)
                    for chunk in _completion_chunks(result):
                        yield chunk

                return chunks()

        litellm.custom_provider_map.append(
            {"provider": OAUTH_PROVIDER, "custom_handler": DeepTutorOAuthProvider()}
        )
