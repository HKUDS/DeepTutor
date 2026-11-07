# -*- coding: utf-8 -*-
"""
OpenAI Embedder
===============

Embedder using OpenAI-compatible embedding API.
"""

from ...types import Document
from ..base import BaseComponent


class OpenAIEmbedder(BaseComponent):
    """
    OpenAI-compatible embedder.

    Uses the embedding service to generate vectors for document chunks.
    """

    name = "openai_embedder"

    def __init__(self, batch_size: int = 100):
        """
        Initialize OpenAI embedder.

        Args:
            batch_size: Number of texts to embed per API call
        """
        super().__init__()
        self.batch_size = batch_size

    async def process(self, doc: Document, **kwargs) -> Document:
        """
        Embed a document's chunks.

        Args:
            doc: Document with chunks to embed
            **kwargs: Additional arguments

        Returns:
            Document with embedded chunks
        """
        if not doc.chunks:
            self.logger.warning("No chunks to embed")
            return doc

        self.logger.info(f"Embedding {len(doc.chunks)} chunks")

        from src.services.embedding import get_embedding_client

        client = get_embedding_client()

        # Batch embed
        for i in range(0, len(doc.chunks), self.batch_size):
            batch = doc.chunks[i : i + self.batch_size]
            texts = [chunk.content for chunk in batch]

            embeddings = await client.embed(texts)

            for chunk, embedding in zip(batch, embeddings):
                chunk.embedding = embedding

        self.logger.info("Embedding complete")
        return doc
