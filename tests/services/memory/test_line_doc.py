"""Tests for the line-numbered document view + edit application."""

from __future__ import annotations

from deeptutor.services.memory.consolidator.line_doc import (
    DeleteLinesOp,
    InsertAfterOp,
    ReplaceLineOp,
    apply_edits,
    parse_edits_payload,
    render_view,
)
from deeptutor.services.memory.document import Document, Entry, serialize
from deeptutor.services.memory.ids import new_entry_id


def _doc_with_three_entries() -> tuple[Document, list[str]]:
    ids = [new_entry_id() for _ in range(3)]
    doc = Document(
        title="notebook memory",
        sections=[
            (
                "Themes",
                [
                    Entry(
                        id=ids[0],
                        section="Themes",
                        text="uses spaced repetition",
                        refs=["notebook:r1"],
                    ),
                    Entry(
                        id=ids[1],
                        section="Themes",
                        text="prefers Anki over Quizlet",
                        refs=["notebook:r2"],
                    ),
                ],
            ),
            (
                "Open questions",
                [
                    Entry(
                        id=ids[2],
                        section="Open questions",
                        text="ε-δ geometric meaning",
                        refs=["notebook:r3"],
                    ),
                ],
            ),
        ],
    )
    return doc, ids


def test_render_view_shows_lines_and_section_headers() -> None:
    doc, ids = _doc_with_three_entries()
    view = render_view(doc)
    text = view.render()
    assert "## Themes" in text
    assert "## Open questions" in text
    assert f"[^{ids[0]}]" in text


def test_render_view_strips_footnote_block() -> None:
    doc, _ = _doc_with_three_entries()
    view = render_view(doc)
    # Sanitized view never contains a footnote definition.
    assert "[^" in view.render()  # bullet markers ok
    assert ": notebook:" not in view.render()  # footnote-body line absent


def test_replace_preserves_entry_id_and_replaces_refs() -> None:
    doc, ids = _doc_with_three_entries()
    view = render_view(doc)
    target_line = next(line for line in view.lines if line.entry_id == ids[0])
    edit = ReplaceLineOp(
        line=target_line.number,
        new_text="uses SRS with FSRS scheduling",
        refs=["notebook:r1", "notebook:r1b"],
        reason="more specific",
    )
    new_doc, report = apply_edits(doc, [edit])
    assert not report.rejected
    entry = next(e for e in new_doc.all_entries() if e.id == ids[0])
    assert entry.text == "uses SRS with FSRS scheduling"
    assert entry.refs == ["notebook:r1", "notebook:r1b"]


def test_delete_lines_removes_entries_and_collapses_empty_section() -> None:
    doc, ids = _doc_with_three_entries()
    view = render_view(doc)
    target_line = next(line for line in view.lines if line.entry_id == ids[2])
    edit = DeleteLinesOp(line_start=target_line.number, line_end=target_line.number, reason="stale")
    new_doc, report = apply_edits(doc, [edit])
    assert not report.rejected
    assert all(e.id != ids[2] for e in new_doc.all_entries())
    section_names = [name for name, _ in new_doc.sections]
    assert "Open questions" not in section_names  # empty section dropped


def test_insert_after_bullet_keeps_section_context() -> None:
    doc, ids = _doc_with_three_entries()
    view = render_view(doc)
    anchor = next(line for line in view.lines if line.entry_id == ids[1])
    edit = InsertAfterOp(
        after_line=anchor.number,
        text="uses Obsidian for daily notes",
        refs=["notebook:r4"],
        reason="new evidence",
    )
    new_doc, report = apply_edits(doc, [edit])
    assert not report.rejected
    themes = next(entries for name, entries in new_doc.sections if name == "Themes")
    assert any(e.text == "uses Obsidian for daily notes" for e in themes)


def test_replace_rejects_when_refs_empty() -> None:
    doc, ids = _doc_with_three_entries()
    view = render_view(doc)
    target_line = next(line for line in view.lines if line.entry_id == ids[0])
    edit = ReplaceLineOp(line=target_line.number, new_text="hello", refs=[], reason="bad")
    new_doc, report = apply_edits(doc, [edit])
    assert len(report.rejected) == 1
    # Original text still there.
    assert any(e.text == "uses spaced repetition" for e in new_doc.all_entries())


def test_apply_in_reverse_order_does_not_shift_line_numbers() -> None:
    doc, ids = _doc_with_three_entries()
    view = render_view(doc)
    first_line = next(line for line in view.lines if line.entry_id == ids[0])
    third_line = next(line for line in view.lines if line.entry_id == ids[2])

    # Delete line 8 (the third entry) and replace line 4 (the first
    # entry) — these are valid line numbers in the original view.
    edits = [
        ReplaceLineOp(line=first_line.number, new_text="updated", refs=["notebook:r1"], reason="x"),
        DeleteLinesOp(line_start=third_line.number, line_end=third_line.number, reason="stale"),
    ]
    new_doc, report = apply_edits(doc, edits)
    assert not report.rejected
    assert any(e.text == "updated" for e in new_doc.all_entries())
    assert all(e.id != ids[2] for e in new_doc.all_entries())


def test_parse_edits_payload_tolerates_fences_and_prose() -> None:
    raw = """Here are my edits:
    ```json
    {"edits": [
      {"op": "replace", "line": 4, "new_text": "x", "refs": ["a:b"], "reason": "y"},
      {"op": "delete",  "line_start": 8, "line_end": 8, "reason": "z"}
    ]}
    ```"""
    edits = parse_edits_payload(raw)
    assert len(edits) == 2
    assert isinstance(edits[0], ReplaceLineOp)
    assert isinstance(edits[1], DeleteLinesOp)


def test_parse_edits_payload_strips_ref_wrapper_chars() -> None:
    """LLM sometimes echoes ``[^m_xxx]`` markers from the line view —
    caret and brackets included — into the refs array."""
    raw = """{"edits": [
      {"op": "replace", "line": 4, "new_text": "x",
       "refs": ["^m_01HZK1ABCDEFGHJKMNPQRSTVWX", "  [chat:01]  "],
       "reason": "y"}
    ]}"""
    edits = parse_edits_payload(raw, layer="L3")
    assert isinstance(edits[0], ReplaceLineOp)
    # In L3 mode the m_<ULID> form is legal (L3 refs are L2 entry ids),
    # so it survives — but only with the ``^`` and surrounding noise
    # stripped.
    assert edits[0].refs == ["m_01HZK1ABCDEFGHJKMNPQRSTVWX", "chat:01"]


def test_parse_edits_payload_drops_entry_id_refs_in_l2() -> None:
    """L2 refs are ``surface:id`` shaped; ``m_<ULID>`` in L2 is the
    audit/dedup LLM hallucinating from the line-numbered view (it sees
    each bullet's entry-id anchor and copies it as a ref). Drop those."""
    raw = """{"edits": [
      {"op": "replace", "line": 4, "new_text": "x",
       "refs": ["^m_01HZK1ABCDEFGHJKMNPQRSTVWX", "cowriter:abc"],
       "reason": "y"}
    ]}"""
    edits = parse_edits_payload(raw, layer="L2")
    assert isinstance(edits[0], ReplaceLineOp)
    assert edits[0].refs == ["cowriter:abc"]


def test_parse_edits_payload_default_layer_keeps_everything() -> None:
    """Without a layer hint we only strip wrappers — never drop refs."""
    raw = """{"edits": [
      {"op": "insert", "after_line": 0, "text": "t",
       "refs": ["^m_01HZK1ABCDEFGHJKMNPQRSTVWX", "chat:01"],
       "reason": "r"}
    ]}"""
    edits = parse_edits_payload(raw)
    assert isinstance(edits[0], InsertAfterOp)
    assert edits[0].refs == ["m_01HZK1ABCDEFGHJKMNPQRSTVWX", "chat:01"]


def test_serialize_roundtrip_after_edits_keeps_footnotes_consistent() -> None:
    doc, ids = _doc_with_three_entries()
    view = render_view(doc)
    edit = ReplaceLineOp(
        line=next(line for line in view.lines if line.entry_id == ids[0]).number,
        new_text="updated text",
        refs=["notebook:r1-new"],
        reason="x",
    )
    new_doc, _ = apply_edits(doc, [edit])
    md = serialize(new_doc)
    # Footnote section reflects the updated refs (auto-rebuilt).
    assert "notebook:r1-new" in md
    # The old ref text is gone from footnotes (replaced, not appended).
    assert "notebook:r1," not in md and "notebook:r1\n" not in md
