# -*- coding: utf-8 -*-
"""
Vector Indexer
==============

Vector-based indexer using dense embeddings with FAISS.
Provides fast similarity search for RAG retrieval.
"""

import json
from pathlib import Path
import pickle
from typing import List, Optional

import numpy as np

from ...types import Document
from ..base import BaseComponent


class VectorIndexer(BaseComponent):
    """
    Vector indexer using FAISS for fast similarity search.

    Creates and stores vector embeddings for efficient retrieval.
    Falls back to simple vector storage if FAISS is not available.
    """

    name = "vector_indexer"

    def __init__(self, kb_base_dir: Optional[str] = None):
        """
        Initialize vector indexer.

        Args:
            kb_base_dir: Base directory for knowledge bases
        """
        super().__init__()
        self.kb_base_dir = kb_base_dir or str(
            Path(__file__).resolve().parent.parent.parent.parent.parent.parent
            / "data"
            / "knowledge_bases"
        )

        # Try to import FAISS, fallback to simple storage if not available
        self.use_faiss = False
        try:
            import faiss

            self.faiss = faiss
            self.use_faiss = True
            self.logger.info("Using FAISS for vector indexing")
        except ImportError:
            self.logger.warning("FAISS not available, using simple vector storage")

    async def process(self, kb_name: str, documents: List[Document], **kwargs) -> bool:
        """
        Index documents using vector embeddings.

        Creates FAISS index for fast similarity search or falls back to
        simple JSON storage if FAISS is unavailable.

        Args:
            kb_name: Knowledge base name
            documents: List of documents to index
            **kwargs: Additional arguments

        Returns:
            True if successful
        """
        self.logger.info(f"Indexing {len(documents)} documents into vector store for {kb_name}")

        # Collect all chunks with embeddings
        all_chunks = []
        for doc in documents:
            for chunk in doc.chunks:
                # Check if embedding exists (handles numpy arrays and lists)
                if chunk.embedding is not None and len(chunk.embedding) > 0:
                    all_chunks.append(chunk)

        if not all_chunks:
            self.logger.warning("No chunks with embeddings to index")
            return False

        self.logger.info(f"Indexing {len(all_chunks)} chunks")

        # Create vector store directory
        kb_dir = Path(self.kb_base_dir) / kb_name / "vector_store"
        kb_dir.mkdir(parents=True, exist_ok=True)

        # Convert embeddings to numpy array
        embeddings = np.array(
            [
                chunk.embedding if isinstance(chunk.embedding, list) else chunk.embedding.tolist()
                for chunk in all_chunks
            ],
            dtype=np.float32,
        )

        # Store metadata separately
        metadata = []
        for i, chunk in enumerate(all_chunks):
            metadata.append(
                {
                    "id": i,
                    "content": chunk.content,
                    "type": chunk.chunk_type,
                    "metadata": chunk.metadata,
                }
            )

        # Save metadata
        with open(kb_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        if self.use_faiss:
            # Create FAISS index for inner product (cosine similarity with normalized vectors)
            dimension = embeddings.shape[1]
            index = self.faiss.IndexFlatIP(dimension)  # Inner product for cosine similarity

            # Normalize vectors for cosine similarity (inner product of normalized vectors = cosine similarity)
            self.faiss.normalize_L2(embeddings)

            # Add vectors to index
            index.add(embeddings)

            # Save FAISS index
            self.faiss.write_index(index, str(kb_dir / "index.faiss"))
            self.logger.info(f"FAISS index saved with {index.ntotal} vectors")
        else:
            # Simple storage: save embeddings as pickle
            with open(kb_dir / "embeddings.pkl", "wb") as f:
                pickle.dump(embeddings, f)
            self.logger.info(f"Embeddings saved for {len(all_chunks)} chunks")

        # Save index info
        info = {
            "num_chunks": len(all_chunks),
            "num_documents": len(documents),
            "embedding_dim": embeddings.shape[1],
            "use_faiss": self.use_faiss,
        }
        with open(kb_dir / "info.json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)

        self.logger.info(f"Vector index saved to {kb_dir}")
        return True
