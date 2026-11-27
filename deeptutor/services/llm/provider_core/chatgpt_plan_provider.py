"""Text Responses for a locally authorized ChatGPT plan."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from deeptutor.services.chatgpt_plan_context import PlanError, request_allowed
from deeptutor.services.llm.exceptions import LLMChatGPTPlanLoginRequired, LLMChatGPTPlanUsageLimit
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse
from deeptutor.services.llm.provider_core.openai_responses.parsing import iter_sse

_MESSAGES = {
    "desktop_required": "ChatGPT plan is available in Open DeepTutor Desktop.",
    "interactive_request_required": "Use ChatGPT Plan in Desktop chat or run a language-model test in Settings.",
    "access_renewed": "The ChatGPT connection was refreshed. Try again.",
    "request_account_changed": "The active ChatGPT account changed. Send the request again to use the new account.",
    "sharing_required": "Enable ChatGPT plan usage in Providers to send messages.",
    "subscription_sharing_user_not_eligible": "This ChatGPT account or workspace cannot use plan sharing.",
    "subscription_sharing_usage_unavailable": "ChatGPT plan usage is temporarily unavailable. Try again later.",
    "unsupported_request": "Use a new text chat with the ChatGPT plan provider. This preview handles text messages only.",
    "incomplete_response": "ChatGPT did not complete the response. Try again.",
}


def _input(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant", "developer", "system"} or message.get("tool_calls"):
            raise PlanError("unsupported_request")
        if isinstance(content, list) and all(
            isinstance(item, dict)
            and item.get("type") in {"text", "input_text"}
            and isinstance(item.get("text"), str)
            for item in content
        ):
            content = "\n".join(item["text"] for item in content)
        if not isinstance(content, str):
            raise PlanError("unsupported_request")
        if content:
            result.append({"role": "developer" if role == "system" else role, "content": content})
    return result


class ChatGPTPlanProvider(LLMProvider):
    def __init__(self, default_model: str):
        super().__init__()
        self.default_model = default_model

    def get_default_model(self) -> str:
        return self.default_model

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
        return await self.chat_stream(
            messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice, **kwargs
        )

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
        if not request_allowed.get():
            return LLMResponse(
                content=_MESSAGES["interactive_request_required"], finish_reason="error"
            )
        from deeptutor.services.chatgpt_plan import (
            RESOURCE,
            get_session,
            response_error_code,
        )

        try:
            if tools:
                raise PlanError("unsupported_request")
            # The plan endpoint accepts a narrower request than the shared provider interface.
            body = {
                "model": model or self.default_model,
                "input": _input(messages),
                "store": False,
                "stream": True,
            }
            session = get_session()
            token = await session.access_token()
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                async with client.stream(
                    "POST",
                    f"{RESOURCE}/responses",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    if response.status_code != 200:
                        await response.aread()
                        try:
                            code = response_error_code(response.json())
                        except ValueError:
                            code = ""
                        if response.status_code == 401:
                            await session.rejected_access_token(token)
                        raise PlanError(code)
                    deltas: list[str] = []
                    async for event in iter_sse(response):
                        kind = event.get("type")
                        if kind == "response.output_text.delta" and isinstance(
                            event.get("delta"), str
                        ):
                            delta = event["delta"]
                            deltas.append(delta)
                            if on_content_delta:
                                await on_content_delta(delta)
                        elif kind == "response.completed":
                            result = event.get("response") or {}
                            if not deltas or result.get("status", "completed") != "completed":
                                raise PlanError("incomplete_response")
                            usage = result.get("usage") or {}
                            return LLMResponse(
                                content="".join(deltas),
                                usage={
                                    "prompt_tokens": usage.get("input_tokens", 0),
                                    "completion_tokens": usage.get("output_tokens", 0),
                                    "total_tokens": usage.get("total_tokens", 0),
                                },
                            )
                        elif kind in {"response.failed", "response.incomplete", "error"}:
                            code = response_error_code(event.get("response") or event)
                            if code == "subscription_sharing_invalid_user":
                                await session.rejected_access_token(token)
                            raise PlanError(code or "incomplete_response")
                    raise PlanError("incomplete_response")
        except (PlanError, ValueError, httpx.HTTPError, OSError) as exc:
            code = exc.code if isinstance(exc, PlanError) else ""
            if code == "login_required":
                raise LLMChatGPTPlanLoginRequired(
                    "Reconnect your ChatGPT account in Providers."
                ) from None
            if code == "subscription_sharing_usage_limit_exceeded":
                raise LLMChatGPTPlanUsageLimit("ChatGPT plan usage is unavailable.") from None
            return LLMResponse(
                content=_MESSAGES.get(
                    code,
                    "The ChatGPT plan request failed. Try again or check your connection in Providers.",
                ),
                finish_reason="error",
            )
