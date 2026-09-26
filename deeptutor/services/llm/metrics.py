"""Task-local turn accounting at the LLM transport boundaries.

No prompts, credentials or responses are retained. Parallel child tasks share
one collector; different turns/users get different ContextVar bindings.
"""

from __future__ import annotations

from contextvars import ContextVar
import logging
import time
from typing import Any
import uuid

from .usage_frame import usage_breakdown


class TurnUsage:
    def __init__(self, *, session_id: str = "", turn_id: str = "", source: str = "") -> None:
        self.session_id = session_id
        self.turn_id = turn_id or uuid.uuid4().hex
        self.source = source
        self.calls: list[dict[str, Any]] = []

    def summary(self) -> dict[str, Any] | None:
        if not self.calls:
            return None
        calls = self.calls
        totals = {
            key: sum(c.get(key, 0) or 0 for c in calls)
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
                "reasoning_tokens",
                "duration_seconds",
            )
        }
        cache_calls = [c for c in calls if c.get("cache_read_input_tokens") is not None]
        cache_input = sum(c["prompt_tokens"] for c in cache_calls)
        timed = [c for c in calls if c.get("ttft_seconds") is not None]
        generated = [c for c in calls if c.get("generation_seconds") and not c["estimated"]]
        generation_seconds = sum(c["generation_seconds"] for c in generated)
        return {
            **totals,
            "total_calls": len(calls),
            "cache_reported_calls": len(cache_calls),
            "cache_input_tokens": cache_input,
            "cache_hit_rate": (
                totals["cache_read_input_tokens"] / cache_input if cache_input else None
            ),
            "ttft_seconds": (sum(c["ttft_seconds"] for c in timed) / len(timed) if timed else None),
            "ttft_calls": len(timed),
            "generation_seconds": generation_seconds,
            "timed_completion_tokens": sum(c["completion_tokens"] for c in generated),
            "tokens_per_second": (
                sum(c["completion_tokens"] for c in generated) / generation_seconds
                if generation_seconds
                else None
            ),
            "estimated_calls": sum(c["estimated"] for c in calls),
            "call_details": list(calls),
        }


current_usage: ContextVar[TurnUsage | None] = ContextVar("llm_turn_usage", default=None)
# Prevent native adapter and factory instrumentation from counting the same call twice.
measurement_active: ContextVar[bool] = ContextVar("llm_measurement_active", default=False)


class CallMeasurement:
    def __init__(self, *, model: str = "", provider: str = "", messages: Any = None):
        self.enabled = not measurement_active.get()
        self.collector = current_usage.get() if self.enabled else None
        self.call_id = uuid.uuid4().hex
        self.started_at = time.time()
        self.ledger = None
        if self.enabled:
            from .usage_ledger import ledger_path

            try:
                self.ledger = ledger_path()
            except Exception:
                logging.getLogger(__name__).exception("Unable to resolve usage ledger")
        self.model, self.provider = model, provider
        self.started = time.perf_counter()
        self.first: float | None = None
        self.last: float | None = None
        self.output_chars = 0
        # Estimate only when the API does not report usage; never persist message text.
        self.input_chars = len(str(messages or "")) if self.enabled else 0
        self.usage: Any = None
        self.finished = False

    def delta(self, value: Any) -> None:
        if not value:
            return
        now = time.perf_counter()
        if self.first is None:
            self.first = now
        self.last = now
        self.output_chars += len(str(value))

    def chunk(self, chunk: Any) -> None:
        if usage := usage_breakdown(getattr(chunk, "usage", None)):
            self.usage = usage
        for choice in getattr(chunk, "choices", []) or []:
            delta = getattr(choice, "delta", None)
            if delta is not None:
                self.delta(getattr(delta, "content", None))
                self.delta(
                    getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                )
                for tool in getattr(delta, "tool_calls", []) or []:
                    self.delta(getattr(getattr(tool, "function", None), "arguments", None))

    def finish(self, response: Any = None, *, status: str = "completed") -> None:
        if self.finished or not self.enabled:
            return
        self.finished = True
        if response is not None:
            self.usage = getattr(response, "usage", None) or self.usage
        counts = usage_breakdown(self.usage)
        estimated = not bool(counts)
        if estimated:
            response_text = getattr(response, "content", "") or ""
            if not response_text:
                for choice in getattr(response, "choices", []) or []:
                    message = getattr(choice, "message", None)
                    response_text += str(getattr(message, "content", "") or "")
                    response_text += str(getattr(message, "reasoning_content", "") or "")
            output = self.output_chars or len(response_text)
            counts = {
                "prompt_tokens": int(self.input_chars / 3.5),
                "completion_tokens": int(output / 3.5),
            }
            counts["total_tokens"] = sum(counts.values())
        duration = time.perf_counter() - self.started
        # Use last model delta, excluding usage-only trailers and UI rendering.
        generation = self.last - self.first if self.first is not None and self.last else 0
        record = {
            "call_id": self.call_id,
            **counts,
            "model": self.model,
            "provider": self.provider,
            "status": status,
            "estimated": estimated,
            "duration_seconds": duration,
            "ttft_seconds": self.first - self.started if self.first is not None else None,
            "generation_seconds": generation if generation > 0 else None,
            "tokens_per_second": (
                counts["completion_tokens"] / generation
                if generation > 0 and not estimated
                else None
            ),
            "cache_hit_rate": (
                counts["cache_read_input_tokens"] / counts["prompt_tokens"]
                if "cache_read_input_tokens" in counts and counts["prompt_tokens"]
                else None
            ),
        }
        if self.collector is not None:
            self.collector.calls.append(record)
        if self.ledger is not None:
            from .usage_ledger import record_call

            try:
                record_call(
                    self.ledger,
                    record,
                    started_at=self.started_at,
                    session_id=self.collector.session_id if self.collector else "",
                    turn_id=self.collector.turn_id if self.collector else "",
                    source=self.collector.source if self.collector else "",
                )
            except Exception:
                logging.getLogger(__name__).exception("Unable to persist LLM usage")


async def measure_provider_call(call: Any, *, provider: str = "", **kwargs: Any) -> Any:
    """Measure each provider attempt, before callbacks are buffered by the factory."""
    meter = CallMeasurement(
        model=kwargs.get("model") or "", provider=provider, messages=kwargs.get("messages")
    )
    for key in ("on_content_delta", "on_reasoning_delta", "on_tool_args_delta"):
        callback = kwargs.get(key)
        if callback is not None:

            def wrap(original: Any) -> Any:
                async def measured(*args: Any, **kw: Any) -> Any:
                    meter.delta(args[-1] if args else None)
                    return await original(*args, **kw)

                return measured

            kwargs[key] = wrap(callback)
    token = measurement_active.set(True)
    try:
        response = await call(**kwargs)
        meter.finish(
            response, status="failed" if response.finish_reason == "error" else "completed"
        )
        return response
    except BaseException:
        meter.finish(status="interrupted")
        raise
    finally:
        measurement_active.reset(token)


class MeasuredStream:
    def __init__(self, stream: Any, meter: CallMeasurement):
        self.stream, self.meter = stream, meter
        self.iterator: Any = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)

    def __aiter__(self) -> Any:
        return self

    async def __anext__(self) -> Any:
        token = measurement_active.set(True)
        try:
            if self.iterator is None:
                self.iterator = self.stream.__aiter__()
            chunk = await self.iterator.__anext__()
            self.meter.chunk(chunk)
            return chunk
        except StopAsyncIteration:
            self.meter.finish()
            raise
        except BaseException:
            self.meter.finish(status="interrupted")
            raise
        finally:
            measurement_active.reset(token)

    async def close(self) -> None:
        self.meter.finish(status="interrupted")
        close = getattr(self.stream, "close", None) or getattr(self.stream, "aclose", None)
        if close:
            await close()

    async def aclose(self) -> None:
        await self.close()

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def instrument_client(client: Any, *, model: str = "", provider: str = "") -> Any:
    create = client.chat.completions.create

    async def measured_create(**kwargs: Any) -> Any:
        meter = CallMeasurement(
            model=kwargs.get("model") or model, provider=provider, messages=kwargs.get("messages")
        )
        token = measurement_active.set(True)
        try:
            result = await create(**kwargs)
            if kwargs.get("stream"):
                return MeasuredStream(result, meter)
            meter.finish(result)
            return result
        except BaseException:
            meter.finish(status="failed")
            raise
        finally:
            measurement_active.reset(token)

    client.chat.completions.create = measured_create
    return client
