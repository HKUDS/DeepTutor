"""textbook_struct — rebuild a textbook chapter tree from MinerU layout.json.

Deterministic layered criteria (column blacklist → regex → position →
adjacent merge), zero LLM.

Nothing in this package imports deeptutor.
"""

from .chapter_rebuild import Chapter, rebuild
from .column_blacklist import COLUMN_BLACKLIST

__all__ = [
    "Chapter",
    "rebuild",
    "COLUMN_BLACKLIST",
]
