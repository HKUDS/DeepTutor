"""Retrieval-only RAG pipeline backed by a Tencent IMA knowledge base.

A KB bound to the ``ima`` provider is a connection pointer to a library the user
keeps in IMA (https://ima.qq.com) and curates there. DeepTutor never indexes or
stores anything locally: retrieval calls IMA's ``search_knowledge`` OpenAPI
(passages only — DeepTutor's chat LLM still writes the answer), and the
credentials plus knowledge base id are configured per-KB. See ``client`` for the
wire and ``probe`` for the connect-time health check.
"""

from __future__ import annotations

from .pipeline import ImaPipeline

__all__ = ["ImaPipeline"]
