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


async def _generate(
    response: str, monkeypatch: pytest.MonkeyPatch, *, max_tokens: int = 32768
) -> Block:
    from deeptutor.agents.visualize import pipeline as pipeline_module
    from deeptutor.services.config import capabilities_settings
    from deeptutor.services.llm import config as config_module

    monkeypatch.setattr(
        capabilities_settings,
        "get_visualize_params",
        lambda: {"temperature": 0.15, "max_tokens": max_tokens},
    )

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
        f"```html\n{_HTML}",
        f"{_HTML}\n\nNote: the page ends at its closing </html> tag.",
    ],
    ids=[
        "raw",
        "fenced",
        "raw-with-prose",
        "bare-fence",
        "fence-left-open",
        "prose-quotes-end-tag",
    ],
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
        (f"```html\n{_HTML[: _HTML.index('</script>')]}", "cut off"),
        (_HTML.replace("</html>", ""), "cut off"),
        (f"```html\n{_HTML.replace('</html>', '')}\n```", "cut off"),
        (_HTML.replace("</script>", ""), "script"),
        (_HTML.replace("</body>", "</script></body>"), "script"),
        (_HTML.replace("<script>", "<script/>").replace("</script>", ""), "script"),
    ],
    ids=[
        "truncated-inside-script",
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    ["", "   \n", f"```html\n{_HTML[: _HTML.index('</script>')]}", _HTML.replace("</html>", "")],
    ids=["empty", "whitespace", "truncated-inside-script", "missing-html-close"],
)
async def test_output_budget_failures_tell_the_user_what_to_change(
    response: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A reasoning model can spend the whole visualize budget on thinking and
    # return nothing, or run out halfway through the page. Both are fixed by
    # the same two settings, so the error has to name them.
    result = await _generate(response, monkeypatch, max_tokens=12345)

    assert result.status == BlockStatus.ERROR
    assert "12345" in result.error
    assert "Settings → Capabilities → Visualize" in result.error
    assert "thinking" in result.error
    assert result.metadata["failure"]["retryable"] is True


@pytest.mark.asyncio
async def test_empty_output_is_not_reported_as_a_missing_document_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _generate("", monkeypatch)

    assert "returned no code" in result.error
    assert "document start" not in result.error


@pytest.mark.asyncio
async def test_unpaired_scripts_do_not_blame_the_output_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _generate(_HTML.replace("</script>", ""), monkeypatch)

    assert result.status == BlockStatus.ERROR
    assert "Settings → Capabilities → Visualize" not in result.error


@pytest.mark.asyncio
async def test_fences_and_end_tags_inside_the_document_are_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A code sample in <pre> and an end tag inside a script string belong to
    # the page; neither may cut the document short.
    html = _HTML.replace(
        '<div id="app"></div>',
        '<div id="app"></div>\n<pre>\n```python\nprint(1)\n```\n</pre>',
    ).replace('"Ready"', '"</html> is only text here"')
    result = await _generate(f"Here it is.\n\n```html\n{html}\n```\n", monkeypatch)

    assert result.status == BlockStatus.READY
    assert result.payload["code"]["content"] == html
