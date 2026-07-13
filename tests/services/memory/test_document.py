from __future__ import annotations

from deeptutor.services.memory.document import Document, Entry, parse, serialize

_SAMPLE = """\
# Chat memory

## Misconceptions
- Student misreads "for all ε" as "for some ε"[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]
- Forgets to multiply by g'(x) in chain rule[^m_01HZK5ABCDEFGHJKMNPQRSTVWX]

## Mastery
- Has geometric intuition for limits[^m_01HZK6ABCDEFGHJKMNPQRSTVWX]

---

[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]: chat:01HZK4AAAAAAAAAAAAAAAAAAAA, chat:01HZK4BBBBBBBBBBBBBBBBBBBB
[^m_01HZK5ABCDEFGHJKMNPQRSTVWX]: chat:01HZK5CCCCCCCCCCCCCCCCCCCC
[^m_01HZK6ABCDEFGHJKMNPQRSTVWX]: chat:01HZK6DDDDDDDDDDDDDDDDDDDD
"""


def test_parse_extracts_title_sections_entries() -> None:
    doc = parse(_SAMPLE)
    assert doc.title == "Chat memory"
    assert len(doc.sections) == 2
    section_names = [name for name, _ in doc.sections]
    assert section_names == ["Misconceptions", "Mastery"]
    assert len(doc.sections[0][1]) == 2
    assert len(doc.sections[1][1]) == 1


def test_parse_binds_refs_to_entries() -> None:
    doc = parse(_SAMPLE)
    first = doc.sections[0][1][0]
    assert first.id == "m_01HZK4ABCDEFGHJKMNPQRSTVWX"
    assert first.refs == [
        "chat:01HZK4AAAAAAAAAAAAAAAAAAAA",
        "chat:01HZK4BBBBBBBBBBBBBBBBBBBB",
    ]


def test_round_trip_is_idempotent() -> None:
    doc = parse(_SAMPLE)
    rendered = serialize(doc)
    again = serialize(parse(rendered))
    assert rendered == again


def test_serialize_empty_doc() -> None:
    assert serialize(Document()) == "\n"


def test_serialize_skips_empty_sections() -> None:
    doc = Document(title="X")
    doc.sections.append(("Empty", []))
    rendered = serialize(doc)
    assert "Empty" not in rendered
    assert rendered.startswith("# X")


def test_find_and_remove() -> None:
    doc = parse(_SAMPLE)
    target = "m_01HZK5ABCDEFGHJKMNPQRSTVWX"
    assert doc.find(target) is not None
    assert doc.remove(target) is True
    assert doc.find(target) is None
    assert doc.remove(target) is False  # already gone


def test_section_entries_creates_when_missing() -> None:
    doc = Document(title="X")
    entries = doc.section_entries("New section")
    entries.append(Entry(id="m_01HZK7ABCDEFGHJKMNPQRSTVWX", section="New section", text="hi"))
    assert doc.sections == [("New section", entries)]
    # Second call returns the same list, not a new one.
    assert doc.section_entries("New section") is entries


def test_parse_ignores_malformed_lines() -> None:
    md = """\
# T

## S
- text without id
- text with id[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]

random prose

[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]: chat:01HZK4AAAAAAAAAAAAAAAAAAAA
"""
    doc = parse(md)
    assert len(doc.sections[0][1]) == 1
    assert doc.sections[0][1][0].text == "text with id"


_NEW_SAMPLE = """\
# Notebook memory

## Concepts
- Limit definition uses ε-δ pairing [^1] <!--m_01HZK4ABCDEFGHJKMNPQRSTVWX-->
- Continuity implies sequential continuity [^1][^2] <!--m_01HZK5ABCDEFGHJKMNPQRSTVWX-->

## Mastery
- Has geometric intuition [^2] <!--m_01HZK6ABCDEFGHJKMNPQRSTVWX-->

---

[^1]: notebook:01HZK4AAAAAAAAAAAAAAAAAAAA
[^2]: notebook:01HZK4BBBBBBBBBBBBBBBBBBBB
"""


def test_parse_new_format_resolves_refs_via_label_map() -> None:
    doc = parse(_NEW_SAMPLE)
    assert doc.title == "Notebook memory"
    first = doc.sections[0][1][0]
    assert first.id == "m_01HZK4ABCDEFGHJKMNPQRSTVWX"
    assert first.refs == ["notebook:01HZK4AAAAAAAAAAAAAAAAAAAA"]
    second = doc.sections[0][1][1]
    assert second.refs == [
        "notebook:01HZK4AAAAAAAAAAAAAAAAAAAA",
        "notebook:01HZK4BBBBBBBBBBBBBBBBBBBB",
    ]


def test_serialize_consolidates_duplicate_refs() -> None:
    """Five entries citing the same source render as ONE footnote definition."""
    doc = Document(title="Notebook")
    section: list[Entry] = []
    doc.sections.append(("Concepts", section))
    same_ref = "notebook:3a563e6f"
    for i in range(5):
        section.append(
            Entry(
                id=f"m_01HZK{i}ABCDEFGHJKMNPQRSTVWX",
                section="Concepts",
                text=f"fact {i}",
                refs=[same_ref],
            )
        )
    rendered = serialize(doc)
    # All five bullets share the same [^1] marker.
    assert rendered.count("[^1]") == 6  # 5 bullets + 1 def
    # Only ONE footnote definition.
    assert rendered.count(f"[^1]: {same_ref}") == 1
    assert "[^2]" not in rendered


def test_serialize_assigns_labels_in_first_appearance_order() -> None:
    doc = Document(title="X")
    section: list[Entry] = []
    doc.sections.append(("S", section))
    section.append(
        Entry(
            id="m_01HZK1ABCDEFGHJKMNPQRSTVWX",
            section="S",
            text="a",
            refs=["chat:01", "chat:02"],
        )
    )
    section.append(
        Entry(
            id="m_01HZK2ABCDEFGHJKMNPQRSTVWX",
            section="S",
            text="b",
            refs=["chat:03", "chat:01"],  # ``chat:01`` repeats earlier ref
        )
    )
    rendered = serialize(doc)
    assert "[^1]: chat:01" in rendered
    assert "[^2]: chat:02" in rendered
    assert "[^3]: chat:03" in rendered
    # Second bullet cites refs in entry order — label 3 then label 1.
    # Markers are ``, ``-separated so the rendered superscripts read
    # "³, ¹" rather than the visually-merged "³¹".
    assert "- b [^3], [^1] <!--m_01HZK2ABCDEFGHJKMNPQRSTVWX-->" in rendered


def test_legacy_doc_serialized_then_reparsed_is_lossless() -> None:
    """Migration path: old → new → parse → same entries."""
    old = parse(_SAMPLE)
    migrated = serialize(old)
    reparsed = parse(migrated)
    # Entry ids and refs are preserved across the migration.
    assert [e.id for e in old.all_entries()] == [e.id for e in reparsed.all_entries()]
    assert [e.refs for e in old.all_entries()] == [e.refs for e in reparsed.all_entries()]
    assert [e.text for e in old.all_entries()] == [e.text for e in reparsed.all_entries()]


def test_new_format_round_trip_is_idempotent() -> None:
    doc = parse(_NEW_SAMPLE)
    rendered = serialize(doc)
    again = serialize(parse(rendered))
    assert rendered == again


def test_parse_tolerates_both_separator_styles_between_markers() -> None:
    """Bullets emitted before the separator change had ``[^1][^2]`` —
    the comma-tolerant parser still binds refs correctly on legacy
    in-flight docs."""
    md_compact = """\
# X

## S
- a [^1][^2] <!--m_01HZK1ABCDEFGHJKMNPQRSTVWX-->

---

[^1]: chat:01
[^2]: chat:02
"""
    md_spaced = """\
# X

## S
- a [^1], [^2] <!--m_01HZK1ABCDEFGHJKMNPQRSTVWX-->

---

[^1]: chat:01
[^2]: chat:02
"""
    a = parse(md_compact).all_entries()[0]
    b = parse(md_spaced).all_entries()[0]
    assert a.refs == b.refs == ["chat:01", "chat:02"]


def test_serialize_omits_marker_when_entry_has_no_refs() -> None:
    doc = Document(title="X")
    section: list[Entry] = []
    doc.sections.append(("S", section))
    section.append(Entry(id="m_01HZK1ABCDEFGHJKMNPQRSTVWX", section="S", text="t", refs=[]))
    rendered = serialize(doc)
    assert "- t <!--m_01HZK1ABCDEFGHJKMNPQRSTVWX-->" in rendered
    # No footnote definitions block at all when nothing has refs.
    assert "---" not in rendered
