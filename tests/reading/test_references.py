from __future__ import annotations

from pathlib import Path

from deeptutor.reading.references import (
    MAX_READING_REFERENCE_UNITS,
    normalize_reading_references,
    resolve_reading_sources,
)
from deeptutor.reading.store import ReadingStore


def test_reference_normalization_rejects_paths_and_deduplicates_locators() -> None:
    assert normalize_reading_references(
        [
            {"material_id": "../../etc", "revision": 1, "locators": [1]},
            {
                "material_id": "ABCDEF0123456789",
                "revision": 2,
                "locators": [2, 2, "3", 0, True, 1.5],
            },
            {"material_id": "abcdef0123456789", "revision": 2, "locators": [4]},
        ]
    ) == [{"material_id": "abcdef0123456789", "revision": 2, "locators": [2, 3, 4]}]


def test_reference_normalization_bounds_the_total_unit_count() -> None:
    refs = normalize_reading_references(
        [
            {
                "material_id": "abcdef0123456789",
                "revision": 1,
                "locators": list(range(1, 100)),
            }
        ]
    )

    assert len(refs[0]["locators"]) == MAX_READING_REFERENCE_UNITS


def test_empty_rows_do_not_consume_the_material_limit() -> None:
    empty_rows = [
        {"material_id": f"{index:016x}", "revision": 1, "locators": []} for index in range(20)
    ]

    assert normalize_reading_references(
        [
            *empty_rows,
            {"material_id": "abcdef0123456789", "revision": 1, "locators": [1]},
        ]
    ) == [{"material_id": "abcdef0123456789", "revision": 1, "locators": [1]}]


def test_references_resolve_from_the_store_not_client_text(tmp_path: Path) -> None:
    source = tmp_path / "chapter.txt"
    source.write_text("# Opening\n\nTrusted source text.", encoding="utf-8")
    store = ReadingStore(tmp_path / "reading")
    manifest = store.ingest(source)

    resolved = resolve_reading_sources(
        [
            {
                "material_id": manifest.material_id,
                "revision": manifest.revision,
                "locators": [1, 99],
                "text": "client-supplied text must be ignored",
            }
        ],
        store=store,
    )

    assert len(resolved) == 1
    assert resolved[0].source_id == f"rd-{manifest.material_id}-r{manifest.revision}-1"
    assert "Trusted source text." in resolved[0].full_text
    assert "client-supplied" not in resolved[0].full_text
    assert manifest.filename in resolved[0].full_text


def test_missing_materials_are_safely_ignored(tmp_path: Path) -> None:
    assert (
        resolve_reading_sources(
            [{"material_id": "abcdef0123456789", "revision": 1, "locators": [1]}],
            store=ReadingStore(tmp_path / "reading"),
        )
        == []
    )


def test_references_resolve_the_persisted_revision_not_current_content(tmp_path: Path) -> None:
    store = ReadingStore(tmp_path / "reading")
    material_id = "abcdef0123456789"
    first = store.ingest_units(
        material_id,
        filename="snapshot.md",
        units=["Original revision text."],
        source_type="url_snapshot",
    )
    second = store.ingest_units(
        material_id,
        filename="snapshot.md",
        units=["Replacement revision text."],
        source_type="url_snapshot",
    )

    resolved = resolve_reading_sources(
        [{"material_id": material_id, "revision": first.revision, "locators": [1]}],
        store=store,
    )

    assert second.revision == first.revision + 1
    assert len(resolved) == 1
    assert "Original revision text." in resolved[0].full_text
    assert "Replacement revision text." not in resolved[0].full_text


def test_references_fail_closed_without_a_content_revision() -> None:
    assert (
        normalize_reading_references([{"material_id": "abcdef0123456789", "locators": [1]}]) == []
    )
