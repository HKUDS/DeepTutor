"""Pure store coverage for versioned web and knowledge-base reading sources."""

from pathlib import Path

import pytest

from deeptutor.reading import (
    Annotation,
    ReadingPosition,
    ReadingSourcePayload,
    ReadingStore,
    Rect,
)


@pytest.fixture
def store(tmp_path: Path) -> ReadingStore:
    return ReadingStore(root=tmp_path / "materials")


def payload(*units: str, captured_at: float = 1.0) -> ReadingSourcePayload:
    return ReadingSourcePayload(
        source_type="url_snapshot",
        source_ref="https://docs.example.com/tutorial",
        filename="tutorial.md",
        title="Tutorial",
        units=tuple(units),
        source_url="https://docs.example.com/tutorial",
        captured_at=captured_at,
    )


def test_stable_identity_idempotence_and_revision_history(store: ReadingStore) -> None:
    first = store.ingest_source(payload("Alpha", "Beta", captured_at=1))
    again = store.ingest_source(payload("Alpha", "Beta", captured_at=2))
    changed = store.ingest_source(payload("Alpha revised", "Beta", captured_at=3))

    assert again == first
    assert changed.material_id == first.material_id
    assert changed.revision_id != first.revision_id
    assert changed.previous_revision_id == first.revision_id
    assert {row.revision_id for row in store.revisions(first.material_id)} == {
        first.revision_id,
        changed.revision_id,
    }


def test_unique_quote_and_position_migrate_without_stale_geometry(
    store: ReadingStore,
) -> None:
    first = store.ingest_source(payload("One", "A unique portable quote"))
    saved = store.save_annotation(
        first.material_id,
        Annotation(
            annotation_id="",
            locator=2,
            quote="unique portable quote",
            rects=(Rect(0.1, 0.1, 0.4, 0.2),),
            source_anchor="old-native-anchor",
        ),
    )
    store.save_position(
        first.material_id,
        ReadingPosition(locator=2, source_anchor="old-position-anchor", percentage=0.7),
    )

    changed = store.ingest_source(
        payload("One revised", "Middle", "A unique portable quote moved")
    )

    migrated = store.annotations(changed.material_id)[0]
    assert migrated.annotation_id == saved.annotation_id
    assert migrated.locator == 3
    assert migrated.rects == ()
    assert migrated.source_anchor == ""
    assert migrated.revision_id == changed.revision_id
    assert migrated.migration_status == "migrated"
    position = store.position(changed.material_id)
    assert position.locator == 3
    assert position.percentage == 0.7
    assert position.source_anchor == ""


@pytest.mark.parametrize(
    "units",
    [("The quote disappeared",), ("same quote", "same quote again")],
)
def test_unreliable_annotation_migration_requires_review(
    store: ReadingStore,
    units: tuple[str, ...],
) -> None:
    first = store.ingest_source(payload("A same quote lives here"))
    store.save_annotation(
        first.material_id,
        Annotation(annotation_id="", locator=1, quote="same quote"),
    )

    changed = store.ingest_source(payload(*units))

    migrated = store.annotations(changed.material_id)[0]
    assert migrated.migration_status == "needs_review"
    assert migrated.revision_id == changed.revision_id


def test_revision_switch_restores_revision_state(store: ReadingStore) -> None:
    first = store.ingest_source(payload("First revision"))
    store.save_annotation(
        first.material_id,
        Annotation(annotation_id="", locator=1, quote="First revision", note="old"),
    )
    store.save_position(first.material_id, ReadingPosition(locator=1, percentage=0.25))
    second = store.ingest_source(payload("Second revision"))
    store.save_position(second.material_id, ReadingPosition(locator=1, percentage=0.75))

    active = store.switch_revision(second.material_id, first.revision_id)

    assert active.revision_id == first.revision_id
    assert store.unit_text(active.material_id, 1) == "First revision"
    assert store.annotations(active.material_id)[0].note == "old"
    assert store.position(active.material_id).percentage == 0.25


def test_kb_link_preserves_material_and_revision_ids(store: ReadingStore) -> None:
    first = store.ingest_source(payload("Keep my progress"))
    linked = store.link_source_to_kb(first.material_id, kb_name="user:kb:docs")

    assert linked.material_id == first.material_id
    assert linked.revision_id == first.revision_id
    assert linked.kb_name == "user:kb:docs"
