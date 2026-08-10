"""Provider-neutral LLM adapter honoring explicit ``api_protocol``.

The adapter is the single deterministic path for explicit protocol profiles:

- ``openai_chat_completions`` -> Chat Completions wire format
- ``openai_responses``       -> Responses wire format (+ background lifecycle)
- ``anthropic_messages``     -> Anthropic Messages wire format

With ``strict_protocol=true`` an unsupported or failed path raises
:class:`UnifiedProtocolError` and never silently falls back to another
protocol.  Legacy callers keep working through the ``LLMProvider`` interface
(``chat`` / ``chat_stream`` return the classic
:class:`~deeptutor.services.llm.provider_core.base.LLMResponse`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse

from .anthropic import (
    ANTHROPIC_MESSAGES_PATH,
    AnthropicStreamParser,
    build_anthropic_request,
    parse_anthropic_response,
)
from .chat_completions import (
    CHAT_COMPLETIONS_PATH,
    ChatCompletionsStreamParser,
    build_chat_completions_request,
    parse_chat_completions_response,
)
from .common import normalize_messages, normalize_tools, to_legacy_llm_response
from .responses import (
    RESPONSES_PATH,
    ResponsesStreamParser,
    build_responses_request,
    parse_responses_response,
    responses_cancel_path,
    responses_retrieve_path,
)
from .transport import HttpTransport, LLMTransport, TransportError
from .types import (
    EXPLICIT_PROTOCOLS,
    PROTOCOL_ANTHROPIC,
    PROTOCOL_CHAT_COMPLETIONS,
    PROTOCOL_RESPONSES,
    UnifiedProtocolError,
    UnifiedRequest,
    UnifiedResponse,
    UnifiedResponseEvent,
)

if TYPE_CHECKING:
    from deeptutor.services.llm.config import LLMConfig


def _finished_event(unified: UnifiedResponse) -> UnifiedResponseEvent:
    return UnifiedResponseEvent(
        type="finished",
        finish_status=unified.finish_status,
        status=unified.status,
        model=unified.model,
        usage=unified.usage,
    )


class UnifiedLLMAdapter(LLMProvider):
    """Deterministic adapter for one explicit API protocol."""

    def __init__(
        self,
        *,
        protocol: str,
        transport: LLMTransport,
        strict_protocol: bool = False,
        default_model: str = "",
        provider: str = "",
        api_key: str | None = None,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        api_version: str | None = None,
    ) -> None:
        if protocol not in EXPLICIT_PROTOCOLS:
            raise UnifiedProtocolError(
                f"UnifiedLLMAdapter requires an explicit protocol, got {protocol!r}",
                code="invalid_protocol",
                protocol=protocol,
            )
        super().__init__(api_key, base_url)
        self.protocol = protocol
        self.transport = transport
        self.strict_protocol = strict_protocol
        self.default_model = default_model
        self.provider = provider
        self.extra_headers = extra_headers or {}
        self.api_version = api_version

    # ------------------------------------------------------------------
    # Legacy LLMProvider interface
    # ------------------------------------------------------------------

    def get_default_model(self) -> str:
        return self.default_model

    async def aclose(self) -> None:
        """Release the adapter-owned transport.

        The base :class:`LLMProvider` implementation only looks for
        ``_client``, but this adapter owns a :class:`LLMTransport` instead,
        so the inherited no-op would leak the httpx pool on shutdown or pool
        eviction.  Each ``aclose()`` awaits ``transport.aclose()`` exactly
        once; transports are responsible for making repeated closes
        idempotent.
        """
        await self.transport.aclose()

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"content-type": "application/json"}
        if self.protocol == PROTOCOL_ANTHROPIC:
            headers["x-api-key"] = self.api_key or ""
            headers["anthropic-version"] = self.api_version or "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {self.api_key or ''}"
        headers.update(self.extra_headers or {})
        return headers

    def _build_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        extra_kwargs: Mapping[str, Any],
        *,
        background: bool = False,
    ) -> UnifiedRequest:
        return UnifiedRequest(
            messages=normalize_messages(messages),
            tools=normalize_tools(tools),
            model=model or self.default_model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            extra=dict(extra_kwargs),
            background=background,
        )

    # ------------------------------------------------------------------
    # Provider-neutral API
    # ------------------------------------------------------------------

    async def complete_unified(self, request: UnifiedRequest) -> UnifiedResponse:
        """Run a non-streaming completion and return a unified response."""
        body, path = self._build_body_and_path(request, stream=False)
        try:
            raw = await self.transport.request_json("POST", path, body, self._headers())
        except TransportError as exc:
            raise self._protocol_failure(
                str(exc), code="transport_error", status_code=exc.status_code
            ) from exc
        return self._with_provider(parse_unified_response(self.protocol, raw))

    async def stream_events(
        self,
        request: UnifiedRequest,
    ) -> AsyncIterator[UnifiedResponseEvent]:
        """Stream normalized events for a completion request."""
        body, path = self._build_body_and_path(request, stream=True)
        parser = self._make_parser()
        try:
            async for raw in self.transport.request_json_lines("POST", path, body, self._headers()):
                for event in parser.feed(raw):
                    yield event
        except TransportError as exc:
            raise self._protocol_failure(
                str(exc), code="transport_error", status_code=exc.status_code
            ) from exc
        yield _finished_event(parser.final_response())

    # ------------------------------------------------------------------
    # OpenAI Responses background lifecycle
    # ------------------------------------------------------------------

    async def submit_background(self, request: UnifiedRequest) -> UnifiedResponse:
        """Submit a background Responses request and return its identity."""
        if self.protocol != PROTOCOL_RESPONSES:
            raise UnifiedProtocolError(
                "background submit is only supported by openai_responses",
                code="background_unsupported",
                protocol=self.protocol,
            )
        background_request = request.model_copy(update={"background": True})
        body = build_responses_request(background_request)
        try:
            raw = await self.transport.request_json("POST", RESPONSES_PATH, body, self._headers())
        except TransportError as exc:
            raise self._protocol_failure(
                str(exc), code="transport_error", status_code=exc.status_code
            ) from exc
        response = self._with_provider(parse_responses_response(raw))
        if not response.id:
            raise UnifiedProtocolError(
                "Responses background submit returned no response id",
                code="missing_response_id",
                protocol=self.protocol,
                provider=self.provider,
            )
        response.metadata["response_id"] = response.id
        return response

    async def retrieve(self, response_id: str) -> UnifiedResponse:
        """Retrieve a background Responses result without re-submitting."""
        if self.protocol != PROTOCOL_RESPONSES:
            raise UnifiedProtocolError(
                "retrieve is only supported by openai_responses",
                code="background_unsupported",
                protocol=self.protocol,
            )
        try:
            raw = await self.transport.request_json(
                "GET", responses_retrieve_path(response_id), None, self._headers()
            )
        except TransportError as exc:
            raise self._protocol_failure(
                str(exc), code="transport_error", status_code=exc.status_code
            ) from exc
        response = self._with_provider(parse_responses_response(raw))
        response.metadata["response_id"] = response.id or response_id
        return response

    async def cancel(self, response_id: str) -> UnifiedResponse:
        """Cancel a background Responses result without re-submitting."""
        if self.protocol != PROTOCOL_RESPONSES:
            raise UnifiedProtocolError(
                "cancel is only supported by openai_responses",
                code="background_unsupported",
                protocol=self.protocol,
            )
        try:
            raw = await self.transport.request_json(
                "POST", responses_cancel_path(response_id), {}, self._headers()
            )
        except TransportError as exc:
            raise self._protocol_failure(
                str(exc), code="transport_error", status_code=exc.status_code
            ) from exc
        response = self._with_provider(parse_responses_response(raw))
        response.metadata["response_id"] = response.id or response_id
        return response

    # ------------------------------------------------------------------
    # Legacy chat/chat_stream
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **extra_kwargs: Any,
    ) -> LLMResponse:
        request = self._build_request(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
            extra_kwargs,
        )
        try:
            unified = await self.complete_unified(request)
        except TransportError as exc:
            return self._error_response(
                self._protocol_failure(
                    str(exc), code="transport_error", status_code=exc.status_code
                )
            )
        except Exception as exc:
            return self._error_response(exc)
        return to_legacy_llm_response(unified)

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
        **extra_kwargs: Any,
    ) -> LLMResponse:
        request = self._build_request(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
            extra_kwargs,
        )
        body, path = self._build_body_and_path(request, stream=True)
        parser = self._make_parser()
        try:
            async for raw in self.transport.request_json_lines("POST", path, body, self._headers()):
                for event in parser.feed(raw):
                    if (
                        on_content_delta is not None
                        and event.type == "content_delta"
                        and event.delta
                    ):
                        await on_content_delta(event.delta)
                    if (
                        on_reasoning_delta is not None
                        and event.type == "reasoning_delta"
                        and event.delta
                    ):
                        await on_reasoning_delta(event.delta)
            unified = self._with_provider(parser.final_response())
        except TransportError as exc:
            return self._error_response(
                self._protocol_failure(
                    str(exc), code="transport_error", status_code=exc.status_code
                )
            )
        except Exception as exc:
            return self._error_response(exc)
        return to_legacy_llm_response(unified)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_body_and_path(
        self,
        request: UnifiedRequest,
        *,
        stream: bool,
    ) -> tuple[dict[str, Any], str]:
        if self.protocol == PROTOCOL_CHAT_COMPLETIONS:
            body = build_chat_completions_request(request)
            path = CHAT_COMPLETIONS_PATH
        elif self.protocol == PROTOCOL_RESPONSES:
            body = build_responses_request(request)
            path = RESPONSES_PATH
        elif self.protocol == PROTOCOL_ANTHROPIC:
            body = build_anthropic_request(request)
            path = ANTHROPIC_MESSAGES_PATH
        else:
            raise UnifiedProtocolError(
                f"unsupported protocol {self.protocol!r}",
                code="invalid_protocol",
                protocol=self.protocol,
            )
        if stream:
            body["stream"] = True
        return body, path

    def _make_parser(self) -> Any:
        if self.protocol == PROTOCOL_CHAT_COMPLETIONS:
            return ChatCompletionsStreamParser()
        if self.protocol == PROTOCOL_RESPONSES:
            return ResponsesStreamParser()
        if self.protocol == PROTOCOL_ANTHROPIC:
            return AnthropicStreamParser()
        raise UnifiedProtocolError(
            f"unsupported protocol {self.protocol!r}",
            code="invalid_protocol",
            protocol=self.protocol,
        )

    def _with_provider(self, unified: UnifiedResponse) -> UnifiedResponse:
        if self.provider and not unified.provider:
            unified.provider = self.provider
        if self.protocol and not unified.metadata.get("api_protocol"):
            unified.metadata["api_protocol"] = self.protocol
        return unified

    def _protocol_failure(
        self, message: str, *, code: str, status_code: int | None = None
    ) -> UnifiedProtocolError:
        return UnifiedProtocolError(
            message,
            code=code,
            protocol=self.protocol,
            provider=self.provider,
            status_code=status_code,
        )

    def _error_response(self, exc: Exception) -> LLMResponse:
        if self.strict_protocol:
            if isinstance(exc, UnifiedProtocolError):
                raise exc
            raise self._protocol_failure(str(exc), code="protocol_error") from exc
        status_code = getattr(exc, "status_code", None)
        error_code = str(getattr(exc, "code", "protocol_error") or "protocol_error")
        retryable = status_code in {408, 429} or (
            isinstance(status_code, int) and 500 <= status_code <= 599
        )
        return LLMResponse(
            # Preserve the legacy facade's generic error body; lifecycle-aware
            # consumers reject it based on ``termination`` before treating it
            # as model output.
            content="Error calling LLM.",
            finish_reason="error",
            termination={
                "provider_status": "failed",
                "finish_reason": "error",
                "error_code": error_code,
                "status_code": status_code,
                "protocol": self.protocol,
                "provider": self.provider,
                "retryable": retryable,
            },
        )


def parse_unified_response(protocol: str, raw: dict[str, Any]) -> UnifiedResponse:
    """Parse a raw wire response dict for the given protocol."""
    if protocol == PROTOCOL_CHAT_COMPLETIONS:
        return parse_chat_completions_response(raw)
    if protocol == PROTOCOL_RESPONSES:
        return parse_responses_response(raw)
    if protocol == PROTOCOL_ANTHROPIC:
        return parse_anthropic_response(raw)
    raise UnifiedProtocolError(
        f"unsupported protocol {protocol!r}",
        code="invalid_protocol",
        protocol=protocol,
    )


def build_unified_adapter(config: "LLMConfig") -> UnifiedLLMAdapter:
    """Build a production transport-backed adapter from an ``LLMConfig``."""
    protocol = config.api_protocol or "auto"
    if protocol not in EXPLICIT_PROTOCOLS:
        protocol = config.resolved_api_protocol or "openai_chat_completions"
    base_url = config.effective_url or config.base_url or ""
    return UnifiedLLMAdapter(
        protocol=protocol,
        transport=HttpTransport(base_url=base_url),
        strict_protocol=config.strict_protocol,
        default_model=config.model,
        provider=config.provider_name or config.binding,
        api_key=config.api_key,
        base_url=base_url,
        extra_headers=config.extra_headers,
        api_version=config.api_version,
    )


__all__ = [
    "UnifiedLLMAdapter",
    "build_unified_adapter",
    "parse_unified_response",
]
