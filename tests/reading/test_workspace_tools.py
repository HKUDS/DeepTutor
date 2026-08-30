from __future__ import annotations

import asyncio
from pathlib import Path

from deeptutor.capabilities.reading import tools as reading_tools
from deeptutor.capabilities.reading.tools import (
    BINDING_KWARG,
    WORKSPACE_KWARG,
    ReadingListTabsTool,
    ReadingSwitchTabTool,
    ReadMaterialTool,
)
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.store import ReadingStore


def test_tab_inventory_has_identity_but_never_material_body(tmp_path: Path, monkeypatch) -> None:
    store, catalog, workspace = _workspace(tmp_path)
    monkeypatch.setattr(reading_tools._ReadingToolBase, "_store", staticmethod(lambda: store))
    monkeypatch.setattr(reading_tools._ReadingToolBase, "_catalog", staticmethod(lambda: catalog))

    result = asyncio.run(ReadingListTabsTool().execute(**{WORKSPACE_KWARG: workspace.workspace_id}))

    assert result.success
    assert "First source" in result.content
    assert "second material secret" not in result.content
    assert set(result.metadata["tabs"][0]) == {
        "material_id",
        "title",
        "source_kind",
        "status",
        "active",
    }


def test_switch_tab_rebinds_later_read_tools(tmp_path: Path, monkeypatch) -> None:
    store, catalog, workspace = _workspace(tmp_path)
    monkeypatch.setattr(reading_tools._ReadingToolBase, "_store", staticmethod(lambda: store))
    monkeypatch.setattr(reading_tools._ReadingToolBase, "_catalog", staticmethod(lambda: catalog))
    target = workspace.tabs[1].material.material_id
    binding = {"material_id": workspace.tabs[0].material.material_id}

    switched = asyncio.run(
        ReadingSwitchTabTool().execute(
            material_id=target,
            **{WORKSPACE_KWARG: workspace.workspace_id, BINDING_KWARG: binding},
        )
    )
    read = asyncio.run(ReadMaterialTool().execute(locators="1", **{BINDING_KWARG: binding}))

    assert switched.metadata["reader_action"] == "switch_tab"
    assert binding["material_id"] == target
    assert "second material secret" in read.content
    assert catalog.get_workspace(workspace.workspace_id).active_material_id == target


def _workspace(tmp_path: Path):
    root = tmp_path / "reading"
    store = ReadingStore(root)
    catalog = ReadingCatalogStore(root)
    first = store.ingest_units(
        "1" * 16,
        filename="first.md",
        title="First source",
        units=["first material evidence"],
    )
    second = store.ingest_units(
        "2" * 16,
        filename="second.md",
        title="Second source",
        units=["second material secret"],
    )
    catalog.register_manifest(first)
    catalog.register_manifest(second)
    workspace = catalog.create_workspace("Research table", [first.material_id, second.material_id])
    return store, catalog, workspace
