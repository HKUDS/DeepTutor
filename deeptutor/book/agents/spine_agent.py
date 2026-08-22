"""
SpineAgent
==========

Stage 2 of the BookEngine pipeline. Given an approved ``BookProposal`` and
optional source material from the learner's knowledge bases, produce a
``Spine`` of chapters that the user can review and edit before compilation.
"""

from __future__ import annotations

from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.utils.json_parser import parse_json_response

from ..models import BookProposal, Chapter, ContentType, SourceAnchor, Spine


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


class SpineAgent(BaseAgent):
    """LLM call that designs the chapter tree of a book."""

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
            agent_name="spine_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
            binding=binding,
        )

    async def process(
        self,
        *,
        book_id: str,
        proposal: BookProposal,
        source_material: str = "",
    ) -> Spine:
        system_prompt = self.get_prompt("system") or _FALLBACK_SYSTEM
        user_template = self.get_prompt("user_template") or _FALLBACK_USER
        proposal_block = (
            f"title: {proposal.title}\n"
            f"description: {proposal.description}\n"
            f"scope: {proposal.scope}\n"
            f"target_level: {proposal.target_level}\n"
            f"estimated_chapters: {proposal.estimated_chapters}\n"
            f"rationale: {proposal.rationale}"
        )
        user_prompt = user_template.format(
            proposal_block=proposal_block,
            source_material=source_material.strip() or "(no extra material provided)",
        )

        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            stage="spine",
        ):
            chunks.append(chunk)
        raw = "".join(chunks)

        payload = parse_json_response(raw, logger_instance=self.logger, fallback={})
        if not isinstance(payload, dict):
            payload = {}

        chapters = self._coerce_chapters(payload.get("chapters"))
        if not chapters:
            # Fallback: fabricate a minimal spine so the pipeline can keep going
            chapters = [
                Chapter(
                    title=f"{proposal.title} – Overview",
                    learning_objectives=[
                        "Understand the scope of this book",
                        "Identify the key topics it will cover",
                    ],
                    content_type=ContentType.THEORY,
                    summary=proposal.description or "Overview chapter.",
                    order=0,
                )
            ]

        # Guarantee deterministic order field
        for idx, chapter in enumerate(chapters):
            chapter.order = idx

        return Spine(book_id=book_id, chapters=chapters)

    # ------------------------------------------------------------------ #
    # JSON → models
    # ------------------------------------------------------------------ #

    def _coerce_chapters(self, raw: Any) -> list[Chapter]:
        if not isinstance(raw, list):
            return []
        chapters: list[Chapter] = []
        seen_titles: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = _clip(str(item.get("title") or ""), 160)
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())

            objectives_raw = item.get("learning_objectives") or []
            if not isinstance(objectives_raw, list):
                objectives_raw = []
            objectives = [_clip(str(o), 200) for o in objectives_raw if str(o or "").strip()][:6]

            anchors = self._coerce_anchors(item.get("source_anchors"))
            content_type = self._coerce_content_type(item.get("content_type"))

            prereq_raw = item.get("prerequisites") or []
            if not isinstance(prereq_raw, list):
                prereq_raw = []
            prerequisites = [_clip(str(p), 160) for p in prereq_raw if str(p or "").strip()][:4]

            chapters.append(
                Chapter(
                    title=title,
                    learning_objectives=objectives,
                    content_type=content_type,
                    source_anchors=anchors,
                    prerequisites=prerequisites,
                    summary=_clip(str(item.get("summary") or ""), 400),
                )
            )
        return chapters

    @staticmethod
    def _coerce_content_type(raw: Any) -> ContentType:
        try:
            return ContentType(str(raw or "theory").strip().lower())
        except ValueError:
            return ContentType.THEORY

    @staticmethod
    def _coerce_anchors(raw: Any) -> list[SourceAnchor]:
        if not isinstance(raw, list):
            return []
        anchors: list[SourceAnchor] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            anchors.append(
                SourceAnchor(
                    kind=_clip(str(item.get("kind") or "manual"), 32),
                    kb_name=_clip(str(item.get("kb_name") or ""), 120),
                    ref=_clip(str(item.get("ref") or ""), 200),
                    snippet=_clip(str(item.get("snippet") or ""), 300),
                )
            )
        return anchors[:6]


_FALLBACK_SYSTEM = (
    "Design a chapter tree for the approved BookProposal. "
    'Output JSON: {"chapters": [{"title", "learning_objectives", "content_type", '
    '"source_anchors", "prerequisites", "summary"}]}.'
)
_FALLBACK_USER = (
    "Proposal:\n{proposal_block}\n\n"
    "Material:\n{source_material}\n\nRespond with the JSON object only."
)


__all__ = ["SpineAgent"]
