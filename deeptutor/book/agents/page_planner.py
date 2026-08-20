"""
Section Architect (formerly PagePlanner)
========================================

Stage 3 of the BookEngine pipeline. Translate a ``Chapter`` into a concrete
ordered list of ``Block`` shells (type + params + dependencies) ready for the
``BookCompiler`` to fill in.

BookEngine v2 architecture
--------------------------

The architect runs in two layers:

1. **LLM layer (``SectionArchitect.plan_blocks_async``)** — best effort. Calls
   one LLM with the chapter spec and (optionally) the cached
   ``ExplorationReport`` summary. The LLM returns a JSON ``blocks`` list with
   ``type``, ``focus``, ``transition_in``, and free-form ``params``. We
   validate / clip / coerce, then return.

2. **Static layer (``SectionArchitect.plan_blocks``)** — always available.
   Deterministic templates keyed on ``ContentType`` that *already* include
   ``SECTION`` blocks for chapter-grade prose plus optional ``transition_in``
   strings that the compiler turns into a short ``payload['bridge_text']``
   on the target block. Used as fallback when the LLM call is disabled or
   fails.

The legacy class name ``PagePlanner`` is kept as an alias to avoid touching
every importer in the codebase.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.utils.json_parser import parse_json_response

from ..blocks._llm_writer import llm_text
from ..blocks._prompts import get_book_prompt, load_book_prompts
from ..models import (
    Block,
    BlockStatus,
    BlockType,
    Chapter,
    ContentType,
    ExplorationReport,
    depth_scale,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Static templates (v2). Each entry is (BlockType, params overrides). SECTION
# blocks carry the long-form chapter content; supporting blocks may declare a
# ``transition_in`` so the compiler attaches a short ``bridge_text`` paragraph
# onto that block's payload.
# ─────────────────────────────────────────────────────────────────────────────


_PHASE1_TYPES = {
    BlockType.TEXT,
    BlockType.CALLOUT,
    BlockType.QUIZ,
    BlockType.SECTION,
    BlockType.FIGURE,
    BlockType.INTERACTIVE,
    BlockType.CODE,
    BlockType.FLASH_CARDS,
    BlockType.TIMELINE,
    BlockType.ANIMATION,
}


_TEMPLATES_V2: dict[ContentType, list[tuple[BlockType, dict[str, Any]]]] = {
    ContentType.THEORY: [
        (BlockType.SECTION, {"role": "introduction", "target_words": 1200}),
        (
            BlockType.FIGURE,
            {"variant": "diagram", "transition_in": "Visualising the core structure"},
        ),
        (BlockType.SECTION, {"role": "deep_dive", "target_words": 1600}),
        (BlockType.CALLOUT, {"variant": "key_idea", "transition_in": "A key idea to remember"}),
        (
            BlockType.CODE,
            {
                "language": "python",
                "intent": "example",
                "transition_in": "A concrete example in code",
            },
        ),
        (BlockType.SECTION, {"role": "synthesis", "target_words": 800}),
        (BlockType.QUIZ, {"num_questions": 3, "transition_in": "Check your understanding"}),
        (BlockType.FLASH_CARDS, {"count": 5, "transition_in": "Quick mental hooks"}),
    ],
    ContentType.DERIVATION: [
        (BlockType.SECTION, {"role": "setup", "target_words": 1400}),
        (
            BlockType.ANIMATION,
            {"focus": "core derivation", "transition_in": "Step through the derivation visually"},
        ),
        (BlockType.SECTION, {"role": "formal_proof", "target_words": 1200}),
        (
            BlockType.CODE,
            {
                "language": "python",
                "intent": "verify",
                "transition_in": "Verify the result numerically",
            },
        ),
        (
            BlockType.CALLOUT,
            {"variant": "insight", "transition_in": "What this result really means"},
        ),
        (BlockType.SECTION, {"role": "interpretation", "target_words": 1000}),
        (BlockType.QUIZ, {"num_questions": 2, "transition_in": "Test your derivation skills"}),
    ],
    ContentType.HISTORY: [
        (BlockType.SECTION, {"role": "context", "target_words": 1200}),
        (BlockType.TIMELINE, {"transition_in": "The key milestones"}),
        (BlockType.SECTION, {"role": "narrative", "target_words": 1500}),
        (BlockType.FIGURE, {"variant": "illustration", "transition_in": "A period illustration"}),
        (BlockType.CALLOUT, {"variant": "connection", "transition_in": "Why this matters today"}),
        (BlockType.SECTION, {"role": "analysis", "target_words": 1000}),
        (BlockType.QUIZ, {"num_questions": 2, "transition_in": "Quick recap quiz"}),
    ],
    ContentType.PRACTICE: [
        (BlockType.SECTION, {"role": "brief", "target_words": 1000}),
        (BlockType.QUIZ, {"num_questions": 3, "difficulty": "easy", "transition_in": "Warm up"}),
        (
            BlockType.CODE,
            {"language": "python", "intent": "scaffold", "transition_in": "Try it yourself"},
        ),
        (BlockType.SECTION, {"role": "walkthrough", "target_words": 1200}),
        (
            BlockType.INTERACTIVE,
            {"interaction": "guided exercise", "transition_in": "Practise interactively"},
        ),
        (
            BlockType.QUIZ,
            {"num_questions": 3, "difficulty": "hard", "transition_in": "Now push further"},
        ),
        (
            BlockType.CALLOUT,
            {"variant": "common_pitfall", "transition_in": "Watch out for these traps"},
        ),
    ],
    ContentType.CONCEPT: [
        (BlockType.SECTION, {"role": "definition", "target_words": 1400}),
        (BlockType.FIGURE, {"variant": "mindmap", "transition_in": "Map the related concepts"}),
        (BlockType.SECTION, {"role": "examples", "target_words": 1200}),
        (BlockType.FLASH_CARDS, {"count": 5, "transition_in": "Hooks for recall"}),
        (BlockType.CALLOUT, {"variant": "common_pitfall", "transition_in": "Watch out for these"}),
        (BlockType.FIGURE, {"variant": "comparison", "transition_in": "Side-by-side comparison"}),
        (BlockType.QUIZ, {"num_questions": 3, "transition_in": "Self-check"}),
    ],
}


_PHASE1_SUBSTITUTES: dict[BlockType, tuple[BlockType, dict[str, Any]]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Static fallback planner
# ─────────────────────────────────────────────────────────────────────────────


def _build_block(
    block_type: BlockType,
    params: dict[str, Any],
    chapter: Chapter,
    *,
    depth: str | None = None,
) -> Block:
    transition_in = params.pop("transition_in", "")
    # Every plan — static template or LLM-authored — funnels through here, so
    # this is the single place the reader's brief/standard/deep choice has to
    # be applied. Templates used to hard-code ~3,600 words per chapter for
    # everyone.
    target = params.get("target_words")
    if isinstance(target, (int, float)):
        params["target_words"] = max(120, round(float(target) * depth_scale(depth)))
    full_params: dict[str, Any] = {
        "chapter_title": chapter.title,
        "chapter_summary": chapter.summary,
        "objectives": chapter.learning_objectives,
        "anchors": [a.model_dump() for a in chapter.source_anchors],
        **params,
    }
    metadata: dict[str, Any] = {}
    if transition_in:
        metadata["transition_in"] = transition_in
    return Block(
        type=block_type,
        status=BlockStatus.PENDING,
        params=full_params,
        metadata=metadata,
    )


def _static_plan(
    chapter: Chapter,
    *,
    phase: int,
    depth: str | None = None,
) -> list[Block]:
    template = _TEMPLATES_V2.get(chapter.content_type) or _TEMPLATES_V2[ContentType.THEORY]
    return [_build_block(bt, dict(params), chapter, depth=depth) for bt, params in template]


# ─────────────────────────────────────────────────────────────────────────────
# LLM layer
# ─────────────────────────────────────────────────────────────────────────────


_ALLOWED_LLM_TYPES = {
    BlockType.SECTION,
    BlockType.TEXT,
    BlockType.CALLOUT,
    BlockType.QUIZ,
    BlockType.FLASH_CARDS,
    BlockType.FIGURE,
    BlockType.INTERACTIVE,
    BlockType.ANIMATION,
    BlockType.CODE,
    BlockType.TIMELINE,
}


def _architect_prompts(language: str) -> tuple[str, str]:
    """Return (system_prompt, user_template) for the SectionArchitect.

    The catalog block list and design principles live in
    ``deeptutor/book/prompts/{en,zh}/page_planner.yaml`` so they can be
    iterated on without touching python.
    """
    bundle = load_book_prompts("page_planner", language)
    catalog = get_book_prompt(bundle, "block_catalog")
    system_prompt = get_book_prompt(bundle, "architect_system").replace("{block_catalog}", catalog)
    user_template = get_book_prompt(bundle, "architect_user")
    return system_prompt, user_template


def _architect_user_prompt(
    *,
    chapter: Chapter,
    language: str,
    exploration_summary: str,
    user_template: str,
) -> str:
    none_label = "(无)" if language == "zh" else "(none)"
    objs = "\n".join(f"- {o}" for o in chapter.learning_objectives) or none_label
    return user_template.format(
        chapter_title=chapter.title,
        chapter_summary=chapter.summary or none_label,
        content_type=chapter.content_type.value,
        objectives_block=objs,
        exploration_summary=exploration_summary or none_label,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public class
# ─────────────────────────────────────────────────────────────────────────────


class SectionArchitect:
    """Pick block sequence for a chapter / page (LLM-aware, with fallback)."""

    def __init__(self, *, phase: int = 1, llm_enabled: bool = True) -> None:
        """
        Args:
            phase: 1 → only emit text/callout/quiz/section blocks; 2+ → use the
                   full template (includes figure/interactive/animation/etc.).
            llm_enabled: When True, ``plan_blocks_async`` will try the LLM
                   layer first and only fall back on failure. ``plan_blocks``
                   (sync) always uses the static layer.
        """
        self.phase = phase
        self.llm_enabled = llm_enabled

    # ── Sync (legacy) ────────────────────────────────────────────────
    def plan_blocks(self, chapter: Chapter, *, depth: str | None = None) -> list[Block]:
        """Static-template plan. Always succeeds."""
        return _static_plan(chapter, phase=self.phase, depth=depth)

    # ── Async (LLM-first) ────────────────────────────────────────────
    async def plan_blocks_async(
        self,
        chapter: Chapter,
        *,
        exploration: ExplorationReport | None = None,
        language: str = "en",
        depth: str | None = None,
    ) -> list[Block]:
        if not self.llm_enabled:
            return self.plan_blocks(chapter, depth=depth)

        try:
            system_prompt, user_template = _architect_prompts(language)
            raw = await llm_text(
                user_prompt=_architect_user_prompt(
                    chapter=chapter,
                    language=language,
                    exploration_summary=(exploration.summary if exploration else ""),
                    user_template=user_template,
                ),
                system_prompt=system_prompt,
                max_tokens=1200,
                temperature=0.6,
                response_format={"type": "json_object"},
                language=language,
            )
        except Exception as exc:
            logger.warning(f"SectionArchitect LLM failed → fallback static: {exc}")
            return self.plan_blocks(chapter, depth=depth)

        payload = parse_json_response(raw, logger_instance=logger, fallback={})
        if not isinstance(payload, dict):
            return self.plan_blocks(chapter, depth=depth)

        items = payload.get("blocks")
        if not isinstance(items, list) or not items:
            return self.plan_blocks(chapter, depth=depth)

        blocks: list[Block] = []
        for raw_item in items[:12]:
            if not isinstance(raw_item, dict):
                continue
            type_str = str(raw_item.get("type") or "").strip().lower()
            try:
                block_type = BlockType(type_str)
            except ValueError:
                continue
            if block_type not in _ALLOWED_LLM_TYPES:
                continue

            params = _safe_dict(raw_item.get("params"))
            if raw_item.get("transition_in"):
                params["transition_in"] = str(raw_item["transition_in"])[:240]
            if raw_item.get("focus"):
                params["focus"] = str(raw_item["focus"])[:240]
            blocks.append(_build_block(block_type, params, chapter, depth=depth))

        if not blocks:
            return self.plan_blocks(chapter, depth=depth)

        # Coverage guarantee: ensure at least one SECTION block, otherwise we
        # silently lose chapter prose. Inject one at the front if missing.
        if self.phase >= 1 and not any(b.type == BlockType.SECTION for b in blocks):
            blocks.insert(
                0,
                _build_block(
                    BlockType.SECTION,
                    {"role": "core", "target_words": 1700},
                    chapter,
                    depth=depth,
                ),
            )

        return blocks


def _safe_dict(value: Any) -> dict[str, Any]:
    return value.copy() if isinstance(value, dict) else {}


# Legacy alias used by existing callers (``compiler.py`` historically imported
# ``PagePlanner``). Calling ``.plan_blocks(chapter)`` keeps the old contract.
class PagePlanner(SectionArchitect):
    """Backward-compatible alias for :class:`SectionArchitect`."""

    def __init__(self, *, phase: int = 1) -> None:
        super().__init__(phase=phase, llm_enabled=False)


__all__ = ["PagePlanner", "SectionArchitect"]
