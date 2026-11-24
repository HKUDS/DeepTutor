"""Book interactive HTML must be complete before it becomes reader content."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.agents.visualize.models import VisualizationAnalysis
from deeptutor.book.blocks.base import BlockContext
from deeptutor.book.blocks.interactive import InteractiveGenerator
from deeptutor.book.models import Block, BlockStatus, BlockType, Chapter, Page

_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Interactive</title></head>
<body>
<div id="app"></div>
<script>
  document.getElementById("app").textContent = "Ready";
</script>
</body>
</html>"""


def _context() -> BlockContext:
    chapter = Chapter(id="ch-interactive", title="Mechanics", summary="Stress and strain")
    block = Block(type=BlockType.INTERACTIVE)
    return BlockContext(
        book_id="book-interactive",
        chapter=chapter,
        page=Page(
            id="page-interactive",
            book_id="book-interactive",
            chapter_id=chapter.id,
        ),
        block=block,
        rag_enabled=False,
    )


async def _generate(response: str, monkeypatch: pytest.MonkeyPatch) -> Block:
    from deeptutor.agents.visualize import pipeline as pipeline_module
    from deeptutor.services.llm import config as config_module

    pipeline = MagicMock()
    pipeline.run_analysis = AsyncMock(
        return_value=VisualizationAnalysis(
            render_type="html",
            description="An interactive mechanics diagram.",
            chart_type="interactive",
        )
    )
    pipeline.run_code_generation = AsyncMock(return_value=response)
    monkeypatch.setattr(pipeline_module, "VisualizePipeline", MagicMock(return_value=pipeline))
    monkeypatch.setattr(
        config_module,
        "get_llm_config",
        lambda: SimpleNamespace(api_key="test", base_url="", api_version=""),
    )

    return await InteractiveGenerator().generate(_context())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _HTML,
        f"Here is the interactive page.\n\n```html\n{_HTML}\n```\n",
        f"Here is the interactive page.\n\n{_HTML}\n\nHope this helps.",
        f"```\n{_HTML}\n```",
    ],
    ids=["raw", "fenced", "raw-with-prose", "bare-fence"],
)
async def test_complete_html_is_normalized_and_marked_ready(
    response: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = await _generate(response, monkeypatch)

    assert result.status == BlockStatus.READY
    assert result.payload["code"]["content"] == _HTML
    assert "failure" not in result.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (f"```html\n{_HTML}", "unterminated Markdown fence"),
        (_HTML.replace("</html>", ""), "</html>"),
        (f"```html\n{_HTML.replace('</html>', '')}\n```", "</html>"),
        (_HTML.replace("</script>", ""), "script"),
        (_HTML.replace("</body>", "</script></body>"), "script"),
        (_HTML.replace("<script>", "<script/>").replace("</script>", ""), "script"),
    ],
    ids=[
        "unterminated-fence",
        "missing-html-close",
        "truncated-fenced-document",
        "unclosed-script",
        "extra-script-close",
        "self-closing-script-without-close",
    ],
)
async def test_incomplete_html_is_not_persisted_as_ready(
    response: str, error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = await _generate(response, monkeypatch)

    assert result.status == BlockStatus.ERROR
    assert result.payload == {}
    assert error in result.error
    assert result.metadata["failure"]["retryable"] is True
