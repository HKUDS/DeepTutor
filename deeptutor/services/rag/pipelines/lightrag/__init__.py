"""LightRAG / RAG-Anything knowledge-base engine.

A graph-based RAG provider built on HKUDS/LightRAG (multimodal via
HKUDS/RAG-Anything). It consumes DeepTutor's shared parse layer for document
parsing and exposes LightRAG's native query modes (naive/local/global/hybrid/mix)
through the per-KB ``search_mode``.

Modules:

* ``config``   — availability + mode helpers + the LLM/vision/embedding adapters.
* ``storage``  — per-KB version-dir layout + readiness marker.
* ``engine``   — the ONLY module importing ``raganything``/``lightrag``.
* ``pipeline`` — :class:`LightRagPipeline` implementing the ``RAGPipeline`` contract.
"""
