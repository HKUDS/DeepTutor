"""
BookCompiler
============

Drives the per-page block-generation pipeline.

Responsibilities
----------------
1. Plan a page (call :class:`PagePlanner`) if it has no blocks yet.
2. For each block, look up the right :class:`BlockGenerator` and run it.
3. Persist the page after every block (atomic incremental progress).
4. Emit fine-grained ``BookStream`` events so the frontend can stream
   blocks as they become ready.
5. Aggregate page status (READY / PARTIAL / ERROR).

The compiler is intentionally isolated from the orchestrator (``BookEngine``)
so it can be reused by background workers, recovery flows, and ad-hoc
re-generation requests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time

from .agents.page_planner import SectionArchitect
from .blocks.base import BlockContext, get_block_registry
from .blocks.text import generate_bridge_text
from .models import (
    Block,
    BlockStatus,
    Chapter,
    ExplorationReport,
    Page,
    PageStatus,
)
from .storage import BookStorage, get_book_storage
from .streaming import STAGE_BLOCK, STAGE_COMPILATION, STAGE_PAGE_PLAN, BookStream

logger = logging.getLogger(__name__)


# Failure kinds (from ``blocks.base._classify_failure``) that say something is
# wrong with the *provider account* rather than with this particular block —
# a bad API key, an exhausted quota, an outage. One is worth retrying; a page
# made entirely of them means the next page will fail the same way.
SYSTEMIC_FAILURE_KINDS = frozenset({"rate_limit", "provider_error", "timeout"})


def systemic_failure_reason(page: Page) -> str:
    """Why *page* looks like a provider/account failure — ``""`` if it doesn't.

    Lets the engine's breaker tell "this chapter didn't work" apart from
    "nothing is going to work until the user fixes their setup", and hands back
    a reason concrete enough to show the reader ("rate_limit: 429 …") instead
    of a bare page-level tally.
    """
    failed = [b for b in page.blocks if b.status == BlockStatus.ERROR]
    if not failed:
        return ""

    systemic = [
        b
        for b in failed
        if str((b.metadata or {}).get("failure", {}).get("kind", "")) in SYSTEMIC_FAILURE_KINDS
    ]
    # A single flaky block is normal; a page that is *mostly* provider errors
    # means the next page will hit the same wall.
    if len(systemic) * 2 < len(failed):
        return ""

    failure = (systemic[0].metadata or {}).get("failure", {})
    kind = str(failure.get("kind") or "provider_error")
    message = str(failure.get("message") or "").strip()
    return f"{kind}: {message}" if message else kind


@dataclass
class CompilerOptions:
    """Knobs that influence how a page is compiled."""

    phase: int = 1
    """1 → only emit text/callout/quiz blocks (Phase 1 substitution)."""

    rag_enabled: bool = True
    """Whether block generators may call the RAG tool."""

    block_concurrency: int = 1
    """Maximum number of blocks generated in parallel for a single page.

    Phase 1 uses sequential (1) for predictable streaming order; later phases
    can crank this up for faster compilation.
    """

    persist_after_each_block: bool = True
    """Save the page JSON to disk after every block completes."""

    architect_llm_enabled: bool = True
    """When True, ``SectionArchitect`` may use the LLM layer to plan blocks."""

    block_retry_attempts: int = 1
    """Extra attempts for a block whose failure metadata says ``retryable``.

    Transient provider hiccups (a 429, a stalled response) are the single most
    common reason a block dies, and one backed-off retry recovers most of them
    — the difference between a chapter with a hole in it and a whole one.
    """

    block_retry_backoff_seconds: float = 2.0
    """Base delay before a retry; doubles per attempt."""


class BookCompiler:
    """Compile a single page (or list of pages) end-to-end."""

    def __init__(
        self,
        *,
        storage: BookStorage | None = None,
        options: CompilerOptions | None = None,
    ) -> None:
        self.storage = storage or get_book_storage()
        self.options = options or CompilerOptions()
        self.registry = get_block_registry()
        self.architect = SectionArchitect(
            phase=self.options.phase,
            llm_enabled=self.options.architect_llm_enabled,
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def compile_page(
        self,
        *,
        book_id: str,
        chapter: Chapter,
        page: Page,
        stream: BookStream,
        knowledge_bases: list[str] | None = None,
        language: str = "en",
        depth: str | None = None,
        exploration: ExplorationReport | None = None,
    ) -> Page:
        """Plan (if needed) and generate every block on *page*."""
        await stream.book_event(
            "page_compile_started",
            {"page_id": page.id, "chapter_id": chapter.id, "title": page.title},
            stage=STAGE_COMPILATION,
        )

        # Lazy-load the exploration report from disk if the caller didn't pass
        # one in. This keeps the compiler usable from background workers.
        if exploration is None:
            try:
                exploration = self.storage.load_exploration(book_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"load_exploration({book_id}) skipped: {exc}")

        await self._plan_if_needed(
            book_id,
            chapter,
            page,
            stream,
            language=language,
            depth=depth,
            exploration=exploration,
        )

        page.status = PageStatus.GENERATING
        page.updated_at = time.time()
        self.storage.save_page(page)

        ctx_factory = lambda block: BlockContext(  # noqa: E731
            book_id=book_id,
            chapter=chapter,
            page=page,
            block=block,
            language=language,
            knowledge_bases=knowledge_bases or [],
            rag_enabled=self.options.rag_enabled,
            exploration=exploration,
        )

        sem = asyncio.Semaphore(max(1, self.options.block_concurrency))

        async def _run(block: Block, prev: Block | None) -> None:
            async with sem:
                await self._generate_block(
                    book_id,
                    page,
                    block,
                    ctx_factory(block),
                    stream,
                    chapter=chapter,
                    language=language,
                    previous_block=prev,
                )

        # Sequential keeps streaming order; concurrent if requested.
        if self.options.block_concurrency <= 1:
            prev: Block | None = None
            for block in page.blocks:
                if block.status == BlockStatus.READY:
                    prev = block
                    continue
                await _run(block, prev)
                prev = block
        else:
            # Concurrent path uses planning order to derive prev pointers.
            pending: list[tuple[Block, Block | None]] = []
            prev = None
            for block in page.blocks:
                if block.status != BlockStatus.READY:
                    pending.append((block, prev))
                prev = block
            await asyncio.gather(*(_run(b, p) for b, p in pending))

        self._finalize_page_status(page)
        page.updated_at = time.time()
        self.storage.save_page(page)
        self.storage.append_log(
            book_id,
            f"page {page.id} → {page.status.value} "
            f"({sum(1 for b in page.blocks if b.status == BlockStatus.READY)}/{len(page.blocks)} blocks ready)",
            op="compile_page",
        )

        await stream.book_event(
            "page_compiled",
            {
                "page_id": page.id,
                "chapter_id": chapter.id,
                "status": page.status.value,
                "blocks": [
                    {"id": b.id, "type": b.type.value, "status": b.status.value}
                    for b in page.blocks
                ],
            },
            stage=STAGE_COMPILATION,
        )
        return page

    # ── Block-level helpers ──────────────────────────────────────────────

    async def _generate_block(
        self,
        book_id: str,
        page: Page,
        block: Block,
        ctx: BlockContext,
        stream: BookStream,
        *,
        chapter: Chapter,
        language: str,
        previous_block: Block | None,
    ) -> None:
        await stream.book_event(
            "block_started",
            {
                "page_id": page.id,
                "block_id": block.id,
                "block_type": block.type.value,
            },
            stage=STAGE_BLOCK,
        )

        generator = self.registry.get(block.type)
        if generator is None:
            block.status = BlockStatus.ERROR
            block.error = f"No generator registered for block type {block.type.value}"
            logger.warning(block.error)
        else:
            await self._generate_with_retry(generator, ctx, block)

        if block.status == BlockStatus.READY:
            await self._attach_bridge_text(
                block, chapter=chapter, previous_block=previous_block, language=language
            )

        block.updated_at = time.time()

        if self.options.persist_after_each_block:
            self.storage.save_page(page)

        kind = "block_ready" if block.status == BlockStatus.READY else "block_error"
        await stream.book_event(
            kind,
            {
                "page_id": page.id,
                "block_id": block.id,
                "block_type": block.type.value,
                "status": block.status.value,
                "error": block.error,
                "failure": block.metadata.get("failure") if block.metadata else None,
                "payload_keys": list(block.payload.keys()),
            },
            stage=STAGE_BLOCK,
        )

    async def _generate_with_retry(self, generator, ctx: BlockContext, block: Block) -> None:
        """Run *generator*, retrying once (backed off) on a retryable failure.

        ``BlockGenerator.generate`` never raises — it records the outcome on the
        block, tagging failures with a ``kind`` and a ``retryable`` flag. This
        is the only place that acts on that flag; without it the classification
        was computed and then thrown away.
        """
        attempts = max(0, self.options.block_retry_attempts) + 1
        for attempt in range(attempts):
            t0 = time.time()
            await generator.generate(ctx)
            block.metadata.setdefault("generation_ms", int((time.time() - t0) * 1000))

            if block.status != BlockStatus.ERROR:
                return
            failure = (block.metadata or {}).get("failure") or {}
            if not failure.get("retryable") or attempt == attempts - 1:
                return

            delay = self.options.block_retry_backoff_seconds * (2**attempt)
            logger.info(
                f"block {block.id} ({block.type.value}) failed with "
                f"{failure.get('kind')}; retrying in {delay:.1f}s"
            )
            await asyncio.sleep(delay)
            block.metadata["retry_attempts"] = attempt + 1

    # ── Bridge text attachment ─────────────────────────────────────────

    async def attach_bridge_text(
        self,
        block: Block,
        *,
        chapter: Chapter,
        previous_block: Block | None,
        language: str,
    ) -> None:
        """If the block carries a ``transition_in`` hint, generate a short
        plain-text bridge paragraph and store it on the block's payload as
        ``bridge_text``. The hint stays on ``metadata`` so the bridge can be
        regenerated when the target block is replaced or refreshed.
        """
        hint = str((block.metadata or {}).get("transition_in") or "").strip()
        if not hint or previous_block is None:
            block.payload.pop("bridge_text", None)
            return

        previous_summary = f"{previous_block.type.value} block on {chapter.title}"
        try:
            text = await generate_bridge_text(
                chapter_title=chapter.title,
                previous_block_summary=previous_summary,
                next_block_hint=hint,
                language=language,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"bridge_text generation failed: {exc}")
            text = ""

        if text:
            block.payload["bridge_text"] = text
        else:
            block.payload.pop("bridge_text", None)

    async def _attach_bridge_text(
        self,
        block: Block,
        *,
        chapter: Chapter,
        previous_block: Block | None,
        language: str,
    ) -> None:
        await self.attach_bridge_text(
            block,
            chapter=chapter,
            previous_block=previous_block,
            language=language,
        )

    # ── Planning ─────────────────────────────────────────────────────────

    async def _plan_if_needed(
        self,
        book_id: str,
        chapter: Chapter,
        page: Page,
        stream: BookStream,
        *,
        language: str = "en",
        depth: str | None = None,
        exploration: ExplorationReport | None = None,
    ) -> None:
        if page.blocks:
            return
        page.status = PageStatus.PLANNING
        self.storage.save_page(page)
        await stream.book_event(
            "page_planning",
            {"page_id": page.id, "chapter_id": chapter.id, "title": page.title},
            stage=STAGE_PAGE_PLAN,
        )

        planned = await self.architect.plan_blocks_async(
            chapter, exploration=exploration, language=language, depth=depth
        )
        page.blocks = planned
        if not page.content_type:
            page.content_type = chapter.content_type
        if not page.learning_objectives:
            page.learning_objectives = list(chapter.learning_objectives)
        page.updated_at = time.time()
        self.storage.save_page(page)

        await stream.book_event(
            "page_planned",
            {
                "page_id": page.id,
                "chapter_id": chapter.id,
                "block_types": [b.type.value for b in page.blocks],
            },
            stage=STAGE_PAGE_PLAN,
        )

    # ── Status aggregation ─────────────────────────────────────────────

    @staticmethod
    def _finalize_page_status(page: Page) -> None:
        if not page.blocks:
            page.status = PageStatus.ERROR
            page.error = "No blocks were planned for this page."
            return

        ready = sum(1 for b in page.blocks if b.status == BlockStatus.READY)
        errored = sum(1 for b in page.blocks if b.status == BlockStatus.ERROR)
        if ready == len(page.blocks):
            page.status = PageStatus.READY
            page.error = ""
        elif ready == 0:
            page.status = PageStatus.ERROR
            page.error = f"All {errored} blocks failed to generate."
        else:
            page.status = PageStatus.PARTIAL
            page.error = f"{errored}/{len(page.blocks)} blocks failed."


__all__ = ["BookCompiler", "CompilerOptions"]
