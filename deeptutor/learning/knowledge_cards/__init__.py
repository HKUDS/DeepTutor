"""Knowledge-card draft domain, service, offline generation worker and durable
publication (KB-02 / KB-03).

Durable behavior for knowledge-card drafts over the integrated LRN-01/LRN-02/
LRN-03 learning aggregates, MOD-03 invocation audit and MED-01 artifact
references, plus restart-safe, idempotent publication into a writable local
indexed KB. This package never calls a live model and never stores credentials,
private URLs, base64/media payloads or raw provider responses.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "KnowledgeCardBlobStore",
    "KnowledgeCardDraftService",
    "KnowledgeCardGenerationWorker",
    "KnowledgeCardPublicationService",
    "KnowledgeCardRuntime",
    "DraftExecutor",
    "DraftOutput",
]


def __getattr__(name: str) -> Any:
    if name == "KnowledgeCardBlobStore":
        from .blobs import KnowledgeCardBlobStore

        return KnowledgeCardBlobStore
    if name == "KnowledgeCardDraftService":
        from .service import KnowledgeCardDraftService

        return KnowledgeCardDraftService
    if name == "KnowledgeCardGenerationWorker":
        from .worker import KnowledgeCardGenerationWorker

        return KnowledgeCardGenerationWorker
    if name == "KnowledgeCardPublicationService":
        from .publish import KnowledgeCardPublicationService

        return KnowledgeCardPublicationService
    if name == "KnowledgeCardRuntime":
        from .runtime import KnowledgeCardRuntime

        return KnowledgeCardRuntime
    if name == "DraftExecutor":
        from .worker import DraftExecutor

        return DraftExecutor
    if name == "DraftOutput":
        from .worker import DraftOutput

        return DraftOutput
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
