"""DeepSeek Harness backend with SDK streaming and headless CLI fallback.

The Python SDK is the only official surface that combines durable sessions
with structured runtime events, so it is preferred whenever installed.  The
published ``dsh --profile headless`` command remains useful for npm-only
installations, but it is deliberately one task per process and cannot resume.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any
import uuid

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.process import (
    not_found_detail,
    probe_version,
    stream_process_lines,
)
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_REASONING,
    EVENT_TEXT,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
    ConsultResult,
    DetectResult,
    SubagentEvent,
)

logger = logging.getLogger(__name__)

_HEADLESS_REASONING = "dsh: reasoning:"


class DeepSeekHarnessBackend(SubagentBackend):
    kind = "deepseek_harness"
    display_name = "DeepSeek Harness"
    cli_command = "dsh"

    async def detect(self) -> DetectResult:
        ok, text = await probe_version([self.cli_command, "--version"])
        sdk = _sdk_available()
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=ok or sdk,
            version=text if ok else ("Python SDK" if sdk else ""),
            detail="" if ok or sdk else not_found_detail(text, "dsh CLI / Python SDK not found"),
        )

    def _build_headless_command(
        self, question: str, *, config: BackendConfig, images: list[str] | None = None
    ) -> list[str]:
        prompt = question
        if config.system_prompt.strip():
            prompt = f"{config.system_prompt.strip()}\n\n{question}"
        if images:
            prompt += "\n\nAttached local files:\n" + "\n".join(f"- {path}" for path in images)
        return [self.cli_command, "--profile", "headless", *config.extra_args, prompt]

    async def consult(
        self,
        question: str,
        *,
        on_event: OnEvent,
        cwd: str | None = None,
        session_id: str | None = None,
        config: BackendConfig | None = None,
        images: list[str] | None = None,
        partner_id: str | None = None,  # noqa: ARG002 — partner-only
    ) -> ConsultResult:
        config = config or BackendConfig()
        if _sdk_available():
            return await self._consult_sdk(
                question,
                on_event=on_event,
                cwd=cwd,
                session_id=session_id,
                config=config,
                images=images,
            )
        return await self._consult_headless(
            question, on_event=on_event, cwd=cwd, config=config, images=images
        )

    async def _consult_headless(
        self,
        question: str,
        *,
        on_event: OnEvent,
        cwd: str | None,
        config: BackendConfig,
        images: list[str] | None,
    ) -> ConsultResult:
        cmd = self._build_headless_command(question, config=config, images=images)
        # The official headless profile creates one fresh agent per invocation.
        result = ConsultResult(session_id=None)
        answer_lines: list[str] = []
        reasoning_lines: list[str] = []
        reasoning_active = False
        returncode = "0"

        async def emit(
            kind: str, text: str, raw: dict[str, Any], meta: dict[str, Any] | None = None
        ) -> None:
            result.event_count += 1
            await on_event(SubagentEvent(kind=kind, text=text, raw=raw, meta=meta or {}))

        try:
            async for channel, line in stream_process_lines(cmd, cwd=cwd):
                if channel == "exit":
                    returncode = line
                    continue
                if channel == "stdout":
                    answer_lines.append(line)
                    text = "\n".join(answer_lines).strip()
                    if text:
                        await emit(
                            EVENT_TEXT,
                            text,
                            {"stream": "stdout"},
                            {"merge_id": "deepseek:final"},
                        )
                    continue
                stripped = line.strip()
                if stripped.lower() == _HEADLESS_REASONING:
                    reasoning_active = True
                    continue
                if reasoning_active and not stripped.lower().startswith("dsh:"):
                    reasoning_lines.append(line)
                    text = "\n".join(reasoning_lines).strip()
                    if text:
                        await emit(
                            EVENT_REASONING,
                            text,
                            {"stream": "stderr"},
                            {"merge_id": "deepseek:reasoning"},
                        )
                elif stripped:
                    reasoning_active = False
                    await emit(EVENT_LOG, line, {"stream": "stderr"})
        except Exception as exc:  # pragma: no cover - defensive process boundary
            logger.warning("deepseek headless consult failed: %s", exc, exc_info=True)
            result.success = False
            result.error = str(exc)
            await emit(EVENT_ERROR, result.error, {})

        result.final_text = "\n".join(answer_lines).strip()
        if returncode != "0" and result.success:
            result.success = False
            result.error = f"dsh headless exited with code {returncode}"
            await emit(EVENT_ERROR, result.error, {"returncode": returncode})
        elif not result.final_text and result.success:
            result.success = False
            result.error = "dsh headless returned no answer"
            await emit(EVENT_ERROR, result.error, {})
        return result

    async def _consult_sdk(
        self,
        question: str,
        *,
        on_event: OnEvent,
        cwd: str | None,
        session_id: str | None,
        config: BackendConfig,
        images: list[str] | None,
    ) -> ConsultResult:
        sid = session_id or f"deeptutor-{uuid.uuid4().hex}"
        result = ConsultResult(session_id=sid)
        loop = asyncio.get_running_loop()
        pending: list[Any] = []
        state: dict[str, dict[str, str]] = {"text": {}, "reasoning": {}}
        emitted_final = False

        prompt = question
        if config.system_prompt.strip() and not session_id:
            prompt = f"{config.system_prompt.strip()}\n\n{question}"
        if images:
            prompt += "\n\nAttached local files:\n" + "\n".join(f"- {path}" for path in images)

        async def publish(event: SubagentEvent) -> None:
            result.event_count += 1
            await on_event(event)

        def on_notification(notification: Any) -> None:
            nonlocal emitted_final
            for event in _sdk_notification_events(notification, state):
                if event.kind == EVENT_TEXT:
                    emitted_final = True
                pending.append(asyncio.run_coroutine_threadsafe(publish(event), loop))

        def run_sdk() -> Any:
            from deepseek_harness import DeepSeekHarness

            kwargs: dict[str, Any] = {
                "cwd": cwd or os.getcwd(),
                "dsh_home": _dsh_home(),
                "profile": "sdk",
            }
            if config.model:
                kwargs["model"] = config.model
            if config.effort:
                kwargs["reasoning_effort"] = config.effort
            with DeepSeekHarness(**kwargs) as harness:
                return harness.run(prompt, session_id=sid, on_notification=on_notification)

        try:
            sdk_result = await asyncio.to_thread(run_sdk)
            if pending:
                await asyncio.gather(*(asyncio.wrap_future(future) for future in pending))
            result.session_id = str(getattr(sdk_result, "session_id", sid) or sid)
            result.final_text = str(getattr(sdk_result, "final_response", "") or "").strip()
            finish_reason = str(getattr(sdk_result, "finish_reason", "") or "")
            if finish_reason == "error":
                result.success = False
                result.error = "DeepSeek Harness ended the turn with an error"
                await publish(SubagentEvent(EVENT_ERROR, result.error, {}))
            elif result.final_text and not emitted_final:
                await publish(SubagentEvent(EVENT_TEXT, result.final_text, {}))
            elif not result.final_text:
                result.success = False
                result.error = "DeepSeek Harness returned no answer"
                await publish(SubagentEvent(EVENT_ERROR, result.error, {}))
        except Exception as exc:  # never retry: the failed turn may have side effects
            logger.warning("deepseek SDK consult failed: %s", exc, exc_info=True)
            if pending:
                await asyncio.gather(
                    *(asyncio.wrap_future(future) for future in pending),
                    return_exceptions=True,
                )
            result.success = False
            result.error = str(exc)
            await publish(SubagentEvent(EVENT_ERROR, result.error, {}))
        return result


def _sdk_available() -> bool:
    try:
        return importlib.util.find_spec("deepseek_harness") is not None
    except (ImportError, ValueError):
        return False


def _dsh_home() -> str:
    configured = os.environ.get("DSH_HOME", "").strip()
    return str(Path(configured).expanduser() if configured else Path.home() / ".dsh")


def _sdk_notification_events(
    notification: Any, state: dict[str, dict[str, str]]
) -> list[SubagentEvent]:
    method = str(getattr(notification, "method", "") or "")
    payload = getattr(notification, "payload", {})
    if method != "session.event" or not isinstance(payload, dict):
        return []
    event = payload.get("event")
    if not isinstance(event, dict):
        return []
    etype = str(event.get("type") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    step = str(data.get("step") or "0")

    if etype == "assistant/chunk":
        chunk = data.get("chunk") if isinstance(data.get("chunk"), dict) else {}
        chunk_type = str(chunk.get("type") or "")
        if chunk_type not in {"text-delta", "reasoning-delta"}:
            return []
        channel = "text" if chunk_type == "text-delta" else "reasoning"
        delta = str(chunk.get("text") or "")
        if not delta:
            return []
        state[channel][step] = state[channel].get(step, "") + delta
        kind = EVENT_TEXT if channel == "text" else EVENT_REASONING
        return [
            SubagentEvent(
                kind,
                state[channel][step],
                event,
                {"merge_id": f"deepseek:{channel}:{step}"},
            )
        ]

    if etype == "assistant/message":
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        text = _content_text(message.get("content"), block_types={"text"})
        if not text or text == state["text"].get(step, ""):
            return []
        state["text"][step] = text
        return [
            SubagentEvent(
                EVENT_TEXT,
                text,
                event,
                {"merge_id": f"deepseek:text:{step}"},
            )
        ]

    if etype == "tool/call":
        name = str(data.get("name") or "tool")
        arguments = str(data.get("arguments") or "").strip()
        text = f"{name}({arguments})" if arguments else name
        return [SubagentEvent(EVENT_TOOL, text, event)]

    if etype == "tool/result":
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        text = _content_text(message.get("content")) or "(empty result)"
        return [SubagentEvent(EVENT_TOOL_RESULT, text, event)]

    if etype == "turn/end":
        reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
        kind = str(reason.get("kind") or "")
        if kind == "error":
            detail = str(reason.get("message") or "DeepSeek Harness turn failed")
            return [SubagentEvent(EVENT_ERROR, detail, event)]
    return []


def _content_text(content: Any, *, block_types: set[str] | None = None) -> str:
    allowed = block_types or {"text", "reasoning"}
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type in allowed and block.get("text"):
            parts.append(str(block["text"]))
        elif block_type == "tool-result":
            nested = _content_text(block.get("content"), block_types=allowed)
            if nested:
                parts.append(nested)
    return "\n".join(parts).strip()


__all__ = ["DeepSeekHarnessBackend"]
