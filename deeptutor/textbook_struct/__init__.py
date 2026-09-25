"""textbook_struct — rebuild a textbook chapter tree from MinerU layout.json.

Deterministic layered criteria (column blacklist → regex → position →
adjacent merge), zero LLM.

Nothing in this package imports deeptutor.
"""

from .chapter_rebuild import Chapter, rebuild, rebuild_from_headers_level, verify_offset
from .column_blacklist import COLUMN_BLACKLIST
from .page_headers import rebuild_from_headers

__all__ = [
    "Chapter",
    "rebuild",
    "rebuild_from_headers",
    "rebuild_from_headers_level",
    "verify_offset",
    "COLUMN_BLACKLIST",
]
