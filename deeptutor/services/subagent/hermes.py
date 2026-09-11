"""Hermes Agent backend — drive ``hermes chat`` through its quiet contract.

``hermes chat --quiet --query`` is the project's machine-readable one-shot
surface: stdout contains only the final answer and stderr ends with
``session_id: <id>``.  Quiet mode intentionally suppresses tool and reasoning
callbacks, so this adapter does not invent intermediate events that Hermes did
not expose.  The returned id is passed to ``--resume`` on the next consult.
"""

from __future__ import annotations

import logging
import re
from typing import Any

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

_SESSION_LINE = re.compile(r"^\s*session_id:\s*(\S+)\s*$", re.IGNORECASE)


class HermesBackend(SubagentBackend):
    kind = "hermes"
    display_name = "Hermes Agent"
    cli_command = "hermes"

    async def detect(self) -> DetectResult:
        ok, text = await probe_version([self.cli_command, "--version"])
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=ok,
            version=text if ok else "",
            detail="" if ok else not_found_detail(text, "hermes CLI not found on PATH"),
        )

    def _build_command(
        self,
        question: str,
        *,
        session_id: str | None,
        config: BackendConfig,
        images: list[str] | None = None,
    ) -> list[str]:
        prompt = question
        if config.system_prompt.strip() and not session_id:
            prompt = f"{config.system_prompt.strip()}\n\n{question}"

        cmd = [self.cli_command, "chat", "--quiet"]
        if session_id:
            cmd += ["--resume", session_id]
        if config.model:
            cmd += ["--model", config.model]
        if config.effort:
            cmd += ["--reasoning", config.effort]
        if config.auto_approve:
            cmd.append("--yolo")
        if images:
            # Hermes currently exposes one --image argument. Keep additional
            # paths visible to its file tools instead of silently dropping them.
            cmd += ["--image", images[0]]
            if len(images) > 1:
                prompt += "\n\nAdditional attached files:\n" + "\n".join(
                    f"- {path}" for path in images[1:]
                )
        cmd += list(config.extra_args)
        cmd += ["--query", prompt]
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
        cmd = self._build_command(question, session_id=session_id, config=config, images=images)
        result = ConsultResult(session_id=session_id)
        answer_lines: list[str] = []
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
                if channel == "stderr":
                    match = _SESSION_LINE.match(line)
                    if match:
                        result.session_id = match.group(1)
                    elif line.strip():
                        await emit(EVENT_LOG, line, {"stream": "stderr"})
                    continue
                answer_lines.append(line)
                text = "\n".join(answer_lines).strip()
                if text:
                    await emit(
                        EVENT_TEXT,
                        text,
                        {"stream": "stdout"},
                        {"merge_id": "hermes:final"},
                    )
        except Exception as exc:  # pragma: no cover - defensive process boundary
            logger.warning("hermes consult failed: %s", exc, exc_info=True)
            result.success = False
            result.error = str(exc)
            await emit(EVENT_ERROR, result.error, {})

        result.final_text = "\n".join(answer_lines).strip()
        if returncode != "0" and result.success:
            result.success = False
            result.error = f"hermes exited with code {returncode}"
            await emit(EVENT_ERROR, result.error, {"returncode": returncode})
        elif not result.final_text and result.success:
            result.success = False
            result.error = "hermes returned no answer"
            await emit(EVENT_ERROR, result.error, {})
        return result


__all__ = ["HermesBackend"]
