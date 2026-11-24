"""Interactive block – self-contained interactive HTML widget.

Wraps :class:`deeptutor.agents.visualize.pipeline.VisualizePipeline` with
``render_mode="html"``. The payload carries an HTML document the frontend
renders in an isolated iframe.

The draft is normalized to a complete HTML document and checked by the
deterministic local ``validate_visualization``. HTML has no repair pass (full
single-file documents are too large for a useful targeted fix), so an
unrenderable document raises ``GenerationFailure`` and lets the book engine
retry — better than baking a placeholder page into the book.
"""

from __future__ import annotations

from html.parser import HTMLParser
import logging
import re
from typing import Any

from deeptutor.services.keypool import primary_api_key

from ..models import BlockType, SourceAnchor
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure

logger = logging.getLogger(__name__)

_HTML_START = re.compile(r"<!doctype\s+html\b|<html\b", re.IGNORECASE)
_HTML_END = re.compile(r"</html\s*>", re.IGNORECASE)
_FENCE_OPEN = re.compile(r"^[ \t]*```(?:html)?[ \t]*\r?\n", re.IGNORECASE | re.MULTILINE)
_FENCE_CLOSE = re.compile(r"^[ \t]*```[ \t]*(?:\r?\n|$)", re.MULTILINE)


class _ScriptBalanceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.open_scripts = 0
        self.extra_closes = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.open_scripts += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag != "script":
            return
        if self.open_scripts:
            self.open_scripts -= 1
        else:
            self.extra_closes += 1


def _normalize_interactive_html(code: str) -> str:
    text = (code or "").strip()
    start = _HTML_START.search(text)
    if start is None:
        raise GenerationFailure(
            "interactive html is missing a document start (<!DOCTYPE html> or <html>)."
        )

    candidate = text
    fence_open = _FENCE_OPEN.search(text[: start.start()])
    if fence_open is not None:
        fence_close = _FENCE_CLOSE.search(text, fence_open.end())
        if fence_close is None:
            raise GenerationFailure("interactive html has an unterminated Markdown fence.")
        candidate = text[fence_open.end() : fence_close.start()]

    start = _HTML_START.search(candidate)
    ends = list(_HTML_END.finditer(candidate, start.end())) if start is not None else []
    if start is None or not ends:
        raise GenerationFailure("interactive html is missing a complete </html> boundary.")
    document = candidate[start.start() : ends[-1].end()].strip()

    parser = _ScriptBalanceParser()
    parser.feed(document)
    parser.close()
    if parser.open_scripts or parser.extra_closes:
        raise GenerationFailure("interactive html contains unpaired <script> tags.")

    return document


class InteractiveGenerator(BlockGenerator):
    block_type = BlockType.INTERACTIVE

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        focus = str(params.get("focus") or "")
        interaction = str(params.get("interaction") or "interactive")
        prompts = load_book_prompts("interactive", ctx.language)

        history_lines: list[str] = []
        if chapter_summary:
            history_lines.append(
                get_book_prompt(prompts, "context_summary")
                .strip()
                .format(chapter_summary=chapter_summary)
            )
        if objectives:
            history_lines.append(get_book_prompt(prompts, "context_objectives").strip())
            for obj in objectives:
                history_lines.append(f"- {obj}")
        history_context = "\n".join(history_lines)

        focus_clause = (
            get_book_prompt(prompts, "focus_clause").rstrip().format(focus=focus) if focus else ""
        )
        user_input = (
            get_book_prompt(prompts, "brief")
            .strip()
            .format(
                interaction=interaction,
                chapter_title=chapter_title,
                focus_clause=focus_clause,
            )
        )

        try:
            from deeptutor.agents.visualize.pipeline import VisualizePipeline
            from deeptutor.agents.visualize.utils import validate_visualization
            from deeptutor.services.llm.config import get_llm_config

            llm_config = get_llm_config()
            pipeline = VisualizePipeline(
                api_key=primary_api_key(llm_config.api_key),
                base_url=llm_config.base_url,
                api_version=llm_config.api_version,
                language=ctx.language,
            )
            analysis = await pipeline.run_analysis(
                user_input=user_input,
                history_context=history_context,
                render_mode="html",
            )
            code = await pipeline.run_code_generation(
                user_input=user_input,
                history_context=history_context,
                analysis=analysis,
            )
        except Exception as exc:
            logger.warning(f"InteractiveGenerator failed: {exc}", exc_info=True)
            raise GenerationFailure(f"interactive generation failed: {exc}") from exc

        code = _normalize_interactive_html(code)
        ok, validation_error = validate_visualization(code, "html")
        if not ok:
            raise GenerationFailure(f"interactive html failed validation: {validation_error}")

        return (
            {
                "render_type": "html",
                "code": {"language": "html", "content": code},
                "description": analysis.description,
                "chart_type": analysis.chart_type,
            },
            [],
            {
                "review_changed": False,
                "review_notes": "Passed local validation.",
            },
        )


__all__ = ["InteractiveGenerator"]
