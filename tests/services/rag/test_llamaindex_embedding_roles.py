"""Tests for query/document roles in the LlamaIndex embedding bridge."""

from __future__ import annotations

from types import SimpleNamespace


def test_custom_embedding_passes_query_and_document_roles(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    class _FakeClient:
        config = SimpleNamespace(
            binding="gemini",
            model="gemini-embedding-2",
            dim=768,
            effective_url="https://example.test/v1/embeddings",
            base_url="https://example.test/v1/embeddings",
            api_version=None,
            send_dimensions=None,
        )

        def __init__(self) -> None:
            self.calls: list[tuple[list[str], str | None]] = []

        async def embed(
            self,
            texts,
            progress_callback=None,
            *,
            input_type: str | None = None,
        ):
            del progress_callback
            self.calls.append((list(texts), input_type))
            return [[1.0] for _ in texts]

    client = _FakeClient()
    monkeypatch.setattr(embedding_module, "get_embedding_client", lambda config=None: client)
    embedding = embedding_module.CustomEmbedding()

    assert embedding._get_query_embedding("question") == [1.0]
    assert embedding._get_text_embedding("document") == [1.0]
    assert embedding._get_text_embeddings(["one", "two"]) == [[1.0], [1.0]]
    assert client.calls == [
        (["question"], "search_query"),
        (["document"], "search_document"),
        (["one", "two"], "search_document"),
    ]
