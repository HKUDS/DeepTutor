"""The vendored snapshot itself: it ships in the package, so it is tested like code.

A re-sync of ``vendor/catalog.json`` is a data change that can silently alter what
this deployment will execute. These tests are the review that data gets.
"""

from __future__ import annotations

import json

from deeptutor.services.cli_apps import catalog as catalog_module
from deeptutor.services.cli_apps import load_catalog, search_catalog
from deeptutor.services.cli_apps.catalog import (
    CATALOG_PATH,
    catalog_pin,
    category_counts,
    get_entry,
)
from deeptutor.services.cli_apps.models import (
    ENTRY_POINT_RE,
    HARNESS_REPO,
    InstallKind,
)


def test_the_snapshot_is_pinned_to_one_reviewed_commit() -> None:
    pin = catalog_pin()
    assert len(pin) == 40 and all(char in "0123456789abcdef" for char in pin), (
        "the harness pin must be a full commit sha — a branch or tag can move, "
        "and this value is what every first-party install resolves to"
    )


def test_every_row_in_the_snapshot_parses() -> None:
    """A dropped row is a silently missing app, so none should be dropped."""
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["apps"]
    assert len(load_catalog()) == len(raw)


def test_every_first_party_install_carries_the_pin() -> None:
    pin = catalog_pin()
    harness = [
        entry for entry in load_catalog() if entry.install.kind is InstallKind.PINNED_HARNESS
    ]
    assert harness, "the snapshot should contain first-party harnesses"
    for entry in harness:
        assert entry.install.target.startswith(f"git+{HARNESS_REPO}@{pin}#subdirectory="), (
            f"{entry.id} would install from an unpinned revision"
        )


def test_no_installable_entry_has_an_unusable_entry_point() -> None:
    """An installable app has to name an executable we can resolve to a file."""
    for entry in load_catalog():
        if entry.install.installable:
            assert ENTRY_POINT_RE.match(entry.entry_point), entry.id


def test_every_refusal_explains_itself() -> None:
    for entry in load_catalog():
        if not entry.install.installable:
            assert entry.install.reason.strip(), (
                f"{entry.id} is catalogued as not installable with no reason; the store "
                "would show a disabled card and say nothing"
            )


def test_ids_are_unique() -> None:
    ids = [entry.id for entry in load_catalog()]
    assert len(ids) == len(set(ids))


# ── search ────────────────────────────────────────────────────────────────


def test_the_default_listing_hides_what_cannot_be_installed() -> None:
    installable = search_catalog(installable_only=True, limit=60)
    assert all(entry.install.installable for entry in installable.entries)
    everything = search_catalog(installable_only=False, limit=60)
    assert everything.total > installable.total


def test_paging_walks_every_match_exactly_once() -> None:
    seen: list[str] = []
    cursor = ""
    while True:
        page = search_catalog(limit=7, cursor=cursor, installable_only=False)
        seen.extend(entry.id for entry in page.entries)
        cursor = page.next_cursor
        if not cursor:
            break
    assert len(seen) == len(set(seen))
    assert sorted(seen) == sorted(entry.id for entry in load_catalog())


def test_a_forged_cursor_restarts_rather_than_crashing() -> None:
    page = search_catalog(cursor="../../etc/passwd", limit=3)
    assert page.entries and page.entries[0].id == search_catalog(limit=3).entries[0].id


def test_a_limit_beyond_the_ceiling_is_clamped() -> None:
    page = search_catalog(limit=10_000, installable_only=False)
    assert len(page.entries) <= catalog_module.MAX_PAGE_SIZE


def test_category_counts_agree_with_what_clicking_the_chip_shows() -> None:
    counts = category_counts(installable_only=True)
    assert counts, "the store's filter row would be empty"
    for category, count in counts.items():
        page = search_catalog(category=category, installable_only=True, limit=60)
        assert page.total == count, category
        assert count > 0, "a chip with no matches opens onto an empty grid"


def test_search_matches_a_description_not_only_a_name() -> None:
    hits = search_catalog(q="bastion", installable_only=False, limit=60)
    assert any(entry.id == "jumpserver" for entry in hits.entries)


def test_a_missing_entry_is_none_rather_than_an_error() -> None:
    assert get_entry("definitely-not-an-app") is None


def test_an_unreadable_snapshot_degrades_to_an_empty_catalog(monkeypatch, tmp_path) -> None:
    """A bad re-sync must not take the whole store — or the app — down."""
    broken = tmp_path / "catalog.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(catalog_module, "CATALOG_PATH", broken)
    catalog_module.load_catalog.cache_clear()
    catalog_module._by_id.cache_clear()
    catalog_module.catalog_pin.cache_clear()
    try:
        assert load_catalog() == ()
        assert get_entry("blender") is None
    finally:
        catalog_module.load_catalog.cache_clear()
        catalog_module._by_id.cache_clear()
        catalog_module.catalog_pin.cache_clear()


def test_a_snapshot_without_a_pin_offers_nothing(monkeypatch, tmp_path) -> None:
    """No pin means every first-party install would resolve to a moving branch."""
    unpinned = tmp_path / "catalog.json"
    unpinned.write_text(
        json.dumps({"meta": {}, "apps": [{"name": "x", "display_name": "X", "description": "d"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(catalog_module, "CATALOG_PATH", unpinned)
    catalog_module.load_catalog.cache_clear()
    catalog_module._by_id.cache_clear()
    try:
        assert load_catalog() == ()
    finally:
        catalog_module.load_catalog.cache_clear()
        catalog_module._by_id.cache_clear()
