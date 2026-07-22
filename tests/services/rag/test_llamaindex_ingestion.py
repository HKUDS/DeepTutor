from __future__ import annotations

from llama_index.core import Document
from llama_index.core.schema import TextNode


def test_documents_do_not_bypass_chunking_pipeline(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import ingestion

    captured: dict[str, object] = {}

    class FakePipeline:
        def run(self, *, documents, show_progress):
            captured["documents"] = list(documents)
            captured["show_progress"] = show_progress
            return [f"chunked:{type(item).__name__}" for item in documents]

    monkeypatch.setattr(ingestion, "build_ingestion_pipeline", lambda: FakePipeline())

    llama_document = Document(text="long document text")
    embedded_node = TextNode(text="already embedded", embedding=[0.1, 0.2])
    plain_node = TextNode(text="node without embedding")

    nodes = ingestion.documents_to_nodes(
        [llama_document, embedded_node, plain_node],
        show_progress=False,
    )

    assert captured["documents"] == [llama_document, plain_node]
    assert captured["show_progress"] is False
    assert nodes == ["chunked:Document", "chunked:TextNode", embedded_node]
