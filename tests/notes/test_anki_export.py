"""Anki text export for notebook flashcards."""

from __future__ import annotations

import json
from types import SimpleNamespace

from deeptutor.co_writer.storage import CoWriterStorage
from deeptutor.notes.anki_export import (
    ANKI_HEADERS,
    cards_from_document,
    cards_from_storage,
    deck_name,
    markdown_to_anki_html,
    note_tags,
    render_anki_export,
)
from deeptutor.notes.review import page_cards
from tests.notes.test_block_pages import Paths


def _flash_block(block_id: str, cards: object, *, kind: str = "flashcards") -> dict:
    return {
        "id": block_id,
        "type": "learning",
        "props": {
            "kind": kind,
            "data": json.dumps({"cards": cards}) if not isinstance(cards, str) else cards,
        },
        "children": [],
    }


def _doc(title: str, blocks: list, doc_id: str = "abc123def456") -> SimpleNamespace:
    return SimpleNamespace(id=doc_id, title=title, blocks=blocks)


def _rows(text: str) -> list[list[str]]:
    body = text.splitlines()
    assert tuple(body[: len(ANKI_HEADERS)]) == ANKI_HEADERS
    return [line.split("\t") for line in body[len(ANKI_HEADERS) :] if line]


def test_headers_and_one_row_per_card_with_deck_tag_guid_columns():
    doc = _doc(
        "Fourier analysis",
        [
            _flash_block(
                "flash",
                [{"front": "What is frequency?", "back": "Cycles per second"}],
            )
        ],
    )
    cards = cards_from_document(doc)
    text = render_anki_export(cards)
    rows = _rows(text)
    assert len(rows) == 1
    front, back, deck, tags, guid = rows[0]
    assert "frequency" in front
    assert "Cycles" in back
    assert deck == "DeepTutor::Fourier analysis"
    assert tags == "deeptutor fourier-analysis"
    assert guid == cards[0]["card_id"]
    assert guid.startswith("flash:")


def test_multiple_flashcard_blocks_on_one_page_export_in_walk_order():
    nested = {
        "id": "cols",
        "type": "noteColumns",
        "props": {},
        "children": [
            {
                "id": "left",
                "type": "noteColumn",
                "props": {},
                "children": [_flash_block("inner", [{"front": "Nested?", "back": "Yes"}])],
            }
        ],
    }
    doc = _doc(
        "Mix",
        [
            _flash_block("first", [{"front": "One", "back": "1"}]),
            {"id": "p", "type": "paragraph", "props": {}, "children": []},
            _flash_block(
                "second", [{"front": "Two", "back": "2"}, {"front": "Three", "back": "3"}]
            ),
            nested,
        ],
    )
    rows = _rows(render_anki_export(cards_from_document(doc)))
    fronts = [row[0] for row in rows]
    assert (
        "One" in fronts[0]
        and "Two" in fronts[1]
        and "Three" in fronts[2]
        and "Nested?" in fronts[3]
    )
    assert len(rows) == 4


def test_malformed_block_data_is_skipped_like_page_cards():
    doc = _doc(
        "Broken",
        [
            _flash_block("ok", [{"front": "Keep", "back": "Me"}]),
            {
                "id": "bad-json",
                "type": "learning",
                "props": {"kind": "flashcards", "data": "not-json"},
                "children": [],
            },
            {
                "id": "bad-list",
                "type": "learning",
                "props": {"kind": "flashcards", "data": json.dumps({"cards": {"front": "nope"}})},
                "children": [],
            },
            _flash_block(
                "partial",
                [
                    {"front": "", "back": "empty front"},
                    "not-a-card",
                    {"back": "missing front"},
                    {"front": "Valid", "back": "Kept"},
                ],
            ),
            _flash_block("quiz", [{"front": "Not a card deck", "back": "x"}], kind="quiz"),
        ],
    )
    cards = cards_from_document(doc)
    assert [card["front"] for card in cards] == ["Keep", "Valid"]
    assert list(page_cards(doc)) == cards
    assert len(_rows(render_anki_export(cards))) == 2


def test_guid_is_stable_across_exports():
    doc = _doc("Stable", [_flash_block("flash", [{"front": "Q", "back": "A"}])])
    first = render_anki_export(cards_from_document(doc))
    second = render_anki_export(cards_from_document(doc))
    assert _rows(first)[0][4] == _rows(second)[0][4]
    assert _rows(first)[0][4] == list(page_cards(doc))[0]["card_id"]


def test_tab_newline_and_html_are_escaped_inside_fields():
    html = markdown_to_anki_html("See <script>alert(1)</script> and a\tb\nline")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "\t" not in html
    assert "\n" not in html
    row = _rows(
        render_anki_export(
            [
                {
                    "front": "A\tB\nC",
                    "back": "<img src=x onerror=alert(1)>",
                    "page_title": "Safe",
                    "card_id": "guid-1",
                }
            ]
        )
    )[0]
    assert len(row) == 5
    assert "\t" not in "".join(row)
    assert "<img" not in row[1]
    assert "&lt;img" in row[1]


def test_latex_becomes_anki_mathjax_and_markdown_inline_is_html():
    html = markdown_to_anki_html("Energy **is** $E=mc^2$ and\n\n$$\\int x$$")
    assert r"\(E=mc^2\)" in html
    assert r"\[\int x\]" in html
    assert "$E=mc^2$" not in html
    assert "$$" not in html
    assert "<b>is</b>" in html
    assert html.startswith("<p>")
    code = markdown_to_anki_html("Use `$raw$` and ```\n$also$\n```")
    assert r"\(" not in code
    assert "<code>" in code
    italic = markdown_to_anki_html("say *this*")
    assert "<i>this</i>" in italic


def test_deck_title_sanitises_hierarchy_and_tags_slug_the_title():
    assert deck_name("Child::Name") == "DeepTutor::Child — Name"
    assert deck_name("") == "DeepTutor::Untitled"
    assert note_tags("Fourier Transform") == "deeptutor fourier-transform"
    assert note_tags("") == "deeptutor"
    assert note_tags("deeptutor") == "deeptutor"


def test_storage_export_covers_every_note_in_the_workspace(tmp_path):
    storage = CoWriterStorage(Paths(tmp_path))
    storage.create_document(
        title="Alpha",
        blocks=[_flash_block("a", [{"front": "From alpha", "back": "1"}])],
    )
    storage.create_document(
        title="Beta",
        blocks=[_flash_block("b", [{"front": "From beta", "back": "2"}])],
    )
    storage.create_document(title="Empty", blocks=[_flash_block("c", [])])
    cards = cards_from_storage(storage)
    fronts = {card["front"] for card in cards}
    assert fronts == {"From alpha", "From beta"}
    text = render_anki_export(cards)
    assert "DeepTutor::Alpha" in text
    assert "DeepTutor::Beta" in text


def test_protected_spans_do_not_nest_or_accept_user_placeholders():
    rendered = markdown_to_anki_html("$a `b` c$ and `code $literal$`")
    assert r"\(a `b` c\)" in rendered
    assert "<code>code $literal$</code>" in rendered
    assert "\x00" not in rendered
    assert "99" in markdown_to_anki_html("literal \x0099\x00")
    assert "<script>" not in markdown_to_anki_html("$<script>`x`</script>$")
