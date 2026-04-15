"""Tests for RAG tool wrappers and pipeline factory."""

from __future__ import annotations

import warnings

import pytest

from deeptutor.services.rag.factory import (
    DEFAULT_PROVIDER,
    LEGACY_PROVIDER_ALIASES,
    has_pipeline,
    list_pipelines,
    normalize_provider_name,
    get_pipeline,
)
from deeptutor.tools.rag_tool import (
    RAGService,
    get_available_providers,
    get_current_provider,
)


# ---------------------------------------------------------------------------
# normalize_provider_name
# ---------------------------------------------------------------------------


class TestNormalizeProviderName:
    def test_default_when_none(self) -> None:
        assert normalize_provider_name(None) == DEFAULT_PROVIDER

    def test_default_when_empty(self) -> None:
        assert normalize_provider_name("") == DEFAULT_PROVIDER

    def test_strips_whitespace(self) -> None:
        assert normalize_provider_name("  llamaindex  ") == "llamaindex"

    def test_case_insensitive(self) -> None:
        assert normalize_provider_name("LlamaIndex") == "llamaindex"

    def test_legacy_alias_lightrag(self) -> None:
        assert normalize_provider_name("lightrag") == DEFAULT_PROVIDER

    def test_legacy_alias_raganything(self) -> None:
        assert normalize_provider_name("raganything") == DEFAULT_PROVIDER

    def test_unknown_passes_through(self) -> None:
        assert normalize_provider_name("custom_pipeline") == "custom_pipeline"


# ---------------------------------------------------------------------------
# Pipeline registry
# ---------------------------------------------------------------------------


class TestPipelineRegistry:
    def test_has_pipeline_default(self) -> None:
        assert has_pipeline(DEFAULT_PROVIDER) is True

    def test_has_pipeline_unknown(self) -> None:
        assert has_pipeline("nonexistent_xyz") is False

    def test_has_pipeline_empty(self) -> None:
        assert has_pipeline("") is False

    def test_list_pipelines_returns_default(self) -> None:
        pipelines = list_pipelines()
        assert isinstance(pipelines, list)
        assert len(pipelines) >= 1
        ids = {p["id"] for p in pipelines}
        assert DEFAULT_PROVIDER in ids

    def test_get_pipeline_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown pipeline"):
            get_pipeline("nonexistent_pipeline_xyz")


# ---------------------------------------------------------------------------
# RAGService class methods
# ---------------------------------------------------------------------------


class TestRAGServiceStaticMethods:
    def test_list_providers(self) -> None:
        providers = RAGService.list_providers()
        assert isinstance(providers, list)
        assert any(p["id"] == DEFAULT_PROVIDER for p in providers)

    def test_has_provider_default(self) -> None:
        assert RAGService.has_provider(DEFAULT_PROVIDER) is True

    def test_has_provider_unknown(self) -> None:
        assert RAGService.has_provider("nonexistent") is False

    def test_get_current_provider_returns_string(self) -> None:
        provider = get_current_provider()
        assert isinstance(provider, str)
        assert len(provider) > 0


# ---------------------------------------------------------------------------
# tool-level wrappers
# ---------------------------------------------------------------------------


class TestToolWrappers:
    def test_get_available_providers(self) -> None:
        providers = get_available_providers()
        assert isinstance(providers, list)


# ---------------------------------------------------------------------------
# Deprecated API surface
# ---------------------------------------------------------------------------


class TestDeprecatedAPI:
    def test_get_plugin_warns(self) -> None:
        from deeptutor.services.rag.factory import get_plugin

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            with pytest.raises(DeprecationWarning):
                get_plugin(DEFAULT_PROVIDER)

    def test_list_plugins_warns(self) -> None:
        from deeptutor.services.rag.factory import list_plugins

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            with pytest.raises(DeprecationWarning):
                list_plugins()

    def test_has_plugin_warns(self) -> None:
        from deeptutor.services.rag.factory import has_plugin

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            with pytest.raises(DeprecationWarning):
                has_plugin(DEFAULT_PROVIDER)
