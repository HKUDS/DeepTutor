"""Scoped text retrieval keeps plain-text documents inside their source (#2374).

LlamaIndex enforces a document scope by rebuilding a corpus from only the
in-scope nodes. Source-schema nodes carry ``document_key``, but plain-text
documents are ingested with just ``file_path``/``file_name`` metadata, so the
scope matcher must also recognise them through their location under the KB's
``raw`` directory — and never by bare name similarity with other files.
"""

from __future__ import annotations

from pathlib import Path

from llama_index.core import VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode

from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module


def _plain_index(raw: Path) -> VectorStoreIndex:
    """Two text documents, ingested the way ``document_loader`` ingests them."""
    nodes = [
        TextNode(
            text="Inspect the pump seal before restart.",
            id_="notes-hit",
            metadata={"file_name": "notes.txt", "file_path": str(raw / "notes.txt")},
        ),
        TextNode(
            text="Torque the cover bolts in sequence.",
            id_="manual-hit",
            metadata={"file_name": "manual.txt", "file_path": str(raw / "manual.txt")},
        ),
        TextNode(
            text="Nested appendix with the same basename.",
            id_="nested-hit",
            metadata={
                "file_name": "notes.txt",
                "file_path": str(raw / "sub" / "notes.txt"),
            },
        ),
    ]
    return VectorStoreIndex(nodes, embed_model=MockEmbedding(embed_dim=8))


def test_scoped_retrieval_keeps_plain_text_documents_in_scope(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "sub").mkdir(parents=True)
    index = _plain_index(raw)

    hits = retriever_module.retrieve_scoped_nodes(
        index, "pump seal restart", ["notes.txt"], top_k=4, raw_root=raw
    )

    assert [hit.node.node_id for hit in hits] == ["notes-hit"]


def test_scoped_retrieval_matches_nested_keys_without_basename_leak(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    (raw / "sub").mkdir(parents=True)
    index = _plain_index(raw)

    nested = retriever_module.retrieve_scoped_nodes(
        index, "appendix basename", ["sub/notes.txt"], top_k=4, raw_root=raw
    )
    flat = retriever_module.retrieve_scoped_nodes(
        index, "appendix basename", ["notes.txt"], top_k=4, raw_root=raw
    )

    assert [hit.node.node_id for hit in nested] == ["nested-hit"]
    assert [hit.node.node_id for hit in flat] == ["notes-hit"]


def test_scoped_retrieval_without_raw_root_does_not_match_by_basename(
    tmp_path: Path,
) -> None:
    """No ``raw`` root means no positional check — never a loose name match."""
    raw = tmp_path / "raw"
    (raw / "sub").mkdir(parents=True)
    index = _plain_index(raw)

    assert (
        retriever_module.retrieve_scoped_nodes(index, "pump seal restart", ["manual.txt"], top_k=4)
        == []
    )


def test_scoped_retrieval_returns_nothing_outside_the_requested_document(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    (raw / "sub").mkdir(parents=True)
    index = _plain_index(raw)

    assert (
        retriever_module.retrieve_scoped_nodes(
            index, "anything", ["reports.csv"], top_k=4, raw_root=raw
        )
        == []
    )
