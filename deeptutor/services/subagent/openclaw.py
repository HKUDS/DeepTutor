"""OpenClaw backend — run one persistent Gateway-backed agent turn.

The official ``openclaw agent --json`` command reserves stdout for one final
Gateway response and sends diagnostics to stderr.  A DeepTutor-owned explicit
session key makes follow-up consults deterministic; operators can add
``--local`` through ``extra_args`` when they prefer the embedded runtime.
"""

from __future__ import annotations

import json
import logging
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
    EVENT_TEXT,
    ConsultResult,
    DetectResult,
    SubagentEvent,
)

logger = logging.getLogger(__name__)


class OpenClawBackend(SubagentBackend):
    kind = "openclaw"
    display_name = "OpenClaw"
    cli_command = "openclaw"

    async def detect(self) -> DetectResult:
        ok, text = await probe_version([self.cli_command, "--version"])
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=ok,
            version=text if ok else "",
            detail="" if ok else not_found_detail(text, "openclaw CLI not found on PATH"),
        )

    def _build_command(
        self,
        question: str,
        *,
        session_id: str,
        fresh_session: bool,
        config: BackendConfig,
        images: list[str] | None = None,
    ) -> list[str]:
        prompt = question
        if config.system_prompt.strip() and fresh_session:
            prompt = f"{config.system_prompt.strip()}\n\n{question}"
        if images:
            prompt += "\n\nAttached local files:\n" + "\n".join(f"- {path}" for path in images)
        cmd = [
            self.cli_command,
            "agent",
            "--session-key",
            session_id,
            "--json",
            "--timeout",
            "0",
        ]
        if config.model:
            cmd += ["--model", config.model]
        if config.effort:
            cmd += ["--thinking", config.effort]
        cmd += list(config.extra_args)
        cmd += ["--message", prompt]
        return cmd

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
        fresh_session = not session_id
        sid = session_id or f"deeptutor-{uuid.uuid4().hex}"
        cmd = self._build_command(
            question,
            session_id=sid,
            fresh_session=fresh_session,
            config=config,
            images=images,
        )
        result = ConsultResult(session_id=sid)
        stdout_lines: list[str] = []
        returncode = "0"

        async def emit(kind: str, text: str, raw: dict[str, Any]) -> None:
            result.event_count += 1
            await on_event(SubagentEvent(kind=kind, text=text, raw=raw))

        try:
            async for channel, line in stream_process_lines(cmd, cwd=cwd):
                if channel == "exit":
                    returncode = line
                elif channel == "stderr":
                    if line.strip():
                        await emit(EVENT_LOG, line, {"stream": "stderr"})
                else:
                    stdout_lines.append(line)
        except Exception as exc:  # pragma: no cover - defensive process boundary
            logger.warning("openclaw consult failed: %s", exc, exc_info=True)
            result.success = False
            result.error = str(exc)
            await emit(EVENT_ERROR, result.error, {})
            return result

        raw_stdout = "\n".join(stdout_lines).strip()
        payload = _parse_json(raw_stdout)
        if payload is None:
            result.success = False
            result.error = (
                f"openclaw exited with code {returncode}"
                if returncode != "0"
                else "openclaw did not return valid JSON"
            )
            if raw_stdout:
                await emit(EVENT_LOG, raw_stdout, {"stream": "stdout"})
            await emit(EVENT_ERROR, result.error, {"returncode": returncode})
            return result

        text = _response_text(payload)
        status = str(payload.get("status") or "").lower()
        explicit_failure = payload.get("ok") is False or (
            bool(status) and status not in {"ok", "success", "completed"}
        )
        if returncode != "0" or explicit_failure:
            result.success = False
            result.error = _response_error(payload) or f"openclaw exited with code {returncode}"
            await emit(EVENT_ERROR, result.error, payload)
        elif not text:
            result.success = False
            result.error = _response_error(payload) or "openclaw returned no reply"
            await emit(EVENT_ERROR, result.error, payload)
        else:
            result.final_text = text
            await emit(EVENT_TEXT, text, payload)
        return result


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _response_text(payload: dict[str, Any]) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    payloads = result.get("payloads") if isinstance(result, dict) else None
    if isinstance(payloads, list):
        parts = [
            str(item.get("text") or "").strip()
            for item in payloads
            if isinstance(item, dict) and item.get("text")
        ]
        if parts:
            return "\n\n".join(parts)
    for key in ("final", "text", "response", "output"):
        value = result.get(key) if isinstance(result, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _response_error(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str) and error.strip():
        return error.strip()
    summary = payload.get("summary")
    return str(summary).strip() if isinstance(summary, str) else ""


__all__ = ["OpenClawBackend"]
