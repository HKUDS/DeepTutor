"""textbook_struct — rebuild a textbook chapter tree from MinerU layout.json.

Deterministic four-layer criteria (regex → position → adjacent-merge → TOC
cross-check), zero LLM. Spec source:
``Workbuddy-Zone/Learn/03-实施方案/P0-章节重建引擎实施方案.md`` §4.

Shared asset: consumed by the DT textbook-import path and the self-built
reader alike. Nothing in this package imports deeptutor (asset red line #1).
"""

from .chapter_rebuild import Chapter, rebuild
from .column_blacklist import COLUMN_BLACKLIST
from .toc_crosscheck import cross_check_with_toc, extract_toc_entries

__all__ = [
    "Chapter",
    "rebuild",
    "COLUMN_BLACKLIST",
    "extract_toc_entries",
    "cross_check_with_toc",
]
