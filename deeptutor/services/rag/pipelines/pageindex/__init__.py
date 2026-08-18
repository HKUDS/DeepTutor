"""PageIndex Cloud and OSS knowledge-base lifecycle.

Both providers use turn-scoped PageIndex SDK tools: Cloud delegates its transport
to the SDK, while OSS binds the same interface to the KB's Local Library. Neither
provider answers through ``RAGPipeline.search``.
"""

from __future__ import annotations

from .pipeline import PageIndexPipeline

__all__ = ["PageIndexPipeline"]
