import sqlite3

from deeptutor.immersive_reading import kids_word_hints
from deeptutor.immersive_reading.kids_word_hints import (
    _kids_simple_lookup,
    build_kids_word_hint,
)
from scripts.build_kids_dictionary import load_yle_words, parse_simple_wiktionary_entry


class _FakePathService:
    def __init__(self, root):
        self.root = root

    def get_immersive_reading_dir(self):
        return self.root


def _write_dictionary_fixtures(tmp_path):
    dictionary_dir = tmp_path / "dictionaries"
    dictionary_dir.mkdir()
    with sqlite3.connect(dictionary_dir / "kids_simple.db") as connection:
        connection.executescript(
            """
            CREATE TABLE entries (
                word TEXT PRIMARY KEY,
                definition TEXT NOT NULL,
                part_of_speech TEXT NOT NULL,
                phonetic TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO entries VALUES
                ('picture', 'A picture is a drawing or a photo.', 'noun', '/ˈpɪktʃɚ/');
            """
        )
    with sqlite3.connect(dictionary_dir / "ecdict.db") as connection:
        connection.executescript(
            """
            CREATE TABLE entries (
                word TEXT PRIMARY KEY,
                sw TEXT NOT NULL,
                phonetic TEXT NOT NULL,
                definition TEXT NOT NULL,
                translation TEXT NOT NULL,
                pos TEXT NOT NULL,
                exchange TEXT NOT NULL
            );
            INSERT INTO entries VALUES
                ('picture', 'picture', "'piktʃә", 'n. an adult multi-line definition', 'n. 图画, 照片', 'n.', ''),
                ('sepulchral', 'sepulchral', '', 'a. very sad and serious', 'a. 阴沉的', 'a.', '');
            """
        )
    return dictionary_dir


def test_simple_wiktionary_parser_extracts_child_readable_definition():
    parsed = parse_simple_wiktionary_entry(
        "picture",
        """
=== Pronunciation ===
* {{US}} {{IPA|/ˈpɪktʃɚ/}}

== Noun ==
{{noun}}
# {{countable}} A '''picture''' is [[mark]]s on a [[flat]] object, like [[paper]], that show [[shape]]s, people, or things.
#: ''Mommy, I drew a picture of a cat.''
""",
    )

    assert parsed is not None
    assert parsed.definition == (
        "A picture is marks on a flat object, like paper, that show shapes, people, or things."
    )
    assert parsed.part_of_speech == "noun"
    assert parsed.phonetic == "/ˈpɪktʃɚ/"


def test_yle_loader_keeps_single_words_and_removes_context():
    words = load_yle_words(
        "british,american,irregular_plural\n"
        "picture,picture,\n"
        "bat (sports),bat (sports),\n"
        "board game,board game,\n"
    )

    assert "picture" in words
    assert "bat" in words
    assert "board" not in words
    assert "board game" not in words


def test_pictures_uses_child_definition_and_normalizes_lookup(tmp_path, monkeypatch):
    root = _write_dictionary_fixtures(tmp_path)
    monkeypatch.setattr(
        kids_word_hints,
        "get_path_service",
        lambda: _FakePathService(root.parent),
    )

    simple_entry = _kids_simple_lookup("pictures")
    assert simple_entry is not None
    assert simple_entry.word == "picture"

    hint = build_kids_word_hint("pictures")
    assert hint is not None
    assert hint.word == "pictures"
    assert hint.correct_choice == "a drawing, a photo, or an image"
    assert hint.chinese == "图画，照片，图像"
    assert "visual representation" not in hint.correct_choice
    assert hint.english_hint.startswith("Think about drawings")
    assert len(hint.choices) == 3


def test_adult_ecdict_definition_alone_is_not_a_child_hint(tmp_path, monkeypatch):
    root = _write_dictionary_fixtures(tmp_path)
    monkeypatch.setattr(
        kids_word_hints,
        "get_path_service",
        lambda: _FakePathService(root.parent),
    )

    assert build_kids_word_hint("sepulchral") is None
