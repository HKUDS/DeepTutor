"""LlamaIndex ingestion helpers.

This module keeps DeepTutor's indexing path thin by delegating parsing
transformations and embedding to LlamaIndex's official IngestionPipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode, Document


def build_ingestion_pipeline() -> IngestionPipeline:
    """Create the default DeepTutor ingestion pipeline.

    The embedding step uses ``Settings.embed_model``, which is configured by
    ``embedding_adapter.configure_llamaindex_settings`` to call DeepTutor's
    configured embedding service rather than any local model.
    """

    return IngestionPipeline(
        transformations=[
            SentenceSplitter(
                chunk_size=Settings.chunk_size,
                chunk_overlap=Settings.chunk_overlap,
            ),
            Settings.embed_model,
        ],
    )


def _has_precomputed_embedding(node: Any) -> bool:
    """Return True if node already carries an embedding vector.

    LlamaIndex's Document class inherits from BaseNode, so a naive
    ``isinstance(doc, BaseNode)`` check incorrectly classifies every
    Document as pre-embedded, bypassing the chunking pipeline entirely.
    This helper distinguishes genuinely pre-embedded nodes (e.g. ImageNode
    produced by multimodal loaders) from regular Documents that still need
    splitting and embedding.
    """
    if isinstance(node, Document):
        return False
    return isinstance(node, BaseNode) and bool(getattr(node, "embedding", None))


def documents_to_nodes(documents: list[Any], *, show_progress: bool = True) -> list[Any]:
    """Convert LlamaIndex documents into embedded nodes.

    Pre-embedded nodes, such as ImageNode instances produced by the document
    loader, pass through unchanged so they are not re-embedded as text.
    """
    text_documents = [doc for doc in documents if not _has_precomputed_embedding(doc)]
    preembedded_nodes = [doc for doc in documents if _has_precomputed_embedding(doc)]

    nodes: list[Any] = []
    if text_documents:
        pipeline = build_ingestion_pipeline()
        nodes.extend(pipeline.run(documents=text_documents, show_progress=show_progress))
    nodes.extend(preembedded_nodes)
    return nodes


def create_index_from_documents(
    documents: list[Any], storage_dir: Path, *, show_progress: bool = True
) -> tuple[VectorStoreIndex, int]:
    """Create and persist a VectorStoreIndex from documents."""
    nodes = documents_to_nodes(documents, show_progress=show_progress)
    index = VectorStoreIndex(nodes=nodes, show_progress=show_progress)
    index.storage_context.persist(persist_dir=str(storage_dir))
    return index, len(documents)


def insert_documents_into_index(
    index: Any, documents: list[Any], *, show_progress: bool = True
) -> int:
    """Transform documents once, then insert nodes into an existing index."""
    nodes = documents_to_nodes(documents, show_progress=show_progress)
    index.insert_nodes(nodes)
    return len(documents)


__all__ = [
    "build_ingestion_pipeline",
    "create_index_from_documents",
    "documents_to_nodes",
    "insert_documents_into_index",
]
