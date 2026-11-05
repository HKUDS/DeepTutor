"""Lightweight services facade for the shared native TypeScript transport.

Text-only service calls (suggestions, briefs, memory extraction, etc.) use the
same worker, HTTP pool and limiter as chat. Rich SDK-specific calls are selected
for compatibility *before* any request is sent. No Python retries or fallback
are allowed after a native call has begun.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .base import LLMProvider, LLMResponse


class TypeScriptProvider(LLMProvider):
    def __init__(self, config: Any):
        super().__init__(config.get_api_key(), config.effective_url or config.base_url)
        self.config = config
        self.provider_name = config.provider_name or config.binding

    def get_default_model(self) -> str:
        return self.config.model

    @staticmethod
    def _native_request(messages: list[dict], tools: Any, kwargs: dict) -> bool:
        # Preserve image degradation, native tools and provider-state replay in
        # the SDK adapter until those contracts have their own TS implementation.
        return (
            not tools
            and not kwargs.get("on_tool_args_delta")
            and all(
                m.get("role") in {"system", "developer", "user", "assistant"}
                and isinstance(m.get("content"), str)
                and not m.get("tool_calls")
                and not m.get("_provider_response_state")
                for m in messages
            )
            and not any(k in kwargs for k in ("extra_headers", "extra_query", "timeout"))
        )

    async def _call_with_retry(
        self, call, *, retry_delays=None, allow_image_fallback=True, **kwargs
    ):
        if not self._native_request(kwargs["messages"], kwargs.get("tools"), kwargs):
            from deeptutor.services.llm.provider_factory import _build_runtime_provider

            provider = _build_runtime_provider(
                self.config, configure_env=False, native_enabled=False
            )
            provider.generation = self.generation
            try:
                return await provider._call_with_retry(
                    getattr(provider, call.__name__),
                    retry_delays=retry_delays,
                    allow_image_fallback=allow_image_fallback,
                    **kwargs,
                )
            finally:
                await provider.aclose()
        from deeptutor.services.llm.metrics import measure_provider_call

        return await measure_provider_call(
            call, provider=self.provider_name, _retry_delays=retry_delays, **kwargs
        )

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
        **kwargs,
    ):
        return await self._request(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
            emit=False,
            **kwargs,
        )

    async def chat_stream(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
        **kwargs,
    ):
        return await self._request(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
            emit=True,
            **kwargs,
        )

    async def _request(
        self,
        messages,
        tools,
        model,
        max_tokens,
        temperature,
        reasoning_effort,
        tool_choice,
        *,
        emit,
        **kwargs,
    ):
        if not self._native_request(messages, tools, kwargs):
            # Direct chat()/chat_stream() callers receive the same preflight.
            from deeptutor.services.llm.provider_factory import _build_runtime_provider

            provider = _build_runtime_provider(
                self.config, configure_env=False, native_enabled=False
            )
            try:
                return await getattr(provider, "chat_stream" if emit else "chat")(
                    messages,
                    tools,
                    model,
                    max_tokens,
                    temperature,
                    reasoning_effort,
                    tool_choice,
                    **kwargs,
                )
            finally:
                await provider.aclose()
        from deeptutor.runtime.agentic.client import build_completion_kwargs
        from deeptutor.runtime.ts_engine import get_engine_client
        from deeptutor.runtime.ts_engine.config import provider_config

        content_sink = kwargs.pop("on_content_delta", None)
        reasoning_sink = kwargs.pop("on_reasoning_delta", None)
        kwargs.pop("on_tool_args_delta", None)
        delays = kwargs.pop("_retry_delays", None)
        cfg = replace(self.config, model=model or self.config.model)
        completion = build_completion_kwargs(
            model=cfg.model,
            binding=cfg.binding,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )
        completion.update({k: v for k, v in kwargs.items() if v is not None})
        provider = provider_config(cfg, completion)
        provider["stream"] = bool(emit and provider["stream"])
        if delays is not None:
            provider["retryDelaysMs"] = [float(delay) * 1000 for delay in delays]

        class ServicePort:
            async def invoke(self, operation, args, state):
                if operation != "event":
                    raise ValueError("Unexpected native service effect")
                event = args["event"]
                sink = content_sink if event["type"] == "content" else reasoning_sink
                if sink is not None:
                    await sink(event["content"])

        result = await get_engine_client().run_native(
            ServicePort(),
            {
                "provider": provider,
                "emit": emit,
                "messages": [
                    {"role": m["role"], "content": m["content"] or "(empty)"} for m in messages
                ],
            },
            kind="service",
        )
        return LLMResponse(
            content=result["text"],
            reasoning_content=result["reasoning"] or None,
            finish_reason=result["finishReason"],
            usage=result["usage"],
            provider_specific_fields={"execution_runtime": "typescript-native"},
        )
