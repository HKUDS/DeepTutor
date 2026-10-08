"""Unit tests verifying high-fidelity Reading Workspace for CME 295 Lecture 1."""

import json
from pathlib import Path
import pytest

from deeptutor.reading import ReadingStore, ReadingCatalogStore


def test_reading_workspace_lecture1_manifest_and_units():
    """Verify material manifest and all 20 units are substantive and grounded."""
    store = ReadingStore()
    mat_id = "ef22893fe5ef4aef"
    manifest = store.manifest(mat_id)

    assert manifest.unit_count == 20
    assert manifest.char_count > 60000
    assert "Lecture 1: Transformers & Self-Attention" in manifest.title

    # Verify all 20 units exist and are substantive
    units = list(store.iter_units(mat_id))
    assert len(units) == 20

    for locator, text in units:
        assert locator >= 1 and locator <= 20
        assert len(text) >= 2000, f"Unit {locator} is too short ({len(text)} chars)"
        assert f"# Unit {locator}:" in text, f"Unit {locator} missing header"
        assert "Thời lượng video" in text, f"Unit {locator} missing time metadata"
        assert "$" in text, f"Unit {locator} missing mathematical formula"
        assert "Check-for-Understanding" in text or "Câu hỏi Củng cố" in text


def test_reading_workspace_lecture1_outline():
    """Verify hierarchical outline structure (8 parts, 20 units, 28 rows total)."""
    store = ReadingStore()
    mat_id = "ef22893fe5ef4aef"
    outline = store.outline(mat_id)

    assert len(outline) == 28

    parts = [entry for entry in outline if entry.level == 1]
    units = [entry for entry in outline if entry.level == 2]

    assert len(parts) == 8
    assert len(units) == 20

    # Verify unit locators range 1 to 20
    for idx, unit_entry in enumerate(units, start=1):
        assert unit_entry.locator == idx
        assert f"Unit {idx}:" in unit_entry.title


def test_reading_workspace_catalog_entry():
    """Verify catalog SQLite database row matches manifest."""
    catalog = ReadingCatalogStore()
    mat_id = "ef22893fe5ef4aef"
    record = catalog.get_material(mat_id)

    assert record is not None
    assert record.material_id == mat_id
    assert "Lecture 1: Transformers & Self-Attention" in record.title
    assert record.status == "ready"
