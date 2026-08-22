#!/usr/bin/env python3
"""Build an offline child-safe simple-English dictionary.

The Cambridge YLE list decides which words may appear. Definitions come from
Simple English Wiktionary, whose text is available under CC BY-SA 4.0. The
generated SQLite database is runtime data, not a git asset.
"""

from __future__ import annotations

import argparse
import bz2
from collections.abc import Iterable, Iterator, Sequence
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import io
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
from xml.etree import ElementTree

YLE_CSV_URL = "https://raw.githubusercontent.com/ozbonus/yle-vocabulary-dataset/main/yle-vocabulary-dataset.csv"
WIKTIONARY_DUMP_URL = (
    "https://dumps.wikimedia.org/simplewiktionary/latest/"
    "simplewiktionary-latest-pages-articles.xml.bz2"
)
WIKTIONARY_SOURCE_URL = "https://simple.wiktionary.org/"
LICENSE = "CC BY-SA 4.0"
USER_AGENT = "DeepTutor-kids-dictionary-builder/1.0"

_WORD_RE = re.compile(r"^[a-z]+(?:['-][a-z]+)?$")
_CONTEXT_RE = re.compile(r"\s*\([^)]*\)\s*$")
_PART_OF_SPEECH_RE = re.compile(r"^==\s*(Noun|Verb|Adjective|Adverb)\s*==$")
_DEFINITION_RE = re.compile(r"^#\s*(?:(?:\{\{[^{}]+\}\},?\s*)+)?(.+)$")
_IPA_RE = re.compile(r"\{\{IPA\|(/[^/|]+/)")
_WIKILINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_FORMAT_RE = re.compile(r"'''?|<[^>]+>")


@dataclass(frozen=True)
class SimpleDefinition:
    word: str
    definition: str
    part_of_speech: str
    phonetic: str = ""


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def load_yle_words(csv_text: str) -> list[str]:
    """Return one-word entries from the Cambridge YLE vocabulary list."""
    words: set[str] = set()
    for row in csv.DictReader(io.StringIO(csv_text)):
        for field in ("american", "british"):
            value = (row.get(field) or "").strip().lower()
            value = _CONTEXT_RE.sub("", value)
            if _WORD_RE.fullmatch(value):
                words.add(value)
    return sorted(words)


def _clean_wikitext(value: str) -> str:
    cleaned = _WIKILINK_RE.sub(r"\1", value)
    cleaned = _TEMPLATE_RE.sub("", cleaned)
    cleaned = _FORMAT_RE.sub("", cleaned)
    cleaned = cleaned.replace("[[", "").replace("]]", "").strip()
    return re.sub(r"\s+", " ", cleaned)


def _first_sentence(value: str) -> str:
    match = re.match(r"^(.+?[.!?])(?:\s|$)", value)
    return match.group(1) if match else value


def parse_simple_wiktionary_entry(word: str, wikitext: str) -> SimpleDefinition | None:
    """Extract the first readable definition from a Simple Wiktionary entry."""
    phonetic_match = _IPA_RE.search(wikitext)
    phonetic = phonetic_match.group(1).strip() if phonetic_match else ""
    part_of_speech = ""

    for raw_line in wikitext.splitlines():
        line = raw_line.strip()
        heading = _PART_OF_SPEECH_RE.fullmatch(line)
        if heading:
            part_of_speech = heading.group(1).lower()
            continue
        if line.startswith("="):
            part_of_speech = ""
            continue
        if not part_of_speech:
            continue

        definition_match = _DEFINITION_RE.match(line)
        if definition_match is None:
            continue
        definition = _first_sentence(_clean_wikitext(definition_match.group(1)))
        if not 20 <= len(definition) <= 160:
            continue
        if definition.startswith(("#", ":", "{{")) or "{{" in definition:
            continue
        if not re.match(r"^[A-Za-z]", definition) or not definition.endswith((".", "?")):
            continue
        return SimpleDefinition(
            word=word.lower(),
            definition=definition,
            part_of_speech=part_of_speech,
            phonetic=phonetic,
        )
    return None


def _iter_dump_entries(path: Path, wanted: set[str]) -> Iterator[tuple[str, str]]:
    namespace = "{http://www.mediawiki.org/xml/export-0.11/}"
    with bz2.open(path, "rb") as stream:
        for _, element in ElementTree.iterparse(stream, events=("end",)):
            if element.tag != f"{namespace}page":
                continue
            title_element = element.find(f"{namespace}title")
            text_element = element.find(f"./{namespace}revision/{namespace}text")
            if title_element is not None and text_element is not None:
                title = (title_element.text or "").strip().lower()
                if title in wanted and text_element.text:
                    yield title, text_element.text
            element.clear()


def build_definitions(
    dump_path: Path,
    yle_words: Iterable[str],
) -> tuple[list[SimpleDefinition], list[str]]:
    wanted = {word.lower() for word in yle_words}
    definitions: dict[str, SimpleDefinition] = {}

    for title, wikitext in _iter_dump_entries(dump_path, wanted):
        parsed = parse_simple_wiktionary_entry(title, wikitext)
        if parsed is not None:
            definitions[title] = parsed

    missing = [word for word in sorted(wanted) if word not in definitions]
    return sorted(definitions.values(), key=lambda item: item.word), missing


def write_database(
    output_path: Path,
    definitions: Sequence[SimpleDefinition],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with sqlite3.connect(temporary_path) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.executescript(
            """
            CREATE TABLE entries (
                word TEXT PRIMARY KEY,
                definition TEXT NOT NULL,
                part_of_speech TEXT NOT NULL,
                phonetic TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO entries(word, definition, part_of_speech, phonetic) VALUES (?, ?, ?, ?)",
            (
                (item.word, item.definition, item.part_of_speech, item.phonetic)
                for item in definitions
            ),
        )
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("schema_version", "1"),
                ("definition_source", "Simple English Wiktionary"),
                ("definition_source_url", WIKTIONARY_SOURCE_URL),
                ("vocabulary_source", "Cambridge YLE vocabulary list"),
                ("vocabulary_source_url", YLE_CSV_URL),
                ("license", LICENSE),
                ("generated_at", datetime.now(timezone.utc).isoformat()),
            ),
        )
        connection.commit()
    temporary_path.replace(output_path)


def _download_to_temporary(url: str) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="kids-dictionary-", delete=False)
    path = Path(handle.name)
    handle.close()
    try:
        path.write_bytes(_http_get(url))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def build(output: Path, *, dump_path: Path | None = None) -> tuple[int, list[str]]:
    yle_bytes = _http_get(YLE_CSV_URL)
    yle_words = load_yle_words(yle_bytes.decode("utf-8-sig"))
    temporary_dump: Path | None = None
    source_dump = dump_path
    if source_dump is None:
        temporary_dump = _download_to_temporary(WIKTIONARY_DUMP_URL)
        source_dump = temporary_dump

    try:
        definitions, missing = build_definitions(source_dump, yle_words)
        write_database(output, definitions)
    finally:
        if temporary_dump is not None:
            temporary_dump.unlink(missing_ok=True)
    return len(definitions), missing


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/user/workspace/immersive_reading/dictionaries/kids_simple.db"),
    )
    parser.add_argument(
        "--dump",
        type=Path,
        help="Use an already-downloaded MediaWiki XML .bz2 dump.",
    )
    args = parser.parse_args(argv)

    try:
        count, missing = build(args.output, dump_path=args.dump)
    except (
        OSError,
        urllib.error.URLError,
        ElementTree.ParseError,
        sqlite3.Error,
    ) as exc:
        print(f"Failed to build kids dictionary: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {count} entries to {args.output}")
    if missing:
        preview = ", ".join(missing[:30])
        suffix = "" if len(missing) <= 30 else ", ..."
        print(f"Skipped {len(missing)} YLE words without a usable definition: {preview}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
