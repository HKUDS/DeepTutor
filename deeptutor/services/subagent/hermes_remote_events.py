"""Map Hermes gateway lifecycle events onto DeepTutor event channels."""

from __future__ import annotations

from typing import Any

import httpx

from deeptutor.services.subagent.hermes_remote_client import (
    HermesRemoteClient,
    HermesRemoteHTTPError,
    HermesRemoteProtocolError,
)
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_REASONING,
    EVENT_TEXT,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
    ConsultResult,
)


class HermesRemoteEventMapper:
    """Translate one run's SSE events while preserving cumulative answer text."""

    def __init__(
        self,
        client: HermesRemoteClient,
        run_id: str,
        result: ConsultResult,
        emit: Any,
        *,
        auto_approve: bool,
    ) -> None:
        self._client = client
        self._run_id = run_id
        self._result = result
        self._emit = emit
        self._auto_approve = auto_approve

    async def handle(self, event: dict[str, Any], emitted_text: str) -> str:
        """Map one parsed event and return the updated cumulative answer."""
        name = str(event.get("event") or "")
        if name == "gateway.keepalive":
            pass
        elif name == "message.delta":
            delta = str(event.get("delta") or "")
            emitted_text += delta
            self._result.final_text = emitted_text.strip()
            if delta:
                await self._emit(
                    EVENT_TEXT,
                    emitted_text,
                    event,
                    {"merge_id": "hermes_remote:final"},
                )
        elif name == "run.completed":
            output = str(event.get("output") or emitted_text).strip()
            self._result.final_text = output
            if output and output != emitted_text.strip():
                await self._emit(
                    EVENT_TEXT,
                    output,
                    event,
                    {"merge_id": "hermes_remote:final"},
                )
        elif name == "run.failed":
            self._result.success = False
            self._result.error = "run_failed"
            await self._emit(EVENT_ERROR, self._result.error, event)
        elif name == "run.cancelled":
            self._result.success = False
            self._result.error = "run_cancelled"
            await self._emit(EVENT_ERROR, self._result.error, event)
        elif name == "approval.request":
            choice = "once" if self._auto_approve else "deny"
            try:
                await self._client.post_json(
                    f"/v1/runs/{self._run_id}/approval",
                    {"choice": choice},
                )
            except (HermesRemoteHTTPError, HermesRemoteProtocolError, httpx.RequestError):
                self._result.success = False
                self._result.error = "approval_failed"
                await self._emit(EVENT_ERROR, self._result.error, {})
                await self._stop()
                return emitted_text
            verb = "approved" if self._auto_approve else "denied"
            await self._emit(EVENT_LOG, f"approval {verb}", event)
        elif name == "tool.started":
            label = str(event.get("tool") or "tool")
            preview = str(event.get("preview") or "")
            await self._emit(
                EVENT_TOOL,
                f"{label}: {preview}".strip(": "),
                event,
                {"merge_id": f"hermes_remote:tool:{label}"},
            )
        elif name == "tool.completed":
            label = str(event.get("tool") or "tool")
            status = "error" if event.get("error") else "complete"
            await self._emit(
                EVENT_TOOL_RESULT,
                f"{label}: {status}",
                event,
                {"merge_id": f"hermes_remote:tool:{label}"},
            )
        elif name == "reasoning.available":
            await self._emit(EVENT_REASONING, str(event.get("text") or ""), event)
        elif name:
            await self._emit(EVENT_LOG, name, event)
        else:
            await self._emit(EVENT_LOG, "gateway event", event)
        return emitted_text

    async def _stop(self) -> None:
        try:
            await self._client.post_json(f"/v1/runs/{self._run_id}/stop", {})
        except (HermesRemoteHTTPError, HermesRemoteProtocolError, httpx.RequestError):
            return


__all__ = ["HermesRemoteEventMapper"]
