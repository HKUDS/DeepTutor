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


def _pipeline(responses: list[str]) -> MagicMock:
    pipeline = MagicMock()
    pipeline.run_analysis = AsyncMock(
        return_value=VisualizationAnalysis(
            render_type="html",
            description="An interactive mechanics diagram.",
            chart_type="interactive",
        )
    )
    pipeline.run_code_generation = AsyncMock(side_effect=responses)
    pipeline.code_agent.binding = "deepseek"
    pipeline.code_agent.get_model.return_value = "deepseek-flash"
    pipeline.code_agent.get_max_tokens.return_value = 16000
    return pipeline


async def _run(pipeline: MagicMock, monkeypatch: pytest.MonkeyPatch) -> Block:
    from deeptutor.agents.visualize import pipeline as pipeline_module
    from deeptutor.services.llm import config as config_module

    monkeypatch.setattr(pipeline_module, "VisualizePipeline", MagicMock(return_value=pipeline))
    monkeypatch.setattr(
        config_module,
        "get_llm_config",
        lambda: SimpleNamespace(api_key="test", base_url="", api_version=""),
    )
    return await InteractiveGenerator().generate(_context())


async def _generate(response: str, monkeypatch: pytest.MonkeyPatch) -> Block:
    # The same reply on every attempt, so a retry cannot rescue a bad page.
    return await _run(_pipeline([response, response]), monkeypatch)


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


def _efforts(pipeline: MagicMock) -> list[object]:
    return [
        call.kwargs.get("reasoning_effort") for call in pipeline.run_code_generation.await_args_list
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first",
    ["", f"```html\n{_HTML[: _HTML.index('</script>')]}"],
    ids=["empty", "cut-off"],
)
async def test_a_page_that_ran_out_of_room_is_retried_with_thinking_off(
    first: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A reasoning model can spend the whole output budget thinking and return
    # nothing, or stop halfway; asking again with thinking off frees the room.
    pipeline = _pipeline([first, _HTML])
    result = await _run(pipeline, monkeypatch)

    assert result.status == BlockStatus.READY
    assert result.payload["code"]["content"] == _HTML
    assert _efforts(pipeline) == [None, "none"]


@pytest.mark.asyncio
async def test_a_page_still_out_of_room_after_the_retry_says_what_to_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _pipeline(["", ""])
    result = await _run(pipeline, monkeypatch)

    assert result.status == BlockStatus.ERROR
    assert "returned no code" in result.error
    assert "16000-token" in result.error
    assert "Settings → Capabilities → Visualize" in result.error
    assert "Reasoning effort → None" not in result.error
    assert _efforts(pipeline) == [None, "none"]


@pytest.mark.asyncio
async def test_a_malformed_page_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unpaired script tags are a model mistake, not a budget problem.
    pipeline = _pipeline([_HTML.replace("</body>", "</script></body>"), _HTML])
    result = await _run(pipeline, monkeypatch)

    assert result.status == BlockStatus.ERROR
    assert "unpaired <script>" in result.error
    assert "Max tokens" not in result.error
    assert _efforts(pipeline) == [None]
