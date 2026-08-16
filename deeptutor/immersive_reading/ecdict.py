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
    frq: int = 0
    oxford: int = 0


def normalize_word(word: str) -> str:
    return word.strip().casefold()


def strip_word(word: str) -> str:
    return _NON_ALNUM.sub("", normalize_word(word))


class ECDictionary:
    """Read-only ECDICT facade with exact, normalized, and inflected lookup."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._connection: sqlite3.Connection | None = None
        self._frequency_columns_available: bool | None = None

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
            frq=int(row["frq"] or 0),
            oxford=int(row["oxford"] or 0),
        )

    @property
    def frequency_columns_available(self) -> bool:
        if self._frequency_columns_available is None:
            columns = {
                str(row["name"])
                for row in self._connect().execute("PRAGMA table_info(entries)")
            }
            self._frequency_columns_available = {"frq", "oxford"}.issubset(columns)
        return self._frequency_columns_available

    @staticmethod
    def _morphological_candidates(word: str) -> list[str]:
        """Generate common base-form candidates for an English inflection."""
        normalized = normalize_word(word)
        candidates: list[str] = []

        if normalized.endswith("'s") or normalized.endswith("’s"):
            candidates.append(normalized[:-2])
        if normalized.endswith("ies") and len(normalized) > 4:
            candidates.append(normalized[:-3] + "y")
        if normalized.endswith("ves") and len(normalized) > 4:
            candidates.append(normalized[:-3] + "f")
            candidates.append(normalized[:-3] + "fe")
        for suffix in ("es", "s", "ed", "ing", "er", "est"):
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 2:
                candidates.append(normalized[: -len(suffix)])
        if normalized.endswith("ed") and len(normalized) > 4:
            candidates.append(normalized[:-2] + "e")
        if normalized.endswith("ing") and len(normalized) > 5:
            candidates.append(normalized[:-3] + "e")
        if normalized.endswith("ied") and len(normalized) > 4:
            candidates.append(normalized[:-3] + "y")
        if len(normalized) > 3 and normalized[-1] == normalized[-2]:
            candidates.append(normalized[:-1])

        return list(dict.fromkeys(candidate for candidate in candidates if candidate))

    @staticmethod
    def _exchange_words(entry: ECDictEntry) -> list[str]:
        """Extract explicit base/inflected forms from ECDICT's exchange field."""
        candidates: list[str] = []
        for item in entry.exchange.split("/"):
            _, separator, value = item.partition(":")
            if separator and value:
                candidates.extend(candidate for candidate in value.split("/") if candidate)
        return list(dict.fromkeys(candidates))

    def _lookup_exact(self, connection: sqlite3.Connection, word: str) -> ECDictEntry | None:
        frequency_columns = (
            "frq, oxford" if self.frequency_columns_available else "0 AS frq, 0 AS oxford"
        )
        row = connection.execute(
            f"SELECT word, phonetic, definition, translation, pos, exchange, {frequency_columns} "
            "FROM entries WHERE word = ? LIMIT 1",
            (word,),
        ).fetchone()
        return self._entry(row) if row is not None else None

    def lookup(self, word: str) -> ECDictEntry | None:
        """Look up a word, including common spelling and punctuation variants."""
        normalized = normalize_word(word)
        if not normalized:
            return None

        connection = self._connect()
        exact = self._lookup_exact(connection, normalized)
        if exact is not None:
            entry = exact
            if entry.definition or entry.translation:
                return entry
            for exchange_word in self._exchange_words(entry):
                exchanged = self._lookup_exact(connection, exchange_word)
                if exchanged is not None and (exchanged.definition or exchanged.translation):
                    return exchanged
            return entry

        for candidate in self._morphological_candidates(normalized):
            entry = self._lookup_exact(connection, candidate)
            if entry is not None:
                return entry

        stripped = strip_word(word)
        if not stripped or stripped == normalized:
            return None
        frequency_columns = (
            "frq, oxford" if self.frequency_columns_available else "0 AS frq, 0 AS oxford"
        )
        row = connection.execute(
            f"SELECT word, phonetic, definition, translation, pos, exchange, {frequency_columns} "
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
                    exchange TEXT NOT NULL,
                    frq INTEGER NOT NULL DEFAULT 0,
                    oxford INTEGER NOT NULL DEFAULT 0
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
                        max(0, int(float(row.get("frq") or 0))),
                        1 if str(row.get("oxford") or "").strip() == "1" else 0,
                    )
                    for row in reader
                )
                connection.executemany(
                    "INSERT OR IGNORE INTO entries "
                    "(word, sw, phonetic, definition, translation, pos, exchange, frq, oxford) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
