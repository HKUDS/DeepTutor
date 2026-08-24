"""Notebook service regression tests."""

from __future__ import annotations

import json

from deeptutor.services.notebook.service import NotebookManager, RecordType


def test_add_record_accepts_enum_record_type(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook = manager.create_notebook("CLI test notebook")

    result = manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type=RecordType.CHAT,
        title="Sample",
        user_query="Sample",
        output="# Sample",
    )

    assert result["record"]["type"] == RecordType.CHAT

    stored = manager.get_notebook(notebook["id"])
    assert stored is not None
    assert stored["records"][0]["type"] == "chat"


def test_add_record_strips_thinking_tags_from_summary(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook = manager.create_notebook("Sanitized notebook")

    result = manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type="chat",
        title="Sample",
        summary="<think>private reasoning</think>\nReusable summary.",
        user_query="Sample",
        output="# Sample",
    )

    assert result["record"]["summary"] == "Reusable summary."

    stored = manager.get_notebook(notebook["id"])
    assert stored is not None
    assert stored["records"][0]["summary"] == "Reusable summary."


def test_get_notebook_repairs_existing_thinking_tags_in_summary(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook = manager.create_notebook("Legacy notebook")
    manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type="chat",
        title="Sample",
        summary="Reusable summary.",
        user_query="Sample",
        output="# Sample",
    )

    path = manager._get_notebook_file(notebook["id"])
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["records"][0]["summary"] = "<think>old reasoning</think>\nReusable summary."
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    repaired = manager.get_notebook(notebook["id"])
    assert repaired is not None
    assert repaired["records"][0]["summary"] == "Reusable summary."
    assert "old reasoning" not in path.read_text(encoding="utf-8")


def test_concurrent_add_record_keeps_every_record(tmp_path) -> None:
    """Forty parallel saves must all land, and must not corrupt the file.

    Before per-notebook locking + atomic writes, this lost records at two
    writers and left unparseable JSON at forty — which surfaced to users as
    a notebook that had silently vanished.
    """
    import threading

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Race")["id"]

    def save(index: int) -> None:
        manager.add_record(
            notebook_ids=[notebook_id],
            record_type=RecordType.CHAT,
            title=f"record-{index}",
            user_query="q",
            output="body" * 500,
        )

    threads = [threading.Thread(target=save, args=(i,)) for i in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stored = manager.get_notebook(notebook_id)
    assert stored is not None
    assert len(stored["records"]) == 40
    assert {row["record_count"] for row in manager.list_notebooks()} == {40}


def test_update_record_leaves_unmentioned_kb_name_alone(tmp_path) -> None:
    """Renaming a record must not clear its knowledge-base link."""
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("KB")["id"]
    record = manager.add_record(
        notebook_ids=[notebook_id],
        record_type=RecordType.CHAT,
        title="Original",
        user_query="q",
        output="o",
        kb_name="physics",
    )["record"]

    updated = manager.update_record(notebook_id, record["id"], title="Renamed")

    assert updated is not None
    assert updated["title"] == "Renamed"
    assert updated["kb_name"] == "physics"

    cleared = manager.update_record(notebook_id, record["id"], kb_name=None)
    assert cleared is not None
    assert cleared["kb_name"] is None


def test_damaged_notebook_is_reported_not_hidden(tmp_path) -> None:
    """A file that exists but does not parse must never look like a deletion."""
    import pytest

    from deeptutor.services.notebook.service import NotebookCorruptedError

    manager = NotebookManager(base_dir=str(tmp_path))
    (tmp_path / "broken01.json").write_text("{ not json", encoding="utf-8")

    listed = {row["id"]: row for row in manager.list_notebooks()}
    assert listed["broken01"]["unreadable"] is True

    with pytest.raises(NotebookCorruptedError):
        manager.get_notebook("broken01")


def test_list_notebooks_adopts_files_missing_from_the_index(tmp_path) -> None:
    """A notebook whose index row was lost is still listed."""
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Orphaned")["id"]

    manager.index_file.write_text('{"notebooks": []}', encoding="utf-8")

    listed = {row["id"] for row in manager.list_notebooks()}
    assert notebook_id in listed


def test_copy_record_is_independent_of_its_source(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    source = manager.create_notebook("Source")["id"]
    target = manager.create_notebook("Target")["id"]
    record = manager.add_record(
        notebook_ids=[source],
        record_type=RecordType.CHAT,
        title="Shared",
        user_query="q",
        output="o",
    )["record"]

    copied = manager.copy_record(source, record["id"], target)
    assert copied is not None
    assert copied["id"] != record["id"]

    manager.update_record(target, copied["id"], title="Edited in target")

    assert manager.get_record(source, record["id"])["title"] == "Shared"
    assert manager.get_record(target, copied["id"])["title"] == "Edited in target"


def test_move_record_leaves_the_source_notebook(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    source = manager.create_notebook("Source")["id"]
    target = manager.create_notebook("Target")["id"]
    record = manager.add_record(
        notebook_ids=[source],
        record_type=RecordType.CHAT,
        title="Travelling",
        user_query="q",
        output="o",
    )["record"]

    moved = manager.move_record(source, record["id"], target)

    assert moved is not None
    assert manager.get_record(source, record["id"]) is None
    assert manager.get_records(target)[0]["title"] == "Travelling"


def test_statistics_counts_every_record_type(tmp_path) -> None:
    """The per-type breakdown must add up to the total, tutorbot included."""
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Stats")["id"]
    for record_type in (RecordType.CHAT, RecordType.TUTORBOT, RecordType.RESEARCH):
        manager.add_record(
            notebook_ids=[notebook_id],
            record_type=record_type,
            title=str(record_type),
            user_query="q",
            output="o",
        )

    stats = manager.get_statistics()

    assert stats["records_by_type"]["tutorbot"] == 1
    assert sum(stats["records_by_type"].values()) == stats["total_records"] == 3


def test_export_markdown_renders_titles_and_bodies(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Exported", description="A short blurb")["id"]
    manager.add_record(
        notebook_ids=[notebook_id],
        record_type=RecordType.CHAT,
        title="First entry",
        user_query="q",
        output="Body text.",
        summary="One-line summary.",
    )

    markdown = manager.export_markdown(notebook_id)

    assert markdown is not None
    assert "# Exported" in markdown
    assert "> A short blurb" in markdown
    assert "## First entry" in markdown
    assert "Body text." in markdown
