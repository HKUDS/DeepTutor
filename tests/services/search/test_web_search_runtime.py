"""Tests for TutorBot-style web_search runtime behavior."""

from __future__ import annotations

import pytest

from deeptutor.services.config.provider_runtime import ResolvedSearchConfig
from deeptutor.services.search import web_search
from deeptutor.services.search.types import WebSearchResponse


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


def _patch_runtime(monkeypatch, resolved: ResolvedSearchConfig, **kwargs) -> None:
    """Pin the resolved config and keep the fallback chain off the real catalog."""
    monkeypatch.setattr(
        "deeptutor.services.search._get_web_search_config",
        lambda: {"enabled": True},
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
