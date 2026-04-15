"""Tests for web search tool types, provider registry, and validation."""

from __future__ import annotations

import pytest

from deeptutor.services.search.types import Citation, SearchResult, WebSearchResponse
from deeptutor.services.search.providers import (
    _DEPRECATED_UNSUPPORTED,
    get_provider,
    list_providers,
    get_providers_info,
)
from deeptutor.services.search import _assert_provider_supported


# ---------------------------------------------------------------------------
# Type dataclasses
# ---------------------------------------------------------------------------


class TestCitation:
    def test_defaults(self) -> None:
        c = Citation(id=1, reference="[1]", url="https://example.com")
        assert c.title == ""
        assert c.type == "web"
        assert c.content == ""

    def test_full_construction(self) -> None:
        c = Citation(
            id=2,
            reference="[2]",
            url="https://example.com",
            title="Example",
            snippet="A snippet",
            source="brave",
        )
        assert c.id == 2
        assert c.source == "brave"


class TestSearchResult:
    def test_defaults(self) -> None:
        r = SearchResult(title="T", url="https://u.com", snippet="S")
        assert r.score == 0.0
        assert r.sitelinks == []
        assert r.attributes == {}

    def test_mutable_defaults_independent(self) -> None:
        r1 = SearchResult(title="A", url="u", snippet="s")
        r2 = SearchResult(title="B", url="u", snippet="s")
        r1.sitelinks.append({"title": "x", "url": "y"})
        assert r2.sitelinks == []


class TestWebSearchResponse:
    def test_to_dict_contains_all_fields(self) -> None:
        citation = Citation(id=1, reference="[1]", url="https://a.com", title="A")
        result = SearchResult(title="R", url="https://r.com", snippet="snippet")
        resp = WebSearchResponse(
            query="test",
            answer="Answer text",
            provider="brave",
            citations=[citation],
            search_results=[result],
        )
        d = resp.to_dict()
        assert d["query"] == "test"
        assert d["answer"] == "Answer text"
        assert d["provider"] == "brave"
        assert len(d["citations"]) == 1
        assert d["citations"][0]["url"] == "https://a.com"
        assert len(d["search_results"]) == 1
        assert d["response"]["content"] == "Answer text"

    def test_to_dict_extra_metadata(self) -> None:
        resp = WebSearchResponse(
            query="q",
            answer="a",
            provider="p",
            metadata={"custom_key": "custom_value", "finish_reason": "stop"},
        )
        d = resp.to_dict()
        assert d["custom_key"] == "custom_value"
        assert "finish_reason" not in d  # handled inside response sub-dict


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def test_list_providers_returns_sorted_names(self) -> None:
        providers = list_providers()
        assert isinstance(providers, list)
        assert providers == sorted(providers)
        assert "duckduckgo" in providers

    def test_get_provider_raises_on_unknown(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("nonexistent_provider_xyz")

    def test_get_provider_raises_on_deprecated(self) -> None:
        for name in _DEPRECATED_UNSUPPORTED:
            with pytest.raises(ValueError, match="Unsupported"):
                get_provider(name)

    def test_get_providers_info_contains_supported_and_deprecated(self) -> None:
        info = get_providers_info()
        statuses = {item["status"] for item in info}
        assert "supported" in statuses
        assert "deprecated" in statuses
        ids = {item["id"] for item in info}
        assert "duckduckgo" in ids

    def test_duckduckgo_no_api_key_required(self) -> None:
        provider = get_provider("duckduckgo")
        assert provider.requires_api_key is False


# ---------------------------------------------------------------------------
# _assert_provider_supported
# ---------------------------------------------------------------------------


class TestAssertProviderSupported:
    def test_supported_provider_does_not_raise(self) -> None:
        _assert_provider_supported("duckduckgo")

    def test_deprecated_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="deprecated"):
            _assert_provider_supported("exa")

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown search provider"):
            _assert_provider_supported("totally_fake")
