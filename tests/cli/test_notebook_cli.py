"""CLI smoke tests for ``deeptutor notebook`` commands."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from deeptutor_cli.main import app

runner = CliRunner()


class FakeNotebookManager:
    """Fake NotebookManager for CLI testing."""

    def __init__(self) -> None:
        self.notebooks: dict[str, dict] = {}

    def create_notebook(self, name: str, description: str = "") -> dict:
        import time
        import uuid

        nb = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "description": description,
            "created_at": time.time(),
            "updated_at": time.time(),
            "records": [],
        }
        self.notebooks[nb["id"]] = nb
        return nb

    def get_notebook(self, notebook_id: str) -> dict | None:
        return self.notebooks.get(notebook_id)

    def add_record(
        self,
        notebook_ids: list[str],
        record_type: str,
        title: str,
        user_query: str,
        output: str,
        summary: str = "",
        metadata: dict | None = None,
        kb_name: str | None = None,
    ) -> dict:
        import time
        import uuid

        record = {
            "id": str(uuid.uuid4())[:8],
            "type": record_type,
            "title": title,
            "summary": summary,
            "user_query": user_query,
            "output": output,
            "metadata": metadata or {},
            "created_at": time.time(),
            "kb_name": kb_name,
        }
        for nb_id in notebook_ids:
            if nb_id in self.notebooks:
                self.notebooks[nb_id]["records"].append(record)
        return {"record": record, "added_to_notebooks": notebook_ids}

    def update_record(self, notebook_id: str, record_id: str, **kwargs) -> dict | None:
        nb = self.notebooks.get(notebook_id)
        if not nb:
            return None
        for rec in nb["records"]:
            if rec["id"] == record_id:
                rec.update(kwargs)
                return rec
        return None

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        nb = self.notebooks.get(notebook_id)
        if not nb:
            return False
        for i, rec in enumerate(nb["records"]):
            if rec["id"] == record_id:
                nb["records"].pop(i)
                return True
        return False


_fake_manager = FakeNotebookManager()


def _patch_facade(monkeypatch) -> None:
    """Patch DeepTutorApp methods to use the shared fake manager."""

    def _create_notebook(self, **kwargs):
        return _fake_manager.create_notebook(**kwargs)

    def _get_notebook(self, notebook_id):
        return _fake_manager.get_notebook(notebook_id)

    def _add_record(self, **kwargs):
        return _fake_manager.add_record(**kwargs)

    def _update_record(self, notebook_id, record_id, **kwargs):
        return _fake_manager.update_record(notebook_id, record_id, **kwargs)

    def _remove_record(self, notebook_id, record_id) -> bool:
        return _fake_manager.remove_record(notebook_id, record_id)

    from deeptutor.app import facade

    monkeypatch.setattr(facade.DeepTutorApp, "create_notebook", _create_notebook)
    monkeypatch.setattr(facade.DeepTutorApp, "get_notebook", _get_notebook)
    monkeypatch.setattr(facade.DeepTutorApp, "add_record", _add_record)
    monkeypatch.setattr(facade.DeepTutorApp, "update_record", _update_record)
    monkeypatch.setattr(facade.DeepTutorApp, "remove_record", _remove_record)


def test_notebook_add_md_creates_record(monkeypatch, tmp_path: Path) -> None:
    """add-md should read a markdown file and add it as a record to a notebook."""
    _patch_facade(monkeypatch)
    _fake_manager.notebooks.clear()

    notebook = _fake_manager.create_notebook("Test Notebook")

    md_file = tmp_path / "sample.md"
    md_file.write_text("# Hello\n\nThis is a test.", encoding="utf-8")

    result = runner.invoke(
        app,
        ["notebook", "add-md", notebook["id"], str(md_file)],
    )

    assert result.exit_code == 0, result.output
    assert "Added record" in result.output

    stored = _fake_manager.get_notebook(notebook["id"])
    assert stored is not None
    assert len(stored["records"]) == 1
    assert stored["records"][0]["title"] == "sample"
    assert stored["records"][0]["type"] == "chat"
    assert stored["records"][0]["output"] == "# Hello\n\nThis is a test."


def test_notebook_add_md_custom_title_and_type(monkeypatch, tmp_path: Path) -> None:
    """add-md should respect --title and --type options."""
    _patch_facade(monkeypatch)
    _fake_manager.notebooks.clear()

    notebook = _fake_manager.create_notebook("Test Notebook")

    md_file = tmp_path / "notes.md"
    md_file.write_text("## Notes", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "notebook",
            "add-md",
            notebook["id"],
            str(md_file),
            "--title",
            "My Custom Title",
            "--type",
            "research",
        ],
    )

    assert result.exit_code == 0, result.output

    stored = _fake_manager.get_notebook(notebook["id"])
    assert stored["records"][0]["title"] == "My Custom Title"
    assert stored["records"][0]["type"] == "research"


def test_notebook_add_md_file_not_found(monkeypatch) -> None:
    """add-md should exit with an error when the file does not exist."""
    _patch_facade(monkeypatch)

    result = runner.invoke(
        app,
        ["notebook", "add-md", "any-nb", "/path/to/missing.md"],
    )

    assert result.exit_code == 1
    assert "File not found" in result.output


def test_notebook_replace_md_updates_record(monkeypatch, tmp_path: Path) -> None:
    """replace-md should replace the output content of an existing record."""
    _patch_facade(monkeypatch)
    _fake_manager.notebooks.clear()

    notebook = _fake_manager.create_notebook("Test Notebook")
    add_result = _fake_manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type="chat",
        title="Original",
        user_query="",
        output="Old content",
    )
    record_id = add_result["record"]["id"]

    new_md = tmp_path / "updated.md"
    new_md.write_text("# Updated\n\nNew content here.", encoding="utf-8")

    result = runner.invoke(
        app,
        ["notebook", "replace-md", notebook["id"], record_id, str(new_md)],
    )

    assert result.exit_code == 0, result.output
    assert "Updated record" in result.output

    stored = _fake_manager.get_notebook(notebook["id"])
    assert len(stored["records"]) == 1
    assert stored["records"][0]["output"] == "# Updated\n\nNew content here."


def test_notebook_replace_md_record_not_found(monkeypatch, tmp_path: Path) -> None:
    """replace-md should exit with an error when the record does not exist."""
    _patch_facade(monkeypatch)
    _fake_manager.notebooks.clear()

    notebook = _fake_manager.create_notebook("Test Notebook")

    md_file = tmp_path / "any.md"
    md_file.write_text("content", encoding="utf-8")

    result = runner.invoke(
        app,
        ["notebook", "replace-md", notebook["id"], "nonexistent-record", str(md_file)],
    )

    assert result.exit_code == 1
    assert "Record not found" in result.output
