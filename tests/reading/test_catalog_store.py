from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import user_context
from deeptutor.reading.catalog_models import IngestionStatus, SourceKind
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.models import ReadingError
from deeptutor.reading.store import ReadingStore


@pytest.fixture
def catalog(tmp_path: Path) -> ReadingCatalogStore:
    return ReadingCatalogStore(root=tmp_path / "reading")


def _material(catalog: ReadingCatalogStore, content_id: str, title: str):
    return catalog.upsert_material(
        content_id=content_id,
        filename=f"{title}.pdf",
        title=title,
        source_kind=SourceKind.FILE,
        mime="application/pdf",
        render_mode="pdf",
        status=IngestionStatus.READY,
    )


def test_material_upsert_is_idempotent_and_searchable(catalog: ReadingCatalogStore) -> None:
    first = _material(catalog, "a" * 16, "Attention Is All You Need")
    second = catalog.upsert_material(
        content_id="a" * 16,
        filename="attention.pdf",
        title="Transformer Paper",
        source_kind=SourceKind.FILE,
        mime="application/pdf",
        render_mode="pdf",
        status=IngestionStatus.READY,
    )

    assert second.material_id == first.material_id
    assert second.title == "Transformer Paper"
    assert [row.material_id for row in catalog.list_materials(search="transformer")] == [
        first.material_id
    ]


def test_material_keeps_remote_media_duration(catalog: ReadingCatalogStore) -> None:
    material = catalog.upsert_material(
        content_id="BV1E7wtzaEdq",
        filename="BV1E7wtzaEdq.url",
        title="Agent Skill",
        source_kind=SourceKind.BILIBILI,
        source_url="https://www.bilibili.com/video/BV1E7wtzaEdq",
        render_mode="video",
        duration_seconds=1951,
        status=IngestionStatus.READY,
    )

    assert material.duration_seconds == 1951
    assert material.to_dict()["duration_seconds"] == 1951


def test_workspace_tabs_keep_order_and_active_material_valid(
    catalog: ReadingCatalogStore,
) -> None:
    one = _material(catalog, "1" * 16, "Paper")
    two = _material(catalog, "2" * 16, "Lecture")
    three = _material(catalog, "3" * 16, "Slides")
    workspace = catalog.create_workspace("Multimodal Retrieval", [one.material_id, two.material_id])

    assert workspace.active_material_id == one.material_id
    catalog.add_material(workspace.workspace_id, three.material_id, make_active=True)
    catalog.reorder_materials(
        workspace.workspace_id,
        [three.material_id, one.material_id, two.material_id],
    )

    detail = catalog.get_workspace(workspace.workspace_id)
    assert detail is not None
    assert detail.active_material_id == three.material_id
    assert [tab.material.material_id for tab in detail.tabs] == [
        three.material_id,
        one.material_id,
        two.material_id,
    ]

    catalog.remove_material(workspace.workspace_id, three.material_id)
    detail = catalog.get_workspace(workspace.workspace_id)
    assert detail is not None
    assert detail.active_material_id == one.material_id

    with pytest.raises(ReadingError, match="does not belong"):
        catalog.set_active_material(workspace.workspace_id, three.material_id)


def test_reading_sessions_and_explicit_historical_links(catalog: ReadingCatalogStore) -> None:
    material = _material(catalog, "c" * 16, "Systems Book")
    workspace = catalog.create_workspace("Systems", [material.material_id])
    first = catalog.attach_session(
        workspace.workspace_id,
        "unified_first",
        title="Chapter 1 questions",
        active_material_id=material.material_id,
    )
    second = catalog.attach_session(
        workspace.workspace_id,
        "unified_second",
        title="Compare memory models",
        active_material_id=material.material_id,
    )

    catalog.link_session(workspace.workspace_id, second.session_id, first.session_id)

    assert [row.session_id for row in catalog.list_sessions(workspace.workspace_id)] == [
        second.session_id,
        first.session_id,
    ]
    assert catalog.list_session_links(workspace.workspace_id, second.session_id) == [
        first.session_id
    ]
    assert catalog.unlink_session(workspace.workspace_id, second.session_id, first.session_id)
    assert catalog.list_session_links(workspace.workspace_id, second.session_id) == []
    assert not catalog.unlink_session(workspace.workspace_id, second.session_id, first.session_id)

    with pytest.raises(ReadingError, match="same reading workspace"):
        catalog.link_session(workspace.workspace_id, second.session_id, "missing")


def test_two_catalog_roots_cannot_see_each_other(tmp_path: Path) -> None:
    victim = ReadingCatalogStore(root=tmp_path / "users" / "victim" / "reading")
    attacker = ReadingCatalogStore(root=tmp_path / "users" / "attacker" / "reading")
    secret = _material(victim, "d" * 16, "Private Draft")
    victim.create_workspace("Private", [secret.material_id])

    assert attacker.get_material(secret.material_id) is None
    assert attacker.list_workspaces() == []
    assert victim.db_path != attacker.db_path


def test_default_stores_follow_the_current_user_scope(tmp_path: Path) -> None:
    def user(user_id: str) -> CurrentUser:
        return CurrentUser(
            id=user_id,
            username=user_id,
            role="user",
            scope=UserScope(
                kind="user",
                user_id=user_id,
                root=(tmp_path / "users" / user_id).resolve(),
            ),
        )

    with user_context(user("victim")):
        victim = ReadingCatalogStore()
        victim_content_root = ReadingStore().root
        secret = _material(victim, "e" * 16, "Scoped Private Draft")
        victim.create_workspace("Scoped Private", [secret.material_id])

    with user_context(user("attacker")):
        attacker = ReadingCatalogStore()
        attacker_content_root = ReadingStore().root

    assert attacker.get_material(secret.material_id) is None
    assert attacker.list_workspaces() == []
    assert victim.db_path != attacker.db_path
    assert victim_content_root != attacker_content_root


def test_sidebar_rename_and_delete_reach_the_collection_list(
    catalog: ReadingCatalogStore,
) -> None:
    # The sidebar renames and deletes through /api/sessions, not through the
    # reader; the collection's own list must follow both.
    material = _material(catalog, "d" * 16, "Networks")
    workspace = catalog.create_workspace("Networks", [material.material_id])
    catalog.attach_session(workspace.workspace_id, "kept", title="Kept")
    catalog.attach_session(workspace.workspace_id, "gone", title="Gone")

    catalog.retitle_session("kept", "Routing questions")
    catalog.forget_session("gone")
    catalog.retitle_session("never_tracked", "No-op")

    rows = catalog.list_sessions(workspace.workspace_id)
    assert [(row.session_id, row.title) for row in rows] == [("kept", "Routing questions")]


def test_collection_color_is_a_palette_key_that_survives_updates(
    catalog: ReadingCatalogStore,
) -> None:
    workspace = catalog.create_workspace("Networks", color="Teal")
    assert workspace.color == "teal"
    assert workspace.to_dict()["color"] == "teal"

    renamed = catalog.update_workspace(workspace.workspace_id, title="Routing")
    assert (renamed.title, renamed.color) == ("Routing", "teal")

    # Arbitrary CSS never reaches the page; it falls back to the default tint.
    recolored = catalog.update_workspace(workspace.workspace_id, color="#ff0000; x")
    assert recolored.color == ""


def test_catalog_created_before_collection_colors_gains_the_column(
    tmp_path: Path,
) -> None:
    import sqlite3

    root = tmp_path / "reading"
    catalog = ReadingCatalogStore(root=root)
    workspace = catalog.create_workspace("Legacy")
    database = next(root.rglob("*.sqlite*"))
    with sqlite3.connect(database) as conn:
        conn.execute("ALTER TABLE reading_workspaces DROP COLUMN color")

    reopened = ReadingCatalogStore(root=root)
    assert reopened.get_workspace(workspace.workspace_id).color == ""
    assert reopened.update_workspace(workspace.workspace_id, color="amber").color == "amber"
