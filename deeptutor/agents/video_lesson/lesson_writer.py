"""The agent that writes a Remotion lesson (Lesson.tsx) against the shipped kit."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id

from .narration import NarrationLine
from .runtime import ASSETS_DIR

_JSON_BLOCK = re.compile(r"```json[ \t]*\n(.*?)\n```", re.S)
_TSX_BLOCK = re.compile(r"```(?:tsx|typescript|ts|jsx)[ \t]*\n(.*?)\n```", re.S)


@dataclass
class LessonDraft:
    title: str
    summary: str
    code: str
    raw: str
    narration: list[NarrationLine] = field(default_factory=list)


def parse_draft(reply: str) -> LessonDraft:
    """Pull the meta block and the longest code block out of a reply; empty code means unusable."""
    blocks = _TSX_BLOCK.findall(reply)
    code = max(blocks, key=len).strip() if blocks else ""
    meta: dict[str, Any] = {}
    match = _JSON_BLOCK.search(reply)
    if match:
        try:
            loaded = json.loads(match.group(1))
            meta = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            meta = {}
    narration = [
        NarrationLine(str(item["id"]).strip(), str(item["text"]).strip())
        for item in meta.get("narration") or []
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and str(item.get("text") or "").strip()
    ]
    return LessonDraft(
        title=str(meta.get("title") or "").strip(),
        summary=str(meta.get("summary") or "").strip(),
        code=code,
        raw=reply,
        narration=narration,
    )


class LessonWriterAgent(BaseAgent):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(
            module_name="video_lesson",
            agent_name="lesson_writer",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self._messages: list[dict[str, str]] = []

    def start(self, *, user_input: str, history: str) -> None:
        system = self.get_prompt("system")
        template = self.get_prompt("user_template")
        if not system or not template:
            raise ValueError("LessonWriterAgent prompts are not configured.")
        # The kit source holds braces, so it is spliced in rather than str.format-ed.
        system = system.replace(
            "{kit_source}", (ASSETS_DIR / "kit.tsx").read_text(encoding="utf-8")
        )
        user = template.format(user_input=user_input.strip(), history=history.strip() or "-")
        self._messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def add_feedback(self, *, previous: str, stage: str, errors: list[str]) -> None:
        """Keep the failed reply in the conversation and ask for a fix."""
        template = self.get_prompt("retry_template") or "{stage}\n{errors}"
        listed = "\n".join(f"- {e}" for e in errors[:20]) or "- (no detail)"
        self._messages += [
            {"role": "assistant", "content": previous},
            {"role": "user", "content": template.format(stage=stage, errors=listed)},
        ]

    async def write(self, *, attempt: int) -> LessonDraft:
        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt="",
            system_prompt="",
            messages=self._messages,
            stage="code_generation",
            trace_meta=build_trace_metadata(
                call_id=new_call_id("video-lesson"),
                phase="code_generation",
                label="Write lesson" if attempt == 1 else f"Fix lesson (attempt {attempt})",
                call_kind="video_lesson_code",
                trace_role="generate" if attempt == 1 else "repair",
                trace_kind="llm_output",
                attempt=attempt,
            ),
        ):
            chunks.append(chunk)
        return parse_draft("".join(chunks))

    async def process(self, *, attempt: int = 1) -> LessonDraft:
        return await self.write(attempt=attempt)


__all__ = ["LessonDraft", "LessonWriterAgent", "parse_draft"]
