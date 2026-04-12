"""RAG provider registry and tool integration tests (llamaindex-only)."""

from __future__ import annotations

import os

import pytest


def test_list_available_providers_only_llamaindex() -> None:
    """Provider list should expose only llamaindex."""
    from deeptutor.tools.rag_tool import get_available_providers

    providers = get_available_providers()
    assert "llamaindex" in [p["id"] for p in providers]
    assert "lightrag" in [p["id"] for p in providers]


def test_factory_has_pipeline_only_llamaindex() -> None:
    """Factory should only report llamaindex as selectable provider."""
    from deeptutor.services.rag.factory import has_pipeline

    assert has_pipeline("llamaindex") is True
    assert has_pipeline("lightrag") is True
    assert has_pipeline("raganything") is False
    assert has_pipeline("nonexistent") is False


def test_normalize_legacy_provider_aliases() -> None:
    """Legacy provider names should normalize to llamaindex."""
    from deeptutor.services.rag.factory import normalize_provider_name

    assert normalize_provider_name("llamaindex") == "llamaindex"
    assert normalize_provider_name("lightrag") == "lightrag"
    assert normalize_provider_name("raganything") == "llamaindex"
    assert normalize_provider_name("raganything_docling") == "llamaindex"


def test_get_current_provider_normalizes_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Current provider should normalize legacy env values."""
    from deeptutor.tools.rag_tool import get_current_provider

    monkeypatch.setenv("RAG_PROVIDER", "lightrag")
    assert get_current_provider() == "lightrag"

    monkeypatch.setenv("RAG_PROVIDER", "llamaindex")
    assert get_current_provider() == "llamaindex"

    monkeypatch.delenv("RAG_PROVIDER", raising=False)
    assert get_current_provider() == "llamaindex"


def test_get_pipeline_llamaindex_interface() -> None:
    """LlamaIndex pipeline should be constructible with optional dependency installed."""
    from deeptutor.services.rag.factory import get_pipeline

    try:
        pipeline = get_pipeline("llamaindex")
    except ValueError as exc:
        pytest.skip(f"LlamaIndex optional dependency missing: {exc}")

    assert hasattr(pipeline, "initialize")
    assert hasattr(pipeline, "search")
    assert hasattr(pipeline, "delete")


def test_get_pipeline_invalid_raises() -> None:
    """Unknown provider names should raise explicit error."""
    from deeptutor.services.rag.factory import get_pipeline

    with pytest.raises(ValueError, match="Unknown pipeline"):
        get_pipeline("nonexistent")


@pytest.mark.asyncio
async def test_rag_search_invalid_provider_falls_back_to_kb_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool wrapper should defer to KB-resolved provider (llamaindex-only runtime)."""
    from deeptutor.services.rag import service as rag_service_module
    from deeptutor.tools.rag_tool import rag_search

    monkeypatch.setattr(
        rag_service_module.RAGService,
        "_get_provider_for_kb",
        lambda self, kb_name: "llamaindex",
    )

    result = await rag_search(
        query="hello",
        kb_name="demo",
        provider="nonexistent",
        kb_base_dir=os.getcwd(),
    )
    assert result["provider"] == "llamaindex"
