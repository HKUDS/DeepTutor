"""Tests for query/document roles in the LlamaIndex embedding bridge."""

from __future__ import annotations

from contextvars import copy_context
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


def test_index_progress_is_cumulative_across_outer_embedding_groups(monkeypatch) -> None:
    from llama_index.core.schema import TextNode

    from deeptutor.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    class _FakeClient:
        config = SimpleNamespace(binding="openai", model="test", batch_size=5)

        async def embed(self, texts, progress_callback=None, *, input_type=None):
            assert input_type == "search_document"
            total = (len(texts) + 4) // 5
            for batch in range(1, total + 1):
                progress_callback(batch, total)
            return [[1.0] for _ in texts]

    client = _FakeClient()
    monkeypatch.setattr(embedding_module, "get_embedding_client", lambda config=None: client)
    embedding = embedding_module.CustomEmbedding(embed_batch_size=10)
    events: list[tuple[int, int]] = []
    embedding_module.set_progress_callback(lambda n, total: events.append((n, total)))
    try:
        nodes = [TextNode(text=f"chunk {n}") for n in range(23)]
        assert len(embedding(nodes)) == 23
    finally:
        embedding_module.set_progress_callback(None)

    # LlamaIndex makes outer calls of 10, 10, and 3 chunks. Provider batches
    # are 2, 2, and 1; their user-visible sequence must never restart at 1.
    assert events == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]


def test_old_embedding_context_cannot_pick_up_next_jobs_callback(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    class _FakeClient:
        config = SimpleNamespace(binding="openai", model="test", batch_size=1)

        async def embed(self, texts, progress_callback=None, *, input_type=None):
            progress_callback(1, 1)
            return [[1.0] for _ in texts]

    monkeypatch.setattr(embedding_module, "get_embedding_client", lambda config=None: _FakeClient())
    embedding = embedding_module.CustomEmbedding()
    old: list[tuple[int, int]] = []
    new: list[tuple[int, int]] = []
    embedding_module.set_progress_callback(lambda n, total: old.append((n, total)))
    old_worker_context = copy_context()
    embedding_module.set_progress_callback(lambda n, total: new.append((n, total)))
    try:
        old_worker_context.run(embedding._get_text_embeddings, ["old worker next group"])
        embedding._get_text_embeddings(["new worker"])
    finally:
        embedding_module.set_progress_callback(None)

    assert old == [(1, 1)]
    assert new == [(1, 1)]
