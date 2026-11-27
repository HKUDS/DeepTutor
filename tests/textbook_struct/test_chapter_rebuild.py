"""Chapter de-duplication must keep the body hit, not the last in list order."""

from __future__ import annotations

from deeptutor.textbook_struct.chapter_rebuild import Chapter, _dedupe_keep_last


def test_dedupe_keeps_higher_page_regardless_of_list_order() -> None:
    # A chapter title appears on a TOC page (page 1) and in the body (page 10).
    # _dedupe_keep_last promises to keep the body hit (the higher page). When
    # pdf_info is not ascending by page_idx — the body entry listed first — the
    # unconditional overwrite kept the TOC hit instead.
    chapters = [
        Chapter(title="Vectors", page_idx=10, bbox=[]),  # body
        Chapter(title="Vectors", page_idx=1, bbox=[]),  # TOC, later in list
    ]

    kept = _dedupe_keep_last(chapters)

    assert [c.page_idx for c in kept] == [10]


def test_dedupe_keeps_higher_page_when_already_sorted() -> None:
    chapters = [
        Chapter(title="Vectors", page_idx=1, bbox=[]),  # TOC
        Chapter(title="Vectors", page_idx=10, bbox=[]),  # body
    ]

    kept = _dedupe_keep_last(chapters)

    assert [c.page_idx for c in kept] == [10]
