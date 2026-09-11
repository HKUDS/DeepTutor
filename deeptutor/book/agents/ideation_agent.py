"""
IdeationAgent
=============

Stage 1 of the BookEngine pipeline: turn an ``IdeationContext`` into a
``BookProposal`` that the user can confirm or edit before Spine generation.
"""

from __future__ import annotations

from typing import Any

from deeptutor.agents.base_agent import BaseAgent

from ..inputs import IdeationContext
from ..json_retry import json_with_reasoning_retry
from ..models import BookProposal


class IdeationAgent(BaseAgent):
    """LLM call that proposes a book given the four-source IdeationContext."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "en",
        # None, not "openai": BaseAgent falls back to the configured
        # provider only when this is falsy. Hard-coding it forced every
        # user onto the OpenAI wire format. Matches the pattern in
        # deeptutor/agents/research/pipeline.py:403.
        binding: str | None = None,
    ) -> None:
        super().__init__(
            module_name="book",
            agent_name="ideation_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
            binding=binding,
        )

    async def process(
        self,
        *,
        ideation_context: IdeationContext,
    ) -> BookProposal:
        from ..blocks._language import language_directive

        system_prompt = self.get_prompt("system") or _FALLBACK_SYSTEM
        system_prompt = system_prompt.rstrip() + language_directive(self.language)
        user_template = self.get_prompt("user_template") or _FALLBACK_USER
        user_prompt = user_template.format(ideation_context=ideation_context.render())

        async def _run(reasoning_effort: str | None) -> str:
            chunks: list[str] = []
            async for chunk in self.stream_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
                stage="ideation",
                reasoning_effort=reasoning_effort,
            ):
                chunks.append(chunk)
            return "".join(chunks)

        # ``title`` is the one field the proposal cannot be rebuilt without, so
        # it is what tells a thinking-only response apart from a real one.
        payload = await json_with_reasoning_retry(
            _run,
            expected_key="title",
            logger_instance=self.logger,
        )

        return self._coerce_proposal(payload, ideation_context)

    @staticmethod
    def _coerce_proposal(data: dict[str, Any], ctx: IdeationContext) -> BookProposal:
        chapters_raw = data.get("estimated_chapters", 0) or 0
        try:
            estimated = max(2, min(8, int(chapters_raw)))
        except (TypeError, ValueError):
            estimated = 4

        title = str(data.get("title") or "Untitled Book").strip() or "Untitled Book"
        return BookProposal(
            title=title[:120],
            description=str(data.get("description") or "").strip(),
            scope=str(data.get("scope") or "").strip(),
            target_level=str(data.get("target_level") or "mixed").strip(),
            estimated_chapters=estimated,
            rationale=str(data.get("rationale") or "").strip(),
        )


_FALLBACK_SYSTEM = (
    "Propose ONE coherent book that satisfies the learner's intent. "
    'Output JSON: {"title", "description", "scope", "target_level", '
    '"estimated_chapters", "rationale"}.'
)
_FALLBACK_USER = "{ideation_context}\n\nRespond with the JSON object only."


__all__ = ["IdeationAgent"]
