"""Tests for template-based search answer consolidation."""

from __future__ import annotations

import pytest

from deeptutor.services.search.consolidation import AnswerConsolidator
from deeptutor.services.search.types import SearchResult, WebSearchResponse


@pytest.mark.parametrize("provider", ["serper", "jina", "serper_scholar"])
def test_provider_templates_handle_empty_results(provider: str) -> None:
    response = WebSearchResponse(query="what changed", answer="", provider=provider)

    answer = AnswerConsolidator().consolidate(response).answer

    assert "No results found." in answer


@pytest.mark.parametrize("provider", ["serper", "jina", "serper_scholar", "generic"])
def test_templates_never_render_missing_fields_as_none(provider: str) -> None:
    response = WebSearchResponse(
        query=" sparse result ",
        answer="",
        provider=provider,
        search_results=[SearchResult(title=None, url=None, snippet=None)],  # type: ignore[arg-type]
    )

    answer = AnswerConsolidator().consolidate(response).answer

    assert "None" not in answer
    assert "[1]" in answer
    assert "Untitled" in answer
    assert "](#)" in answer
    assert "(No snippet available)" in answer


def test_serper_template_renders_answer_box_and_citation_link() -> None:
    response = WebSearchResponse(
        query="fourier transform",
        answer="",
        provider="serper",
        search_results=[
            SearchResult(
                title="Fourier transform",
                url="https://example.com/fourier?a=1&b=2",
                snippet="Transforms time into frequency.",
            )
        ],
        metadata={
            "answerBox": {
                "answer": "A transform from time to frequency.",
                "title": "Example",
                "link": "https://example.com/fourier",
            }
        },
    )

    answer = AnswerConsolidator().consolidate(response).answer

    assert "### Direct Answer" in answer
    assert "[Example](https://example.com/fourier)" in answer
    assert "[1] [Fourier transform](https://example.com/fourier?a=1&amp;b=2)" in answer


def test_jina_template_uses_published_time_and_escapes_content() -> None:
    response = WebSearchResponse(
        query="jina reader",
        answer="",
        provider="jina",
        search_results=[
            SearchResult(
                title="Jina Reader",
                url="https://example.com/jina",
                snippet="Retrieval-friendly pages.",
                content="Safe <em>preview</em>",
                attributes={"publishedTime": "2026-08-01"},
            )
        ],
    )

    answer = AnswerConsolidator().consolidate(response).answer

    assert "2026-08-01" in answer
    assert "Safe &lt;em&gt;preview&lt;/em&gt;" in answer
    assert "[1] [Jina Reader](https://example.com/jina)" in answer
