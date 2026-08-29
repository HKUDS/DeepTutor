"""Native LightRAG knowledge-base engine.

A graph-based RAG provider built directly on HKUDS/LightRAG. It consumes
DeepTutor's shared parse layer for document parsing and exposes LightRAG's
native query modes (naive/local/global/hybrid/mix) through the per-KB
``search_mode``.

Modules:

* ``block_policy`` — versioned MinerU block classification before indexing.
* ``config``   — availability + mode helpers + the LLM/vision/embedding adapters.
* ``storage``  — per-KB version-dir layout + readiness marker.
* ``engine``   — constructs the exact supported LightRAG SDK version.
* ``pipeline`` — :class:`LightRagPipeline` implementing the ``RAGPipeline`` contract.
"""
