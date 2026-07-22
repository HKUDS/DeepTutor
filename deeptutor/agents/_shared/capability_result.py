"""Shared plumbing for capability ``run()`` endpoints.

Capabilities all converge on the same final emission:

    await stream.result({"response": ..., ...}, source="<cap>")

The basic chat capability also attaches a per-turn ``cost_summary`` so the
frontend can render ``$cost · tokens · calls`` in its message footer.
Several other capabilities used to duplicate that merge inline (solve,
research, question followup) and the rest skipped it entirely (visualize,
math_animator), so the footer only appeared for some
capabilities. This module centralizes the merge + emit so every capability
emits the same envelope shape.
"""

from __future__ import annotations

from typing import Any

from deeptutor.core.agentic.usage import UsageTracker
from deeptutor.core.stream_bus import StreamBus


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
    await stream.result(payload, source=source)


__all__ = ["emit_capability_result"]
