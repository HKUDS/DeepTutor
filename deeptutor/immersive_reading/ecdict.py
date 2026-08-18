"""Fast local English/Chinese lookup backed by an ECDICT SQLite database."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ECDictEntry:
    word: str
    phonetic: str
    definition: str
    translation: str
    pos: str
    exchange: str


def normalize_word(word: str) -> str:
    return word.strip().casefold()


def strip_word(word: str) -> str:
    return _NON_ALNUM.sub("", normalize_word(word))


class ECDictionary:
    """Read-only ECDICT facade with exact, normalized, and inflected lookup."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._connection: sqlite3.Connection | None = None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"ECDICT database not found: {self.db_path}")
        if self._connection is None:
            self._connection = sqlite3.connect(
                f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
        return self._connection

    @staticmethod
    def _entry(row: sqlite3.Row) -> ECDictEntry:
        return ECDictEntry(
            word=str(row["word"] or ""),
            phonetic=str(row["phonetic"] or ""),
            definition=str(row["definition"] or ""),
            translation=str(row["translation"] or ""),
            pos=str(row["pos"] or ""),
            exchange=str(row["exchange"] or ""),
        )

    def lookup(self, word: str) -> ECDictEntry | None:
        """Look up a word, including common spelling and punctuation variants."""
        normalized = normalize_word(word)
        if not normalized:
            return None

        connection = self._connect()
        row = connection.execute(
            "SELECT word, phonetic, definition, translation, pos, exchange "
            "FROM entries WHERE word = ? LIMIT 1",
            (normalized,),
        ).fetchone()
        if row is not None:
            return self._entry(row)

        stripped = strip_word(word)
        if not stripped or stripped == normalized:
            return None
        row = connection.execute(
            "SELECT word, phonetic, definition, translation, pos, exchange "
            "FROM entries WHERE sw = ? ORDER BY length(word), word LIMIT 1",
            (stripped,),
        ).fetchone()
        return self._entry(row) if row is not None else None

    @classmethod
    def import_csv(cls, csv_path: str | Path, db_path: str | Path) -> int:
        """Build the compact runtime database from an ECDICT CSV export."""
        source = Path(csv_path)
        target = Path(db_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.unlink(missing_ok=True)

        connection = sqlite3.connect(temporary)
        count = 0
        try:
            connection.executescript(
                """
                PRAGMA journal_mode = OFF;
                PRAGMA synchronous = OFF;
                CREATE TABLE entries (
                    word TEXT PRIMARY KEY,
                    sw TEXT NOT NULL,
                    phonetic TEXT NOT NULL,
                    definition TEXT NOT NULL,
                    translation TEXT NOT NULL,
                    pos TEXT NOT NULL,
                    exchange TEXT NOT NULL
                );
                CREATE INDEX idx_entries_sw ON entries(sw);
                """
            )
            with source.open("r", encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                rows = (
                    (
                        (row.get("word") or "").strip().casefold(),
                        strip_word(row.get("word") or ""),
                        (row.get("phonetic") or "").strip(),
                        (row.get("definition") or "").strip(),
                        (row.get("translation") or "").strip(),
                        (row.get("pos") or "").strip(),
                        (row.get("exchange") or "").strip(),
                    )
                    for row in reader
                )
                connection.executemany(
                    "INSERT OR IGNORE INTO entries "
                    "(word, sw, phonetic, definition, translation, pos, exchange) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            connection.commit()
            count = connection.execute("SELECT count(*) FROM entries").fetchone()[0]
            connection.execute("PRAGMA optimize")
        except Exception:
            connection.close()
            temporary.unlink(missing_ok=True)
            raise
        else:
            connection.close()
            temporary.replace(target)
        return count


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("db_path", type=Path)
    args = parser.parse_args()
    count = ECDictionary.import_csv(args.csv_path, args.db_path)
    print(json.dumps({"entries": count, "database": str(args.db_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
