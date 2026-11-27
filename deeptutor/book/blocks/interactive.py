"""Interactive block – self-contained interactive HTML widget.

Wraps :class:`deeptutor.agents.visualize.pipeline.VisualizePipeline` with
``render_mode="html"``. The payload carries an HTML document the frontend
renders in an isolated iframe.

The draft is normalized to a complete HTML document and checked by the
deterministic local ``validate_visualization``. HTML has no repair pass (full
single-file documents are too large for a useful targeted fix), so an
unrenderable document raises ``GenerationFailure`` and lets the book engine
retry — better than baking a placeholder page into the book.

The one exception is a page that ran out of room — empty, or cut off before
``</html>``. A reasoning model can spend the whole output budget thinking, so
that page is asked for once more with thinking turned off before failing.
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


class _DocumentParser(HTMLParser):
    """Find where the document really ends and check its scripts pair up.

    The parser treats script bodies as raw text, so an ``</html>`` inside a
    script string, a code fence in ``<pre>`` or prose after the page cannot
    move the end of the document.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.end: tuple[int, int] | None = None
        self.open_scripts = 0
        self.extra_closes = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and self.end is None:
            self.open_scripts += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self.end is not None:
            return
        if tag == "html":
            self.end = self.getpos()
        elif tag == "script":
            if self.open_scripts:
                self.open_scripts -= 1
            else:
                self.extra_closes += 1


def _offset(text: str, position: tuple[int, int]) -> int:
    line, column = position
    offset = 0
    for _ in range(line - 1):
        offset = text.index("\n", offset) + 1
    return offset + column


class _OutOfRoom(GenerationFailure):
    """The model returned no page, or stopped before the page was finished.

    Both happen when a reasoning model spends the output budget on hidden
    thinking, so they are worth one more attempt with thinking turned off.
    """


def _budget_hint(max_tokens: int | None) -> str:
    budget = f"its {max_tokens}-token" if max_tokens else "its"
    return (
        f" It was retried with thinking turned off and still ran out of {budget} "
        "output budget: raise Max tokens in Settings → Capabilities → Visualize, "
        "or turn off thinking or lower the reasoning effort for this model in Settings."
    )


def _normalize_interactive_html(code: str) -> str:
    text = (code or "").strip()
    if not text:
        raise _OutOfRoom("interactive generation returned no code.")
    start = _HTML_START.search(text)
    if start is None:
        raise GenerationFailure(
            "interactive html is missing a document start (<!DOCTYPE html> or <html>)."
        )
    text = text[start.start() :]

    parser = _DocumentParser()
    parser.feed(text)
    parser.close()
    if parser.end is None:
        if parser.open_scripts and _HTML_END.search(text) is not None:
            raise GenerationFailure("interactive html contains unpaired <script> tags.")
        where = "inside a <script>" if parser.open_scripts else "before its closing </html>"
        raise _OutOfRoom(
            f"interactive html is incomplete: it stops {where} "
            "(the model output was probably cut off)."
        )
    if parser.open_scripts or parser.extra_closes:
        raise GenerationFailure("interactive html contains unpaired <script> tags.")

    end = _HTML_END.match(text, _offset(text, parser.end))
    if end is None:  # pragma: no cover - the parser only reports real end tags
        raise GenerationFailure("interactive html has an unreadable </html> tag.")
    return text[: end.end()]


def _max_tokens(agent: Any) -> int | None:
    """The budget the code-generation call was sent with, for the error text."""
    try:
        return int(agent.get_output_budget())
    except Exception:  # pragma: no cover - only used to word an error
        logger.debug("Could not read the visualize budget", exc_info=True)
        return None


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
            from deeptutor.services.llm.reasoning_params import thinking_off_effort_for

            analysis = await pipeline.run_analysis(
                user_input=user_input,
                history_context=history_context,
                render_mode="html",
            )
        except Exception as exc:
            logger.warning(f"InteractiveGenerator failed: {exc}", exc_info=True)
            raise GenerationFailure(f"interactive generation failed: {exc}") from exc

        async def write_page(reasoning_effort: str | None) -> str:
            try:
                return await pipeline.run_code_generation(
                    user_input=user_input,
                    history_context=history_context,
                    analysis=analysis,
                    reasoning_effort=reasoning_effort,
                )
            except Exception as exc:
                logger.warning(f"InteractiveGenerator failed: {exc}", exc_info=True)
                raise GenerationFailure(f"interactive generation failed: {exc}") from exc

        agent = pipeline.code_agent
        try:
            code = _normalize_interactive_html(await write_page(None))
        except _OutOfRoom as first:
            logger.info(f"Interactive page ran out of room ({first}); retrying with thinking off")
            effort = thinking_off_effort_for(agent.binding, agent.get_model())
            try:
                code = _normalize_interactive_html(await write_page(effort))
            except _OutOfRoom as exc:
                raise GenerationFailure(str(exc) + _budget_hint(_max_tokens(agent))) from exc

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
