"""Key derivation, kept apart so both the writer and the reader agree.

``chunk_key`` must be computed identically by the ingestion pipeline and by any
caller that wants to reference a chunk without reading the row. Importing the
pipeline from the repository would invert the layering (repository is imported
by the pipeline), so the derivation lives in this leaf module that both may
import.
"""

from __future__ import annotations

import hashlib


def chunk_key(*, source_id: str, document_key: str, page_index: int, ordinal: int) -> str:
    """Positional identity of a chunk.

    Deliberately *not* derived from the text. If a parser upgrade changes the
    extracted text of a page, a text-derived key would change too, turning a
    re-parse into a delete-and-insert and dangling every citation already issued
    against that page. A positional key updates the row in place.
    """
    digest = hashlib.sha256(f"{source_id}\x1f{document_key}\x1f{page_index}\x1f{ordinal}".encode())
    return "chk_" + digest.hexdigest()[:32]


def text_checksum(text: str) -> str:
    """Checksum of the chunk's text, so a silent content change is detectable."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
