from __future__ import annotations

from pathlib import Path

from deeptutor.immersive_reading.ecdict import ECDictionary


def _build_database(tmp_path: Path) -> Path:
    csv_path = tmp_path / "ecdict.csv"
    csv_path.write_text(
        "\n".join(
            [
                "word,phonetic,definition,translation,pos,exchange",
                'Technical,\'teknikl,"a. relating to a specialized subject","a. 技术的",a,',
                'long-time,,"for a long time","长期",,',
                'compute,,,v. to calculate,v,"d:computed/p:computed/i:computing/3:computes/4:computed"',
            ]
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "ecdict.db"
    assert ECDictionary.import_csv(csv_path, db_path) == 3
    return db_path


def test_ecdict_import_and_exact_lookup(tmp_path: Path) -> None:
    dictionary = ECDictionary(_build_database(tmp_path))

    entry = dictionary.lookup("TECHNICAL")

    assert entry is not None
    assert entry.word == "technical"
    assert entry.translation == "a. 技术的"


def test_ecdict_matches_normalized_spelling(tmp_path: Path) -> None:
    dictionary = ECDictionary(_build_database(tmp_path))

    entry = dictionary.lookup("long time")

    assert entry is not None
    assert entry.word == "long-time"


def test_ecdict_resolves_common_inflections(tmp_path: Path) -> None:
    dictionary = ECDictionary(_build_database(tmp_path))

    for inflection in ("computes", "computed", "computing"):
        entry = dictionary.lookup(inflection)
        assert entry is not None
        assert entry.word == "compute"
        assert entry.translation == "v. to calculate"
