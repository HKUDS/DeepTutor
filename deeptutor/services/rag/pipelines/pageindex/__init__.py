"""PageIndex Cloud and OSS knowledge-base lifecycle.

Both providers use the PageIndex SDK. Cloud reading stays on DeepTutor's built-in
PageIndex MCP connection; OSS reading uses SDK tools bound to the KB's Local
Library. Neither provider answers through ``RAGPipeline.search``.
"""

from __future__ import annotations

from .pipeline import PageIndexPipeline

__all__ = ["PageIndexPipeline"]
