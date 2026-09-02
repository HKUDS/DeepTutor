"""Tests for TutorBot-style web_search runtime behavior."""

from __future__ import annotations

import pytest

from deeptutor.services.config.provider_runtime import ResolvedSearchConfig
from deeptutor.services.search import web_search
from deeptutor.services.search.source_filter import filter_web_search_response
from deeptutor.services.search.types import Citation, SearchResult, WebSearchResponse


class _FakeProvider:
    def __init__(self, name: str, supports_answer: bool = False):
        self.name = name
        self.supports_answer = supports_answer

    def search(self, query: str, **kwargs):
        return WebSearchResponse(
            query=query,
            answer="",
            provider=self.name,
            citations=[],
            search_results=[],
        )


class _FailingProvider(_FakeProvider):
    def search(self, query: str, **kwargs):
        raise RuntimeError("202 Ratelimit")


def _patch_runtime(
    monkeypatch, resolved: ResolvedSearchConfig, *, config: dict | None = None, **kwargs
) -> None:
    """Pin the resolved config and keep the fallback chain off the real catalog."""
    monkeypatch.setattr(
        "deeptutor.services.search._get_web_search_config",
        lambda: {"enabled": True, **(config or {})},
    )
    monkeypatch.setattr(
        "deeptutor.services.search.load_system_settings",
        lambda: {"web_search_source_filtering": (config or {}).get("source_filtering", {})},
    )
    monkeypatch.setattr(
        "deeptutor.services.search.resolve_search_runtime_config",
        lambda: resolved,
    )
    monkeypatch.setattr(
        "deeptutor.services.search.search_fallback_candidates",
        lambda _provider: list(kwargs.get("candidates", [])),
    )
    monkeypatch.setattr(
        "deeptutor.services.search.search_provider_credentials",
        lambda provider: kwargs.get("credentials", {}).get(provider, ("", "")),
    )


def test_web_search_rejects_deprecated_provider(monkeypatch) -> None:
    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="exa",
            requested_provider="exa",
            unsupported_provider=True,
            deprecated_provider=True,
        ),
    )
    with pytest.raises(ValueError):
        web_search("hello")


def test_web_search_none_provider_returns_actionable_configuration_error(monkeypatch) -> None:
    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="none",
            requested_provider="none",
            max_results=5,
        ),
    )

    result = web_search("hello")

    assert result["provider"] == "none"
    assert result["error_code"] == "search_provider_not_configured"
    assert "Settings" in result["answer"]
    assert "DuckDuckGo" in result["answer"]


def test_web_search_perplexity_missing_key_hard_fails(monkeypatch) -> None:
    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="perplexity",
            requested_provider="perplexity",
            api_key="",
            max_results=5,
            missing_credentials=True,
        ),
    )
    with pytest.raises(ValueError, match="perplexity requires api_key"):
        web_search("hello")


def test_web_search_missing_key_falls_back_to_duckduckgo(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_get_provider(name: str, **kwargs):
        captured["provider"] = name
        captured["kwargs"] = kwargs
        return _FakeProvider(name)

    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="brave",
            requested_provider="brave",
            api_key="",
            base_url="",
            max_results=3,
            proxy="http://127.0.0.1:7890",
        ),
    )
    monkeypatch.setattr("deeptutor.services.search.get_provider", _fake_get_provider)
    result = web_search("hello")
    assert captured["provider"] == "duckduckgo"
    assert result["provider"] == "duckduckgo"
    kwargs = captured["kwargs"]
    assert kwargs["proxy"] == "http://127.0.0.1:7890"
    assert kwargs["max_results"] == 3


def test_web_search_searxng_uses_base_url(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_get_provider(name: str, **kwargs):
        captured["provider"] = name
        captured["kwargs"] = kwargs
        return _FakeProvider(name)

    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="searxng",
            requested_provider="searxng",
            base_url="https://searx.example.com",
            max_results=4,
        ),
    )
    monkeypatch.setattr("deeptutor.services.search.get_provider", _fake_get_provider)
    result = web_search("hello")
    assert captured["provider"] == "searxng"
    assert captured["kwargs"]["base_url"] == "https://searx.example.com"
    assert captured["kwargs"]["max_results"] == 4
    assert result["provider"] == "searxng"


def test_web_search_runtime_failure_falls_through_the_chain(monkeypatch) -> None:
    seen: list[tuple[str, dict]] = []

    def _fake_get_provider(name: str, **kwargs):
        seen.append((name, kwargs))
        return _FailingProvider(name) if name == "serper" else _FakeProvider(name)

    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="serper",
            requested_provider="serper",
            api_key="serper-key",
            max_results=5,
        ),
        candidates=["tavily", "duckduckgo"],
        credentials={"tavily": ("tavily-key", "")},
    )
    monkeypatch.setattr("deeptutor.services.search.get_provider", _fake_get_provider)
    result = web_search("hello")

    assert [name for name, _ in seen] == ["serper", "tavily"]
    assert result["provider"] == "tavily"
    fallback = result["search_fallback"]
    assert fallback["requested"] == "serper"
    assert fallback["used"] == "tavily"
    assert "202 Ratelimit" in fallback["failures"][0]
    # The fallback provider runs on its own credentials, never the failed
    # provider's key.
    assert seen[1][1]["api_key"] == "tavily-key"


def test_web_search_fallback_drops_request_credentials_for_previous_provider(monkeypatch) -> None:
    seen: list[tuple[str, dict]] = []

    def _fake_get_provider(name: str, **kwargs):
        seen.append((name, kwargs))
        return _FailingProvider(name) if name == "serper" else _FakeProvider(name)

    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="serper",
            requested_provider="serper",
            api_key="profile-serper-key",
            base_url="https://profile.serper.example",
            max_results=5,
        ),
        candidates=["tavily"],
        credentials={"tavily": ("tavily-key", "https://tavily.example")},
    )
    monkeypatch.setattr("deeptutor.services.search.get_provider", _fake_get_provider)

    result = web_search(
        "hello",
        api_key="request-serper-key",
        base_url="https://request.serper.example",
    )

    assert result["provider"] == "tavily"
    assert seen[0][1]["api_key"] == "request-serper-key"
    assert seen[0][1]["base_url"] == "https://request.serper.example"
    assert seen[1][1]["api_key"] == "tavily-key"
    assert seen[1][1]["base_url"] == "https://tavily.example"


def test_web_search_raises_when_every_candidate_fails(monkeypatch) -> None:
    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="brave",
            requested_provider="brave",
            api_key="brave-key",
            max_results=5,
        ),
        candidates=["duckduckgo"],
    )
    monkeypatch.setattr(
        "deeptutor.services.search.get_provider",
        lambda name, **kwargs: _FailingProvider(name),
    )
    with pytest.raises(Exception, match="brave: 202 Ratelimit; duckduckgo: 202 Ratelimit"):
        web_search("hello")


def test_web_search_explicit_provider_uses_its_own_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_get_provider(name: str, **kwargs):
        captured["provider"] = name
        captured["kwargs"] = kwargs
        return _FakeProvider(name, supports_answer=True)

    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="brave",
            requested_provider="brave",
            api_key="brave-key",
            max_results=5,
        ),
        credentials={"tavily": ("tavily-key", "")},
    )
    monkeypatch.setattr("deeptutor.services.search.get_provider", _fake_get_provider)
    web_search("hello", provider="tavily")
    assert captured["provider"] == "tavily"
    assert captured["kwargs"]["api_key"] == "tavily-key"


def test_source_filter_removes_unsafe_references_and_preserves_ids() -> None:
    response = WebSearchResponse(
        query="safe references",
        answer="",
        provider="test",
        citations=[
            Citation(id=1, reference="[1]", url="javascript:alert(1)"),
            Citation(id=2, reference="[2]", url="https://school.example/a"),
            Citation(id=3, reference="[3]", url="https://user:pw@example.com/a"),
        ],
        search_results=[
            SearchResult(title="Safe", url="https://school.example/a", snippet="ok"),
            SearchResult(title="Internal", url="http://127.0.0.1:8000/admin", snippet="no"),
        ],
    )

    filtered = filter_web_search_response(response)

    assert [citation.id for citation in filtered.citations] == [2]
    assert [citation.reference for citation in filtered.citations] == ["[2]"]
    assert [result.title for result in filtered.search_results] == ["Safe"]
    assert filtered.metadata["source_filter"] == {
        "removed_citations": 2,
        "removed_search_results": 1,
        "rejected_hosts": ["example.com", "127.0.0.1"],
        "answer_invalidated": False,
    }


def test_source_filter_supports_blocked_and_trusted_domain_policies() -> None:
    response = WebSearchResponse(
        query="education",
        answer="",
        provider="test",
        citations=[
            Citation(id=1, reference="[1]", url="https://spam.example/a"),
            Citation(id=2, reference="[2]", url="https://lesson.trusted.edu/a"),
            Citation(id=3, reference="[3]", url="https://other.example/a"),
        ],
        search_results=[],
    )

    filtered = filter_web_search_response(
        response,
        blocked_domains=["spam.example"],
        trusted_domains=["trusted.edu"],
    )

    assert [citation.url for citation in filtered.citations] == ["https://lesson.trusted.edu/a"]
    assert filtered.metadata["source_filter"]["rejected_hosts"] == [
        "spam.example",
        "other.example",
    ]


def test_web_search_filters_provider_results_before_consolidation(monkeypatch) -> None:
    class _UnsafeProvider(_FakeProvider):
        def search(self, query: str, **kwargs):
            return WebSearchResponse(
                query=query,
                answer="",
                provider=self.name,
                citations=[
                    Citation(id=1, reference="[1]", url="https://spam.example/a"),
                    Citation(id=2, reference="[2]", url="https://school.example/a"),
                ],
                search_results=[
                    SearchResult(title="Spam", url="https://spam.example/a", snippet="bad"),
                    SearchResult(title="School", url="https://school.example/a", snippet="good"),
                ],
            )

    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="brave",
            requested_provider="brave",
            api_key="brave-key",
            max_results=5,
        ),
        config={
            "enabled": True,
            "source_filtering": {"blocked_domains": ["spam.example"]},
        },
    )
    monkeypatch.setattr(
        "deeptutor.services.search.get_provider",
        lambda name, **kwargs: _UnsafeProvider(name),
    )

    result = web_search("education")

    assert "spam.example" not in result["answer"]
    assert "**[1] School**" in result["answer"]
    assert [row["url"] for row in result["search_results"]] == ["https://school.example/a"]
    assert result["source_filter"] == {
        "removed_citations": 1,
        "removed_search_results": 1,
        "rejected_hosts": ["spam.example"],
        "answer_invalidated": False,
    }


def test_web_search_filters_answer_provider_citations_without_renumbering(monkeypatch) -> None:
    class _AnswerProvider(_FakeProvider):
        def __init__(self, name: str):
            super().__init__(name, supports_answer=True)

        def search(self, query: str, **kwargs):
            return WebSearchResponse(
                query=query,
                answer="Unsafe claim [1]. Safe lesson [2].",
                provider=self.name,
                citations=[
                    Citation(id=1, reference="[1]", url="https://spam.example/a"),
                    Citation(id=2, reference="[2]", url="https://school.example/a"),
                ],
                search_results=[
                    SearchResult(title="Spam", url="https://spam.example/a", snippet="bad"),
                    SearchResult(
                        title="School",
                        url="https://school.example/a",
                        snippet="safe lesson",
                    ),
                ],
            )

    _patch_runtime(
        monkeypatch,
        ResolvedSearchConfig(
            provider="brave",
            requested_provider="brave",
            api_key="brave-key",
            max_results=5,
        ),
        config={
            "enabled": True,
            "source_filtering": {"blocked_domains": ["spam.example"]},
        },
    )
    monkeypatch.setattr(
        "deeptutor.services.search.get_provider",
        lambda name, **kwargs: _AnswerProvider(name),
    )

    result = web_search("education")

    assert "Unsafe claim" not in result["answer"]
    assert "School" in result["answer"]
    assert [citation["reference"] for citation in result["citations"]] == ["[2]"]
    assert result["source_filter"]["removed_citations"] == 1
    assert result["source_filter"]["answer_invalidated"] is True
