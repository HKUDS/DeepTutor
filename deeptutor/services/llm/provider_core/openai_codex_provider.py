"""OpenAI Codex Responses provider backed by DeepTutor's private OAuth service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import hashlib
import json
from typing import Any

import httpx
from loguru import logger

from deeptutor.services.codex_auth import CodexAuthError, get_codex_oauth_service
from deeptutor.services.codex_auth.constants import CODEX_DEFAULT_MODEL_ID, CODEX_RESPONSES_URL
from deeptutor.services.codex_auth.contracts import CodexToken
from deeptutor.services.llm.openai_http_client import disable_ssl_verify_enabled
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse, ToolCallRequest
from deeptutor.services.llm.provider_core.openai_responses import (
    consume_sse,
    convert_messages,
    convert_tools,
)

DEFAULT_ORIGINATOR = "DeepTutor"


class CodexHTTPError(RuntimeError):
    def __init__(self, status_code: int, safe_message: str) -> None:
        super().__init__(safe_message)
        self.status_code = status_code


class OpenAICodexProvider(LLMProvider):
    """Use OpenAI Codex OAuth tokens to call the Responses API."""

    def __init__(self, default_model: str = CODEX_DEFAULT_MODEL_ID):
        super().__init__(api_key=None, api_base=None)
        self.default_model = default_model

    async def _load_token(self) -> CodexToken:
        return await get_codex_oauth_service().get_token()

    async def _call_codex(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        model_name = model or self.default_model
        system_prompt, input_items = convert_messages(messages)

        body: dict[str, Any] = {
            "model": _strip_model_prefix(model_name),
            "store": False,
            "stream": True,
            "instructions": system_prompt,
            "input": input_items,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": _prompt_cache_key(messages),
            "tool_choice": tool_choice or "auto",
            "parallel_tool_calls": True,
        }
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        if tools:
            body["tools"] = convert_tools(tools)

        service = get_codex_oauth_service()
        async with service.inference_guard():
            try:
                token = await self._load_token()
                headers = _build_headers(token.account_id, token.access_token)
                try:
                    content, tool_calls, finish_reason = await _request_codex(
                        CODEX_RESPONSES_URL,
                        headers,
                        body,
                        verify=not disable_ssl_verify_enabled(),
                        on_content_delta=on_content_delta,
                    )
                except CodexHTTPError as exc:
                    if exc.status_code == 401:
                        try:
                            await service.recover_after_unauthorized(token.generation)
                        except CodexAuthError:
                            # Only promise a retry when the session really was
                            # renewed; a dead refresh token needs a new sign-in.
                            logger.warning("Codex token renewal after HTTP 401 failed")
                            raise CodexHTTPError(
                                exc.status_code,
                                "Codex login expired and could not be renewed. Sign in again.",
                            ) from None
                    raise
                except Exception as exc:
                    if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                        raise
                    logger.warning(
                        "SSL verification failed for Codex API; retrying with verify=False"
                    )
                    content, tool_calls, finish_reason = await _request_codex(
                        CODEX_RESPONSES_URL,
                        headers,
                        body,
                        verify=False,
                        on_content_delta=on_content_delta,
                    )
                return LLMResponse(
                    content=content,
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                )
            except CodexHTTPError as exc:
                return LLMResponse(
                    content=f"Error calling Codex: {exc}",
                    finish_reason="error",
                )
            except CodexAuthError as exc:
                return LLMResponse(
                    content=f"Error calling Codex: {exc.public_message}",
                    finish_reason="error",
                )
            except Exception:
                # The user-facing text stays generic so upstream payloads never
                # leak, but an operator still needs the real cause in the log.
                logger.exception("Codex request failed")
                return LLMResponse(
                    content="Error calling Codex: Codex request failed. Please try again.",
                    finish_reason="error",
                )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        del max_tokens, temperature, kwargs
        return await self._call_codex(messages, tools, model, reasoning_effort, tool_choice)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        del max_tokens, temperature, on_reasoning_delta, kwargs
        return await self._call_codex(
            messages,
            tools,
            model,
            reasoning_effort,
            tool_choice,
            on_content_delta,
        )

    def get_default_model(self) -> str:
        return self.default_model


def _strip_model_prefix(model: str) -> str:
    if model.startswith("openai-codex/") or model.startswith("openai_codex/"):
        return model.split("/", 1)[1]
    return model


def _build_headers(account_id: str, token: str) -> dict[str, str]:
    if not token:
        raise RuntimeError(
            "OpenAI Codex is not logged in. Run `deeptutor provider login openai-codex`."
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "OpenAI-Beta": "responses=experimental",
        "originator": DEFAULT_ORIGINATOR,
        "User-Agent": "DeepTutor (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }
    if account_id:
        headers["chatgpt-account-id"] = str(account_id)
    return headers


async def _request_codex(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    verify: bool,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, list[ToolCallRequest], str]:
    async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                raw = await response.aread()
                # Kept out of the reply the learner sees, but an operator cannot
                # diagnose an upstream rejection without the body.
                logger.debug(
                    "Codex API returned HTTP {}: {}",
                    response.status_code,
                    raw.decode("utf-8", "ignore")[:500],
                )
                raise CodexHTTPError(
                    response.status_code,
                    _friendly_error(response.status_code),
                )
            return await consume_sse(response, on_content_delta)


def _prompt_cache_key(messages: list[dict[str, Any]]) -> str:
    raw = json.dumps(messages, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _friendly_error(status_code: int) -> str:
    if status_code == 401:
        return "Codex login expired. The session was refreshed; retry this request."
    if status_code == 403:
        return "This Codex account is not allowed to make the requested call."
    if status_code == 429:
        return "Codex usage quota exceeded or rate limit triggered. Please try again later."
    return f"Codex returned HTTP {status_code}."
