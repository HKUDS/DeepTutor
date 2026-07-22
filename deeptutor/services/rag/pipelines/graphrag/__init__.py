"""GraphRAG (microsoft/graphrag) local RAG pipeline.

A KB indexed with the ``graphrag`` provider builds a local knowledge graph
(entities, relationships, communities, community reports) from text and serves
GraphRAG's global/local/drift/basic retrieval. DeepTutor parses documents to
text first and bridges its own LLM/embedding config into GraphRAG's settings, so
GraphRAG never parses documents or owns model credentials of its own.

GraphRAG is an optional dependency (``pip install 'deeptutor[graphrag]'``). The
pipeline module imports cleanly without it installed; only actual indexing /
retrieval requires the package.
"""

from __future__ import annotations

from .pipeline import GraphRagPipeline

__all__ = ["GraphRagPipeline"]
