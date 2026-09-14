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

from ..blocks._llm_writer import llm_json
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
    # YuEdu fork: 数学交互 8 类（T030 交付：前端 math/ 目录 + 8 generator + 双语 prompts）
    BlockType.DESMOS,
    BlockType.GEOGEBRA,
    BlockType.GEOMETRY,
    BlockType.THREE_SCENE,
    BlockType.VENN,
    BlockType.COMPLEX,
    BlockType.FORMULA,
    BlockType.CHART,
}


# YuEdu fork: 数学交互 block 家族。静态模板与 LLM 白名单共用，学科门控按此过滤。
_MATH_BLOCK_TYPES = frozenset(
    {
        BlockType.DESMOS,
        BlockType.GEOGEBRA,
        BlockType.GEOMETRY,
        BlockType.THREE_SCENE,
        BlockType.VENN,
        BlockType.COMPLEX,
        BlockType.FORMULA,
        BlockType.CHART,
    }
)


def _math_blocks_allowed(chapter: Chapter) -> bool:
    """Subject gate for the math block family (best effort).

    TODO(T034): Chapter/Spine 目前没有结构化 subject 字段（models.py 未定义），
    inputs.json/exploration 里的主题信息也还未落到 Chapter 上，只能探测 chapter
    的 extra 字段（``Chapter.model_config = extra="allow"``）。拿不到学科信息时
    退化为始终可用；待主题信息落到 Chapter 后升级为强门控。
    """
    subject = str(
        getattr(chapter, "subject", "") or getattr(chapter, "discipline", "")
    ).strip().lower()
    if not subject:
        return True
    return not any(keyword in subject for keyword in _NON_MATH_SUBJECT_KEYWORDS)


# 明确非数学的学科关键词（小写子串匹配）。命中任一即视为非数学书籍，数学块不选用。
_NON_MATH_SUBJECT_KEYWORDS = (
    "literature",
    "language",
    "history",
    "poetry",
    "grammar",
    "geography",
    "语文",
    "文学",
    "语言",
    "英语",
    "历史",
    "地理",
    "诗词",
    "语法",
)


_TEMPLATES_V2: dict[ContentType, list[tuple[BlockType, dict[str, Any]]]] = {
    ContentType.THEORY: [
        (BlockType.SECTION, {"role": "introduction", "target_words": 1200}),
        (
            BlockType.FIGURE,
            {"variant": "diagram", "transition_in": "Visualising the core structure"},
        ),
        (BlockType.SECTION, {"role": "deep_dive", "target_words": 1600}),
        (
            BlockType.FORMULA,
            {
                "topic": "the core formulas of this chapter",
                "transition_in": "The core formulas, one line at a time",
            },
        ),
        (BlockType.CALLOUT, {"variant": "key_idea", "transition_in": "A key idea to remember"}),
        (
            BlockType.CODE,
            {
                "language": "python",
                "intent": "example",
                "transition_in": "A concrete example in code",
            },
        ),
        (
            BlockType.DESMOS,
            {
                "topic": "the key functions of this chapter",
                "transition_in": "Explore the functions interactively",
            },
        ),
        (
            BlockType.GEOGEBRA,
            {
                "topic": "the geometric construction behind this chapter",
                "transition_in": "Manipulate the geometry live",
            },
        ),
        (BlockType.SECTION, {"role": "synthesis", "target_words": 800}),
        (BlockType.QUIZ, {"num_questions": 3, "transition_in": "Check your understanding"}),
        (BlockType.FLASH_CARDS, {"count": 5, "transition_in": "Quick mental hooks"}),
        # YuEdu fork: 错题闭环——提取练习可落在理论页收尾，趁热回忆。
        (
            BlockType.RETRIEVAL_PRACTICE,
            {"count": 5, "transition_in": "Retrieve what you just read"},
        ),
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
            BlockType.CHART,
            {
                "topic": "the dataset this practice works on",
                "transition_in": "The data, at a glance",
            },
        ),
        (
            BlockType.GEOMETRY,
            {
                "topic": "the construction to try",
                "transition_in": "Now draw it yourself",
            },
        ),
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
        # YuEdu fork: 错题闭环——练习页收尾即模块末测验。
        (
            BlockType.MODULE_TEST,
            {"num_questions": 8, "transition_in": "Module check — pull it all together"},
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
        # YuEdu fork: 错题闭环——概念页同样适合提取练习收尾。
        (
            BlockType.RETRIEVAL_PRACTICE,
            {"count": 5, "transition_in": "Say it back in your own words"},
        ),
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
    allowed: set[BlockType] | None = None,
) -> list[Block]:
    template = _TEMPLATES_V2.get(chapter.content_type) or _TEMPLATES_V2[ContentType.THEORY]
    # YuEdu fork: 学科门控——非数学学科从静态模板中剔除数学交互块族。门控并入上游
    # allowed 过滤机制生效（语义等价于把 _MATH_BLOCK_TYPES 从 allowed 集合中排除）。
    if not _math_blocks_allowed(chapter):
        template = [(bt, params) for bt, params in template if bt not in _MATH_BLOCK_TYPES]
    blocks = [
        _build_block(bt, dict(params), chapter, depth=depth)
        for bt, params in template
        if allowed is None or bt == BlockType.SECTION or bt in allowed
    ]
    if blocks or allowed is None:
        return blocks
    return [
        _build_block(
            BlockType.SECTION,
            {"role": "core", "target_words": 1700},
            chapter,
            depth=depth,
        )
    ]


# ─────────────────────────────────────────────────────────────────────────────
# LLM layer
# ─────────────────────────────────────────────────────────────────────────────


PLANNABLE_BLOCK_TYPES = frozenset(
    {
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
        # YuEdu fork: 错题闭环三件（error_diagnosis / retrieval_practice /
        # module_test）。模板归属：retrieval_practice 入 THEORY/CONCEPT 页，
        # module_test 归模块末（PRACTICE 收尾），error_diagnosis 只在复习/
        # 诊断场景由 LLM 规划选用，不进静态模板——生成器在没有真实错题数据
        # 时会跳过该块，避免产出空卡。
        BlockType.RETRIEVAL_PRACTICE,
        BlockType.ERROR_DIAGNOSIS,
        BlockType.MODULE_TEST,
    }
)


PLANNER_DEFAULT_BLOCK_TYPES = frozenset(
    block_type for template in _TEMPLATES_V2.values() for block_type, _params in template
)


# YuEdu fork: 数学交互 8 类并入 LLM 可规划集合（= 上游 PLANNABLE_BLOCK_TYPES ∪
# _MATH_BLOCK_TYPES，即 DESMOS/GEOGEBRA/GEOMETRY/THREE_SCENE/VENN/COMPLEX/FORMULA/CHART）。
# 学科门控在 _static_plan / plan_blocks_async 里按章节过滤，见 _math_blocks_allowed。
_ALLOWED_LLM_TYPES = PLANNABLE_BLOCK_TYPES | _MATH_BLOCK_TYPES


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
    def plan_blocks(
        self,
        chapter: Chapter,
        *,
        depth: str | None = None,
        allowed: set[BlockType] | None = None,
    ) -> list[Block]:
        """Static-template plan. Always succeeds."""
        return _static_plan(chapter, phase=self.phase, depth=depth, allowed=allowed)

    # ── Async (LLM-first) ────────────────────────────────────────────
    async def plan_blocks_async(
        self,
        chapter: Chapter,
        *,
        exploration: ExplorationReport | None = None,
        language: str = "en",
        depth: str | None = None,
        allowed: set[BlockType] | None = None,
    ) -> list[Block]:
        if not self.llm_enabled:
            return self.plan_blocks(chapter, depth=depth, allowed=allowed)

        try:
            system_prompt, user_template = _architect_prompts(language)
            # ``llm_json`` rather than ``llm_text`` + a parse: it retries once
            # with thinking turned down when the first response is all hidden
            # tokens and no JSON, which is what silently dropped whole chapter
            # plans back to the static planner (#1316).
            payload = await llm_json(
                user_prompt=_architect_user_prompt(
                    chapter=chapter,
                    language=language,
                    exploration_summary=(exploration.summary if exploration else ""),
                    user_template=user_template,
                ),
                system_prompt=system_prompt,
                max_tokens=1200,
                temperature=0.6,
                language=language,
                expected_key="blocks",
            )
        except Exception as exc:
            logger.warning(f"SectionArchitect LLM failed → fallback static: {exc}")
            return self.plan_blocks(chapter, depth=depth, allowed=allowed)

        items = payload.get("blocks")
        if not isinstance(items, list) or not items:
            return self.plan_blocks(chapter, depth=depth, allowed=allowed)

        # YuEdu fork: 学科门控——非数学章节从 LLM 可选集合中剔除数学交互块族
        #（在 1.6.4 的 allowed 过滤之前生效，两层过滤正交：门控管学科、allowed 管版面）。
        allowed_types = _ALLOWED_LLM_TYPES
        if not _math_blocks_allowed(chapter):
            allowed_types = _ALLOWED_LLM_TYPES - _MATH_BLOCK_TYPES

        blocks: list[Block] = []
        for raw_item in items[:12]:
            if not isinstance(raw_item, dict):
                continue
            type_str = str(raw_item.get("type") or "").strip().lower()
            try:
                block_type = BlockType(type_str)
            except ValueError:
                continue
            if block_type not in allowed_types:
                continue
            if (
                allowed is not None
                and block_type != BlockType.SECTION
                and block_type not in allowed
            ):
                continue

            params = _safe_dict(raw_item.get("params"))
            if raw_item.get("transition_in"):
                params["transition_in"] = str(raw_item["transition_in"])[:240]
            if raw_item.get("focus"):
                params["focus"] = str(raw_item["focus"])[:240]
            blocks.append(_build_block(block_type, params, chapter, depth=depth))

        if not blocks:
            if allowed is not None:
                return [
                    _build_block(
                        BlockType.SECTION,
                        {"role": "core", "target_words": 1700},
                        chapter,
                        depth=depth,
                    )
                ]
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


__all__ = [
    "PLANNABLE_BLOCK_TYPES",
    "PLANNER_DEFAULT_BLOCK_TYPES",
    "PagePlanner",
    "SectionArchitect",
]
