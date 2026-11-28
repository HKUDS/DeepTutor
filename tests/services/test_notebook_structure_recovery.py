"""Recover the notebook library when a JSON file has an invalid structure."""

import json

import pytest

from deeptutor.services.notebook.service import NotebookCorruptedError, NotebookManager


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"id": "broken", "records": None}, {"id": "broken", "records": [None]}],
)
def test_invalid_notebook_does_not_hide_healthy_notebooks(tmp_path, payload) -> None:
    manager = NotebookManager(str(tmp_path))
    healthy = manager.create_notebook("Healthy")
    damaged_file = tmp_path / "broken.json"
    damaged_file.write_text(json.dumps(payload), encoding="utf-8")
    original = damaged_file.read_bytes()

    listed = {row["id"]: row for row in manager.list_notebooks()}
    assert listed[healthy["id"]]["name"] == "Healthy"
    assert listed["broken"]["unreadable"] is True
    with pytest.raises(NotebookCorruptedError):
        manager.get_notebook("broken")
    assert damaged_file.read_bytes() == original
    assert manager.get_notebook(healthy["id"])["name"] == "Healthy"


@pytest.mark.parametrize("payload", [None, [], {"notebooks": None}, {"notebooks": [None]}])
def test_invalid_index_is_rebuilt_without_losing_files(tmp_path, payload) -> None:
    manager = NotebookManager(str(tmp_path))
    healthy = manager.create_notebook("Healthy")
    healthy_file = tmp_path / f"{healthy['id']}.json"
    original = healthy_file.read_bytes()
    manager.index_file.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "broken.json").write_text("null", encoding="utf-8")

    listed = {row["id"]: row for row in manager.list_notebooks()}
    assert listed[healthy["id"]]["name"] == "Healthy"
    assert listed["broken"]["unreadable"] is True
    assert healthy_file.read_bytes() == original

    created = manager.create_notebook("After recovery")
    assert {row["id"] for row in manager.list_notebooks()} == {
        healthy["id"],
        created["id"],
        "broken",
    }


def test_legacy_notebook_without_records_remains_readable(tmp_path) -> None:
    manager = NotebookManager(str(tmp_path))
    (tmp_path / "legacy.json").write_text(
        json.dumps({"id": "legacy", "name": "Legacy", "extra": "preserved"}), encoding="utf-8"
    )
    assert manager.get_notebook("legacy")["extra"] == "preserved"
    assert manager.list_notebooks()[0]["record_count"] == 0
