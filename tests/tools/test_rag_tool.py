"""Factory + tool-wrapper layer tests (llamaindex-only)."""

from __future__ import annotations

import pytest

from deeptutor.services.rag.factory import (
    DEFAULT_PROVIDER,
    get_pipeline,
    list_pipelines,
    normalize_provider_name,
)
from deeptutor.tools.rag_tool import (
    RAGService,
    get_available_providers,
    get_current_provider,
)


class TestNormalizeProviderName:
    """`normalize_provider_name` is now a stub: every input collapses to llamaindex."""

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "  ",
            "llamaindex",
            "LlamaIndex",
            "raganything",
            "raganything_docling",
            "totally_unknown_xyz",
        ],
    )
    def test_collapses_to_default(self, value) -> None:
        assert normalize_provider_name(value) == DEFAULT_PROVIDER


class TestPipelineFactory:
    def test_list_pipelines_includes_pageindex(self) -> None:
        pipelines = list_pipelines()
        assert isinstance(pipelines, list)
        assert {p["id"] for p in pipelines} == {
            DEFAULT_PROVIDER,
            "pageindex",
            "graphrag",
            "lightrag",
            "lightrag-server",
        }

    def test_get_pipeline_returns_singleton(self) -> None:
        try:
            first = get_pipeline()
            second = get_pipeline()
        except (ValueError, ImportError) as exc:
            pytest.skip(f"LlamaIndex optional dependency missing: {exc}")
        assert first is second

    def test_get_pipeline_collapses_unknown_to_default_singleton(self) -> None:
        """Unknown / legacy provider names resolve to the default pipeline."""
        try:
            a = get_pipeline("llamaindex")
            b = get_pipeline("raganything")  # legacy string → default
            c = get_pipeline("nonexistent_xyz")
        except (ValueError, ImportError) as exc:
            pytest.skip(f"LlamaIndex optional dependency missing: {exc}")
        assert a is b is c

    def test_get_pipeline_dispatches_known_provider(self) -> None:
        """A real provider name builds its own pipeline (not the default)."""
        pipe = get_pipeline("lightrag", kb_base_dir="/tmp/kb-test")
        assert type(pipe).__name__ == "LightRagPipeline"


class TestRAGServiceClassHelpers:
    def test_list_providers_includes_pageindex(self) -> None:
        providers = RAGService.list_providers()
        assert {p["id"] for p in providers} == {
            DEFAULT_PROVIDER,
            "pageindex",
            "graphrag",
            "lightrag",
            "lightrag-server",
        }

    def test_has_provider_default_true(self) -> None:
        assert RAGService.has_provider(DEFAULT_PROVIDER) is True

    def test_has_provider_unknown_false(self) -> None:
        assert RAGService.has_provider("nonexistent") is False
        assert RAGService.has_provider("") is False

    def test_get_current_provider_collapses_unknown_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RAG_PROVIDER", "raganything")  # unknown → default
        assert get_current_provider() == DEFAULT_PROVIDER
        monkeypatch.delenv("RAG_PROVIDER", raising=False)
        assert get_current_provider() == DEFAULT_PROVIDER


class TestToolLayerExports:
    def test_get_available_providers_matches_class_method(self) -> None:
        assert get_available_providers() == RAGService.list_providers()

    def test_rag_search_requires_kb_name(self) -> None:
        import asyncio

        from deeptutor.tools.rag_tool import rag_search

        with pytest.raises(ValueError, match="kb_name"):
            asyncio.run(rag_search(query="hi", kb_name=""))

    def test_rag_search_requires_query(self) -> None:
        import asyncio

        from deeptutor.tools.rag_tool import rag_search

        with pytest.raises(ValueError, match="non-empty"):
            asyncio.run(rag_search(query="", kb_name="any"))
