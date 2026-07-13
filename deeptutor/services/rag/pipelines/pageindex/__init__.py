"""PageIndex cloud-backed RAG pipeline.

A KB indexed with the ``pageindex`` provider ships its documents to the hosted
PageIndex service (https://pageindex.ai), which builds a hierarchical tree per
document and serves reasoning-based, vectorless retrieval. DeepTutor's own chat
LLM still writes the final answer — only retrieval is delegated. The pipeline
talks to PageIndex's documented REST API directly (see ``client``).
"""

from __future__ import annotations

from .pipeline import PageIndexPipeline

__all__ = ["PageIndexPipeline"]
