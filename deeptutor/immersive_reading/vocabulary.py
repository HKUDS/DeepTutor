"""Vocabulary card generation, review scheduling, export, and difficulty analysis."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import sqlite3
import time
import zipfile
from collections import Counter
from typing import Iterable, Literal

from deeptutor.immersive_reading.ecdict import ECDictionary
from deeptutor.immersive_reading.models import (
    ChapterVocabularyPreview,
    VocabEntry,
    VocabularyCard,
    VocabularyDifficultyWord,
)

REVIEW_INTERVALS_DAYS = (0, 1, 3, 7, 14, 30, 60)
WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?")
STOP_WORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does for from had has have
    he her hers him his how i if in into is it its me my not of on or our ours out said
    she should so some than that the their them then there these they this those through
    to too up us was we were what when where which while who whom why will with would you your
    """.split()
)


def definition_text(entry: VocabEntry) -> str:
    first = entry.definitions[0] if entry.definitions else None
    if first:
        prefix = f"{first.part_of_speech} " if first.part_of_speech else ""
        return f"{prefix}{first.definition}".strip()
    return entry.chinese or entry.context_note


def cloze_sentence(sentence: str, word: str) -> str:
    """Replace the first whole-word occurrence without changing source casing."""
    pattern = rf"(?i)(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])"
    replaced, count = re.subn(pattern, "____", sentence, count=1)
    return replaced if count else f"____ {sentence}"


def _distractors(entries: Iterable[VocabEntry], answer: str, limit: int = 3) -> list[str]:
    candidates = [
        entry.word
        for entry in entries
        if entry.word.casefold() != answer.casefold()
    ]
    candidates.sort(key=lambda word: (-len(word), word.casefold()))
    unique: list[str] = []
    seen: set[str] = set()
    for word in candidates:
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(word)
        if len(unique) >= limit:
            break
    return unique


def ensure_cards(entry: VocabEntry, all_entries: Iterable[VocabEntry]) -> VocabEntry:
    """Create or refresh the cloze and choice cards for one vocabulary entry."""
    context_en = entry.context_en.strip()
    context_zh = entry.context_zh.strip()
    front = cloze_sentence(context_en, entry.word) if context_en else entry.word
    choices = [entry.word, *_distractors(all_entries, entry.word)]
    now = time.time()
    cards = [
        VocabularyCard(
            id=f"{entry.id}:cloze",
            card_type="cloze",
            front=front,
            back=entry.word,
            context_en=context_en,
            context_zh=context_zh,
            choices=[],
            answer=entry.word,
            created_at=entry.cards[0].created_at if entry.cards else now,
            updated_at=now,
        ),
        VocabularyCard(
            id=f"{entry.id}:choice",
            card_type="choice",
            front=front,
            back=entry.word,
            context_en=context_en,
            context_zh=context_zh,
            choices=choices,
            answer=entry.word,
            created_at=entry.cards[1].created_at if len(entry.cards) > 1 else now,
            updated_at=now,
        ),
    ]
    return entry.model_copy(update={"cards": cards})


def review_queue(
    entries: Iterable[VocabEntry], *, limit: int = 10, now: float | None = None
) -> list[VocabEntry]:
    current = time.time() if now is None else now
    due = [entry for entry in entries if entry.review.due_at <= current]
    # Due age comes first, then high-frequency words, then least-reviewed words.
    due.sort(
        key=lambda entry: (
            entry.review.due_at,
            -entry.occurrence_count,
            entry.review.review_count,
            entry.word.casefold(),
        )
    )
    return due[: max(0, limit)]


def grade_review(
    entries: Iterable[VocabEntry], entry_id: str, *, correct: bool, now: float | None = None
) -> tuple[list[VocabEntry], VocabEntry]:
    current = time.time() if now is None else now
    updated: list[VocabEntry] = []
    result: VocabEntry | None = None
    for entry in entries:
        if entry.id != entry_id:
            updated.append(entry)
            continue
        state = entry.review.model_copy(deep=True)
        state.review_count += 1
        if correct:
            state.correct_count += 1
            state.consecutive_correct += 1
            state.interval_index = min(
                len(REVIEW_INTERVALS_DAYS) - 1, state.interval_index + 1
            )
            state.last_result = "correct"
            state.due_at = current + REVIEW_INTERVALS_DAYS[state.interval_index] * 86400
        else:
            state.wrong_count += 1
            state.consecutive_correct = 0
            state.interval_index = max(0, state.interval_index - 1)
            state.last_result = "wrong"
            # A miss returns tomorrow, preventing one hard word from consuming the whole day.
            state.due_at = current + 86400
        state.last_reviewed_at = current
        result = entry.model_copy(update={"review": state})
        updated.append(result)
    if result is None:
        raise ValueError("Vocabulary entry not found")
    return updated, result


def _csv_row(entry: VocabEntry) -> list[str]:
    return [
        entry.word,
        entry.phonetic,
        entry.context_en,
        entry.context_zh,
        definition_text(entry),
        entry.chinese,
        entry.context_note,
        entry.document_title or entry.pairing_id or "Immersive Reading",
        entry.section_title,
        str(entry.occurrence_count),
    ]


def vocabulary_csv(entries: Iterable[VocabEntry]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "Word",
            "Phonetic",
            "Original Sentence",
            "Chinese Translation",
            "English Definition",
            "Chinese Definition",
            "Context Note",
            "Source",
            "Section",
            "Occurrences",
        ]
    )
    for entry in entries:
        writer.writerow(_csv_row(entry))
    return buffer.getvalue().encode("utf-8")


def _anki_guid(entry_id: str) -> str:
    # Anki accepts opaque text GUIDs; a truncated digest keeps repeated exports stable.
    return hashlib.sha256(f"deeptutor-vocabulary:{entry_id}".encode("utf-8")).hexdigest()[:16]


def _field(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


def _collection_anki2(entries: list[VocabEntry], deck_name: str, model_id: int, deck_id: int) -> bytes:
    now = int(time.time())
    field_names = [
        "Word",
        "Phonetic",
        "Cloze Sentence",
        "Original Sentence",
        "Chinese Translation",
        "English Definition",
        "Chinese Definition",
        "Choices",
        "Source",
    ]
    templates = [
        {
            "name": "Context Cloze",
            "ord": 0,
            "qfmt": "{{Cloze Sentence}}<br><span class='zh'>{{Chinese Translation}}</span>",
            "afmt": "{{FrontSide}}<hr id=answer><b>{{Word}}</b> {{Phonetic}}<br>{{English Definition}}<br>{{Chinese Definition}}<br><small>{{Source}}</small>",
            "bqfmt": "",
            "bafmt": "",
            "did": None,
        },
        {
            "name": "Context Choice",
            "ord": 1,
            "qfmt": "{{Cloze Sentence}}<br>{{Choices}}<br><small>Which word fits the blank?</small>",
            "afmt": "{{FrontSide}}<hr id=answer><b>{{Word}}</b> {{Phonetic}}<br>{{English Definition}}<br>{{Chinese Definition}}<br><small>{{Source}}</small>",
            "bqfmt": "",
            "bafmt": "",
            "did": None,
        },
    ]
    model = {
        "id": model_id,
        "name": "DeepTutor Vocabulary",
        "type": 0,
        "mod": now,
        "usn": 0,
        "sortf": 0,
        "did": deck_id,
        "tmpls": templates,
        "flds": [{"name": name, "ord": index, "sticky": False, "rtl": False, "font": "Arial", "size": 20} for index, name in enumerate(field_names)],
        "css": ".card{font-family:system-ui,sans-serif;font-size:20px;line-height:1.5;color:#222}.zh{color:#555}.cloze{font-weight:700}small{color:#777}",
        "latexPre": "\\begin{document}\n",
        "latexPost": "\\end{document}\n",
        "req": [[0, "any", [0]], [1, "any", [0]]],
        "tags": [],
        "vers": [],
    }
    decks = {
        "1": {
            "id": 1,
            "name": "Default",
            "mod": now,
            "usn": 0,
            "lrnToday": [0, 0],
            "revToday": [0, 0],
            "newToday": [0, 0],
            "timeToday": [0, 0],
            "collapsed": False,
            "browserCollapsed": False,
            "desc": "",
            "conf": 1,
            "extendNew": 10,
            "extendRev": 50,
        },
        str(deck_id): {
            "id": deck_id,
            "name": deck_name,
            "mod": now,
            "usn": 0,
            "lrnToday": [0, 0],
            "revToday": [0, 0],
            "newToday": [0, 0],
            "timeToday": [0, 0],
            "collapsed": False,
            "browserCollapsed": False,
            "desc": "Exported from DeepTutor Immersive Reading",
            "conf": 1,
            "extendNew": 10,
            "extendRev": 50,
        },
    }
    conf = {
        "activeDecks": [deck_id],
        "curDeck": deck_id,
        "newSpread": 0,
        "collapseTime": 1200,
        "timeZone": "",
        "estTimes": True,
        "dueCounts": True,
        "curModel": str(model_id),
        "nextPos": 1,
        "sortBackwards": False,
        "dayLearnFirst": False,
    }
    dconf = {
        "1": {
            "id": 1,
            "name": "Default",
            "replayq": True,
            "lapse": {"delays": [10], "mult": 0, "minInt": 1, "leechFails": 8, "leechAction": 0},
            "rev": {"perDay": 200, "fuzz": 0.05, "ivlFct": 1, "maxIvl": 36500, "ease4": 1.3, "bury": True, "minSpace": 1},
            "timer": 0,
            "maxTaken": 60,
            "usn": 0,
            "new": {"perDay": 20, "delays": [1, 10], "separate": True, "ints": [1, 4, 7], "initialFactor": 2500, "bury": True, "order": 1},
            "mod": now,
            "autoplay": True,
        }
    }

    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE col (
          id integer primary key, crt integer not null, mod integer not null,
          scm integer not null, ver integer not null, dty integer not null,
          usn integer not null, ls integer not null, conf text not null,
          models text not null, decks text not null, dconf text not null,
          tags text not null
        );
        CREATE TABLE notes (
          id integer primary key, guid text not null, mid integer not null,
          mod integer not null, usn integer not null, tags text not null,
          flds text not null, sfld integer not null, csum integer not null,
          flags integer not null, data text not null
        );
        CREATE TABLE cards (
          id integer primary key, nid integer not null, did integer not null,
          usn integer not null, ord integer not null, type integer not null, queue integer not null,
          due integer not null, ivl integer not null, factor integer not null,
          reps integer not null, lapses integer not null, left integer not null,
          odue integer not null, odid integer not null, flags integer not null,
          data text not null
        );
        CREATE TABLE revlog (
          id integer primary key, cid integer not null, usn integer not null,
          ease integer not null, ivl integer not null, lastIvl integer not null,
          factor integer not null, time integer not null, type integer not null
        );
        CREATE INDEX ix_notes_usn on notes (usn);
        CREATE INDEX ix_cards_usn on cards (usn);
        CREATE INDEX ix_cards_nid on cards (nid);
        CREATE INDEX ix_cards_sched on cards (did, queue, due);
        CREATE INDEX ix_revlog_usn on revlog (usn);
        CREATE INDEX ix_revlog_cid on revlog (cid);
        """
    )
    connection.execute(
        "INSERT INTO col VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            now,
            now,
            now,
            11,
            0,
            0,
            0,
            json.dumps(conf, separators=(",", ":")),
            json.dumps({str(model_id): model}, separators=(",", ":")),
            json.dumps(decks, separators=(",", ":")),
            json.dumps(dconf, separators=(",", ":")),
            "{}",
        ),
    )
    for index, entry in enumerate(entries, start=1):
        fields = [
            entry.word,
            entry.phonetic,
            cloze_sentence(entry.context_en, entry.word) if entry.context_en else entry.word,
            entry.context_en,
            entry.context_zh,
            definition_text(entry),
            entry.chinese,
            "<ul>" + "".join(f"<li>{_field(choice)}</li>" for choice in entry.cards[1].choices if choice != entry.word) + "</ul>" if len(entry.cards) > 1 else "",
            f"{entry.document_title} · {entry.section_title}" if entry.document_title or entry.section_title else "Immersive Reading",
        ]
        flds = "\x1f".join(_field(value) for value in fields)
        note_id = 1_700_000_000_000 + index
        checksum = int(hashlib.sha1(entry.word.encode("utf-8")).hexdigest()[:8], 16)
        connection.execute(
            "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (note_id, _anki_guid(entry.id), model_id, now, 0, " deeptutor vocabulary ", flds, 0, checksum, 0, ""),
        )
        for ordinal in (0, 1):
            connection.execute(
                "INSERT INTO cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (note_id * 10 + ordinal, note_id, deck_id, 0, ordinal, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ""),
            )
    connection.commit()
    database = connection.serialize()
    connection.close()
    return bytes(database)


def vocabulary_apkg(entries: Iterable[VocabEntry], deck_name: str = "DeepTutor Vocabulary") -> bytes:
    materialized = list(entries)
    if not materialized:
        raise ValueError("No vocabulary entries to export")
    digest = hashlib.sha1(deck_name.encode("utf-8")).hexdigest()
    model_id = int(digest[:8], 16) % 900_000_000 + 100_000_000
    deck_id = int(digest[8:16], 16) % 900_000_000 + 100_000_000
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "collection.anki2", _collection_anki2(materialized, deck_name, model_id, deck_id)
        )
        archive.writestr("media", "{}")
    return package.getvalue()


def _frequency_band(rank: int, oxford: int) -> Literal["core", "common", "advanced", "low", "unknown"]:
    if oxford == 1 or (rank > 0 and rank <= 3000):
        return "core"
    if 0 < rank <= 5000:
        return "common"
    if 0 < rank <= 15000:
        return "advanced"
    if 0 < rank <= 30000:
        return "low"
    return "unknown"


def chapter_difficulty(
    content: str, dictionary: ECDictionary, *, saved_words: Iterable[str] = (), limit: int = 80
) -> ChapterVocabularyPreview:
    try:
        available = dictionary.frequency_columns_available
        reason = "" if available else "ECDICT frequency fields are unavailable; reimport an ECDICT CSV with frq and oxford columns."
    except FileNotFoundError:
        return ChapterVocabularyPreview(
            available=False,
            reason="Local ECDICT database is not installed.",
            words=[],
            distribution={},
        )

    saved = {word.strip().casefold() for word in saved_words if word.strip()}
    counts: Counter[str] = Counter(word.casefold() for word in WORD_RE.findall(content))
    rows: list[VocabularyDifficultyWord] = []
    distribution: dict[str, int] = {}
    for word, count in counts.items():
        if word in STOP_WORDS:
            continue
        entry = dictionary.lookup(word)
        lemma = entry.word.casefold() if entry and entry.word else word
        rank = entry.frq if entry else 0
        oxford = bool(entry and entry.oxford == 1)
        band = _frequency_band(rank, int(oxford))
        distribution[band] = distribution.get(band, 0) + 1
        is_difficult = band in {"advanced", "low", "unknown"}
        if not is_difficult and lemma not in saved:
            continue
        rows.append(
            VocabularyDifficultyWord(
                word=word,
                lemma=lemma,
                count=count,
                frequency_rank=rank if rank > 0 else None,
                oxford=oxford,
                band=band,
                phonetic=entry.phonetic if entry else "",
                definition=entry.definition.splitlines()[0] if entry and entry.definition else "",
                chinese=entry.translation if entry else "",
            )
        )
    rows.sort(
        key=lambda item: (
            {"unknown": 0, "low": 1, "advanced": 2, "common": 3, "core": 4}[item.band],
            -item.count,
            item.frequency_rank if item.frequency_rank is not None else 10**9,
            item.word,
        )
    )
    return ChapterVocabularyPreview(
        available=available,
        reason=reason,
        words=rows[: max(0, limit)],
        distribution=distribution,
    )


__all__ = [
    "REVIEW_INTERVALS_DAYS",
    "chapter_difficulty",
    "cloze_sentence",
    "definition_text",
    "ensure_cards",
    "grade_review",
    "review_queue",
    "vocabulary_apkg",
    "vocabulary_csv",
]
