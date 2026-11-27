"""Reading APIs release native catalog handles before returning."""

from pathlib import Path
import sqlite3

import pytest

from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.store import ReadingStore


@pytest.mark.parametrize("operation", ["manifest", "annotations", "exists"])
def test_reading_api_closes_catalog_connections(
    tmp_path: Path, monkeypatch, operation: str
) -> None:
    """Retain real handles so garbage collection cannot hide leaked readers."""
    catalog = ReadingCatalogStore(tmp_path)
    store = ReadingStore(tmp_path)
    material_id = "abcdef0123456789"
    manifest = store.ingest_units(material_id, filename="guide.md", units=["A reading guide."])
    catalog.register_manifest(manifest)
    connect = sqlite3.connect
    connections = []

    def track_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connection)
    try:
        result = getattr(store, operation)(material_id)
        assert result is not None
        assert connections
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
        catalog.db_path.rename(tmp_path / "moved.sqlite3")
    finally:
        for connection in connections:
            connection.close()
