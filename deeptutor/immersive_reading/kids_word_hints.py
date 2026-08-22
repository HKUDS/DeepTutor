"""Deterministic vocabulary hints for the child reading experience."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import sqlite3

from deeptutor.immersive_reading.sight_words import _get_dictionary
from deeptutor.services.path_service import get_path_service

_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?")
_POS_PREFIX_RE = re.compile(r"^(?:[a-z]{1,5}\.|[a-z]{1,5}\s+)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class KidsWordHint:
    word: str
    phonetic: str
    english_hint: str
    correct_choice: str
    chinese: str
    choices: tuple[str, ...]


def normalize_hint_word(raw_word: str) -> str:
    match = _WORD_RE.search(raw_word or "")
    return (match.group(0) if match else "").lower()


def _first_english_definition(value: str) -> str:
    for line in (value or "").splitlines():
        cleaned = _POS_PREFIX_RE.sub("", line.strip(" ;:"))
        if cleaned and not re.search(r"[\u4e00-\u9fff]", cleaned):
            return cleaned
    return ""


def _concise_chinese(value: str) -> str:
    first = next((line.strip() for line in (value or "").splitlines() if line.strip()), "")
    return _POS_PREFIX_RE.sub("", first).strip()


def _ecdict_lookup(word: str) -> tuple[str, str, str, str] | None:
    path = get_path_service().get_immersive_reading_dir() / "dictionaries" / "ecdict.db"
    if not path.is_file():
        return None
    candidates = [word]
    if word.endswith("s") and len(word) > 3:
        candidates.append(word[:-1])
    if word.endswith("ing") and len(word) > 5:
        candidates.extend((word[:-3], word[:-3] + "e"))
    if word.endswith("ed") and len(word) > 4:
        candidates.extend((word[:-2], word[:-1]))

    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            for candidate in candidates:
                row = connection.execute(
                    "SELECT word, phonetic, definition, translation FROM entries "
                    "WHERE word = ? LIMIT 1",
                    (candidate,),
                ).fetchone()
                if row is None:
                    continue
                definition = _first_english_definition(str(row["definition"] or ""))
                chinese = _concise_chinese(str(row["translation"] or ""))
                if definition and chinese:
                    return str(row["word"]), str(row["phonetic"] or ""), definition, chinese
    except sqlite3.Error:
        return None
    return None


def _stable_choices(word: str, correct: str, age_band: str) -> tuple[str, ...]:
    definitions = sorted(set(_get_dictionary(age_band).values()) - {correct})
    order = sorted(
        definitions,
        key=lambda value: hashlib.sha256(f"{word.lower()}:{value}".encode()).hexdigest(),
    )
    choices = [correct, order[0], order[1]]
    seed = hashlib.sha256(word.lower().encode()).digest()
    # A deterministic seed keeps the same word stable for a child without replay bias.
    for offset in range(1, len(choices)):
        index = (seed[offset % len(seed)] + offset) % len(choices)
        choices[offset], choices[index] = choices[index], choices[offset]
    return tuple(choices)


def build_kids_word_hint(raw_word: str, age_band: str = "6-8") -> KidsWordHint | None:
    word = normalize_hint_word(raw_word)
    if not word:
        return None

    age_definitions = _get_dictionary(age_band)
    english_hint = age_definitions.get(word, "")
    phonetic = ""
    chinese = ""
    if english_hint:
        # The child dictionary is English-first. Chinese is loaded lazily from ECDICT
        # so the API contract can keep it out of the first two learning stages.
        ec_entry = _ecdict_lookup(word)
        if ec_entry:
            _, phonetic, _, chinese = ec_entry
    else:
        ec_entry = _ecdict_lookup(word)
        if ec_entry is None:
            return None
        _, phonetic, english_hint, chinese = ec_entry

    if not chinese:
        return None
    choices = _stable_choices(word, english_hint, age_band)
    return KidsWordHint(
        word=word,
        phonetic=phonetic,
        english_hint=english_hint,
        correct_choice=english_hint,
        chinese=chinese,
        choices=choices,
    )
