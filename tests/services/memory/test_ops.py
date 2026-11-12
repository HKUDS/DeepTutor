from __future__ import annotations

import pytest

from deeptutor.services.memory.document import Document, Entry, parse, serialize
from deeptutor.services.memory.ops import AddOp, ApplyReport, DeleteOp, EditOp, Op, apply

_BASE_MD = """\
# Chat memory

## Misconceptions
- Original text[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]

---

[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]: chat:01HZK4AAAAAAAAAAAAAAAAAAAA
"""

_VALID_REF = "chat:01HZK4AAAAAAAAAAAAAAAAAAAA"
_EXISTING_ID = "m_01HZK4ABCDEFGHJKMNPQRSTVWX"


def _fresh_doc() -> Document:
    return parse(_BASE_MD)


def test_add_op_creates_entry_with_new_id() -> None:
    doc = _fresh_doc()
    report = apply(doc, [AddOp(section="Mastery", text="solid", refs=[_VALID_REF])])
    assert report.accepted
    assert len(report.results) == 1
    new_id = report.results[0].entry_id
    assert new_id and new_id.startswith("m_") and new_id != _EXISTING_ID
    entry = doc.find(new_id)
    assert entry is not None
    assert entry.text == "solid"
    assert entry.refs == [_VALID_REF]


def test_edit_op_updates_text_and_refs() -> None:
    doc = _fresh_doc()
    report = apply(
        doc,
        [
            EditOp(
                target_id=_EXISTING_ID,
                new_text="rewritten",
                new_refs=["chat:01HZK4BBBBBBBBBBBBBBBBBBBB"],
            )
        ],
    )
    assert report.accepted
    entry = doc.find(_EXISTING_ID)
    assert entry is not None
    assert entry.text == "rewritten"
    assert entry.refs == ["chat:01HZK4BBBBBBBBBBBBBBBBBBBB"]


def test_delete_op_removes_entry() -> None:
    doc = _fresh_doc()
    report = apply(doc, [DeleteOp(target_id=_EXISTING_ID, reason="superseded")])
    assert report.accepted
    assert doc.find(_EXISTING_ID) is None


def test_batch_conflict_edit_then_delete_rejects_whole_batch() -> None:
    doc = _fresh_doc()
    original_text = doc.find(_EXISTING_ID).text  # type: ignore[union-attr]
    report = apply(
        doc,
        [
            EditOp(target_id=_EXISTING_ID, new_text="changed", new_refs=[_VALID_REF]),
            DeleteOp(target_id=_EXISTING_ID, reason="stale"),
        ],
    )
    assert not report.accepted
    assert "edit and delete on same id" in report.reason
    # Doc untouched.
    assert doc.find(_EXISTING_ID).text == original_text  # type: ignore[union-attr]


def test_unknown_target_id_rejects() -> None:
    doc = _fresh_doc()
    report = apply(
        doc,
        [EditOp(target_id="m_01HZKZZZZZZZZZZZZZZZZZZZZZ", new_text="x", new_refs=[_VALID_REF])],
    )
    assert not report.accepted
    assert "not found" in report.reason


def test_add_without_refs_rejects() -> None:
    doc = _fresh_doc()
    report = apply(doc, [AddOp(section="Mastery", text="solid", refs=[])])
    assert not report.accepted
    assert "refs" in report.reason


def test_add_with_text_too_long_rejects() -> None:
    doc = _fresh_doc()
    report = apply(doc, [AddOp(section="S", text="x" * 241, refs=[_VALID_REF])])
    assert not report.accepted
    assert "text length" in report.reason


def test_add_with_invalid_ref_rejects() -> None:
    doc = _fresh_doc()
    report = apply(doc, [AddOp(section="S", text="ok", refs=["not-an-id"])])
    assert not report.accepted
    assert "malformed ref" in report.reason


def test_delete_with_invalid_reason_rejects() -> None:
    doc = _fresh_doc()
    report = apply(doc, [DeleteOp(target_id=_EXISTING_ID, reason="because")])
    assert not report.accepted
    assert "reason" in report.reason


def test_parallel_ops_applied_in_order() -> None:
    doc = _fresh_doc()
    report = apply(
        doc,
        [
            AddOp(section="Mastery", text="a", refs=[_VALID_REF]),
            AddOp(section="Mastery", text="b", refs=[_VALID_REF]),
            EditOp(target_id=_EXISTING_ID, new_text="updated", new_refs=[_VALID_REF]),
        ],
    )
    assert report.accepted
    mastery = [e for s, ents in doc.sections if s == "Mastery" for e in ents]
    assert [e.text for e in mastery] == ["a", "b"]
    assert doc.find(_EXISTING_ID).text == "updated"  # type: ignore[union-attr]


def test_repeated_edit_on_same_id_last_wins() -> None:
    doc = _fresh_doc()
    report = apply(
        doc,
        [
            EditOp(target_id=_EXISTING_ID, new_text="first", new_refs=[_VALID_REF]),
            EditOp(target_id=_EXISTING_ID, new_text="second", new_refs=[_VALID_REF]),
        ],
    )
    assert report.accepted
    assert doc.find(_EXISTING_ID).text == "second"  # type: ignore[union-attr]


def test_validation_failure_leaves_doc_untouched() -> None:
    doc = _fresh_doc()
    snapshot_entries = [(e.id, e.text, list(e.refs)) for e in doc.all_entries()]
    report = apply(
        doc,
        [
            AddOp(section="OK", text="valid", refs=[_VALID_REF]),
            AddOp(section="Bad", text="", refs=[_VALID_REF]),  # text empty → invalid
        ],
    )
    assert not report.accepted
    after = [(e.id, e.text, list(e.refs)) for e in doc.all_entries()]
    assert snapshot_entries == after


@pytest.mark.parametrize(
    "separator",
    ["\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"],
)
@pytest.mark.parametrize("field_name", ["add_text", "section", "edit_text"])
def test_line_break_rejects_whole_batch(separator: str, field_name: str) -> None:
    value = f"first{separator}second"
    bad_op: Op
    if field_name == "add_text":
        bad_op = AddOp(section="Notes", text=value, refs=[_VALID_REF])
    elif field_name == "section":
        bad_op = AddOp(section=value, text="valid", refs=[_VALID_REF])
    else:
        bad_op = EditOp(target_id=_EXISTING_ID, new_text=value, new_refs=[_VALID_REF])
    doc = _fresh_doc()
    before = serialize(doc)
    report = apply(
        doc,
        [
            AddOp(section="Valid", text="would be added", refs=[_VALID_REF]),
            bad_op,
        ],
    )
    assert not report.accepted
    assert "single line" in report.reason
    assert report.results == []
    assert serialize(doc) == before


@pytest.mark.parametrize(
    "bad_op",
    [
        AddOp(section="Notes", text="valid", refs=[_VALID_REF + "\n"]),
        EditOp(target_id=_EXISTING_ID, new_text="valid", new_refs=[_VALID_REF + "\n"]),
    ],
)
def test_ref_with_trailing_newline_rejects_whole_batch(bad_op: Op) -> None:
    doc = _fresh_doc()
    before = serialize(doc)
    report = apply(doc, [AddOp(section="Valid", text="valid", refs=[_VALID_REF]), bad_op])
    assert not report.accepted
    assert report.results == []
    assert serialize(doc) == before


def test_single_line_unicode_and_tabs_roundtrip() -> None:
    doc = _fresh_doc()
    report = apply(doc, [AddOp(section="概念\tNotes", text="Café\t总结", refs=[_VALID_REF])])
    assert report.accepted
    assert parse(serialize(doc)) == doc
