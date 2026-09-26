"""Shared plumbing for capability ``run()`` endpoints.

Capabilities all converge on the same final emission:

    await stream.result({"response": ..., ...}, source="<cap>")

Each result includes the task-local LLM usage snapshot when available. The
legacy cost_summary remains for CLI/SDK consumers; the Web footer uses token,
cache and timing measurements from usage_summary.

"""

from __future__ import annotations

from typing import Any

from deeptutor.runtime.agentic.usage import UsageTracker
from deeptutor.runtime.stream_bus import StreamBus


async def emit_capability_result(
    stream: StreamBus,
    payload: dict[str, Any],
    *,
    source: str,
    usage: UsageTracker | None = None,
) -> None:
    """Emit the final capability result, attaching cost_summary if available.

    ``payload`` is mutated in place: when ``usage`` has at least one
    recorded call, its ``summary()`` is merged into
    ``payload["metadata"]["cost_summary"]``. Any pre-existing
    ``payload["metadata"]`` dict is preserved.
    """
    if usage is not None:
        cs = usage.summary()
        if cs:
            meta = payload.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
                payload["metadata"] = meta
            meta["cost_summary"] = cs
    from deeptutor.services.llm.metrics import current_usage

    collector = current_usage.get()
    if collector is not None and (summary := collector.summary()):
        payload.setdefault("metadata", {})["usage_summary"] = summary
    await stream.result(payload, source=source)


__all__ = ["emit_capability_result"]
