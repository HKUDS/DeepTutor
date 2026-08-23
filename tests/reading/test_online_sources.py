"""Pure store coverage for versioned web and knowledge-base reading sources."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from deeptutor.reading import (
    Annotation,
    OutlineEntry,
    ReadingPosition,
    ReadingSourcePayload,
    ReadingStore,
    Rect,
    localize_snapshot_images,
    markdown_payload,
    sanitize_snapshot_markdown,
)


@pytest.fixture
def store(tmp_path: Path) -> ReadingStore:
    return ReadingStore(root=tmp_path / "materials")


def payload(
    *units: str,
    captured_at: float = 1.0,
    outline: tuple[OutlineEntry, ...] = (),
) -> ReadingSourcePayload:
    return ReadingSourcePayload(
        source_type="url_snapshot",
        source_ref="https://docs.example.com/tutorial",
        filename="tutorial.md",
        title="Tutorial",
        units=tuple(units),
        outline=outline,
        source_url="https://docs.example.com/tutorial",
        captured_at=captured_at,
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "<!-- source: https://docs.example.com/ -->\n\n",
        r"\<!-- source: https://docs.example.com/ \-->" + "\n\n",
    ],
)
def test_snapshot_source_comment_is_removed_only_from_document_start(prefix: str) -> None:
    markdown = prefix + "# Documentation\n\nBody\n\n<!-- source: keep in prose -->"
    clean = sanitize_snapshot_markdown(markdown)

    assert clean.startswith("# Documentation")
    assert "keep in prose" in clean
    source = markdown_payload(
        source_type="url_snapshot",
        source_ref="https://docs.example.com/",
        title="Documentation",
        markdown=markdown,
        filename="index.md",
    )
    assert source.content_format == "markdown"
    assert not source.units[0].startswith("<!-- source:")


@pytest.mark.asyncio
async def test_snapshot_images_are_cached_and_rewritten_to_local_authenticated_paths(
    store: ReadingStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.web_source import crawler

    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda _host: False)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://docs.example.com/images/figure.png"
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"PNG-safe-bytes",
            request=request,
        )

    source = markdown_payload(
        source_type="url_snapshot",
        source_ref="https://docs.example.com/guide/",
        title="Guide",
        markdown="![Figure](../images/figure.png)",
        filename="guide.md",
        source_url="https://docs.example.com/guide/",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        localized = await localize_snapshot_images(source, client=client)
    manifest = store.ingest_source(localized)

    assert "docs.example.com" not in store.unit_text(manifest.material_id, 1)
    assert "/api/v1/reading/snapshot-assets/" in store.unit_text(manifest.material_id, 1)
    assert len(localized.snapshot_assets) == 1
    path, mime = store.snapshot_asset(localized.snapshot_assets[0].asset_id)
    assert path.read_bytes() == b"PNG-safe-bytes"
    assert mime == "image/png"


@pytest.mark.asyncio
async def test_snapshot_image_rejects_wrong_mime_and_does_not_hotlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.web_source import crawler

    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda _host: False)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"not an image",
            request=request,
        )

    source = markdown_payload(
        source_type="url_snapshot",
        source_ref="https://docs.example.com/",
        title="Guide",
        markdown="![Figure](/private-looking-resource)",
        filename="guide.md",
        source_url="https://docs.example.com/",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        localized = await localize_snapshot_images(source, client=client)

    assert localized.snapshot_assets == ()
    assert "https://" not in localized.units[0]
    assert "Image unavailable" in localized.units[0]


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


def test_reader_metadata_participates_in_revision_identity() -> None:
    base = payload("Same readable content")
    discovered = replace(
        base,
        tutorial_available=True,
        navigation_kind="original",
    )
    generated_outline = replace(
        base,
        outline=(
            OutlineEntry(
                locator=1,
                title="Tutorial",
                level=1,
                synthesised=True,
            ),
        ),
    )

    assert discovered.content_hash != base.content_hash
    assert generated_outline.content_hash != base.content_hash


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

    changed = store.ingest_source(payload("One revised", "Middle", "A unique portable quote moved"))

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


@pytest.mark.parametrize("with_source_urls", [True, False])
def test_outline_identity_guides_quote_and_progress_migration(
    store: ReadingStore,
    with_source_urls: bool,
) -> None:
    intro_url = "https://docs.example.com/tutorial/intro" if with_source_urls else ""
    install_url = "https://docs.example.com/tutorial/install" if with_source_urls else ""
    old_outline = (
        OutlineEntry(locator=1, title="Introduction", level=1, source_url=intro_url),
        OutlineEntry(locator=3, title="Installation", level=1, source_url=install_url),
    )
    first = store.ingest_source(
        payload(
            "Intro start",
            "portable quote in the introduction",
            "Install start",
            "portable quote in installation",
            outline=old_outline,
        )
    )
    store.save_annotation(
        first.material_id,
        Annotation(annotation_id="", locator=4, quote="portable quote"),
    )
    store.save_position(first.material_id, ReadingPosition(locator=4, percentage=0.8))

    # The sections swap order and the quote occurs in both. Source URL is the
    # preferred identity; title + level is the compatibility fallback for
    # older outlines that did not preserve provenance.
    new_outline = (
        OutlineEntry(locator=1, title="Installation", level=1, source_url=install_url),
        OutlineEntry(locator=3, title="Introduction", level=1, source_url=intro_url),
    )
    changed = store.ingest_source(
        payload(
            "Install revised",
            "portable quote in installation revised",
            "Intro revised",
            "portable quote in the introduction revised",
            captured_at=2,
            outline=new_outline,
        )
    )

    migrated = store.annotations(changed.material_id)[0]
    assert migrated.locator == 2
    assert migrated.migration_status == "migrated"
    position = store.position(changed.material_id)
    assert position.locator == 2
    assert position.percentage == 0.8


def test_outline_title_fallback_survives_changed_page_url(store: ReadingStore) -> None:
    first = store.ingest_source(
        payload(
            "Old section",
            "quote that should migrate",
            outline=(
                OutlineEntry(
                    locator=1,
                    title="Install",
                    level=2,
                    source_url="https://docs.example.com/v1/install",
                ),
            ),
        )
    )
    store.save_annotation(
        first.material_id,
        Annotation(annotation_id="", locator=2, quote="quote that should migrate"),
    )

    changed = store.ingest_source(
        payload(
            "New section",
            "quote that should migrate in v2",
            captured_at=2,
            outline=(
                OutlineEntry(
                    locator=1,
                    title="Install",
                    level=2,
                    source_url="https://docs.example.com/v2/install",
                ),
            ),
        )
    )

    migrated = store.annotations(changed.material_id)[0]
    assert migrated.locator == 2
    assert migrated.migration_status == "migrated"


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
