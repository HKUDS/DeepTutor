"""Retrieval-only RAG pipeline backed by an external LightRAG server.

A KB bound to the ``lightrag-server`` provider is a connection pointer to a
standalone LightRAG server the user runs and indexed themselves. DeepTutor never
indexes or stores anything locally: retrieval is offloaded to the server's
``/query`` endpoint (context only — DeepTutor's chat LLM still writes the
answer), and the endpoint is configured per-KB. See ``client`` for the wire and
``probe`` for the connect-time health check.
"""

from __future__ import annotations

from .pipeline import LightRagServerPipeline

__all__ = ["LightRagServerPipeline"]
