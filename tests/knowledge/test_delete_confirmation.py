"""Cancelled knowledge-base deletion must retain the native MarginNote store."""

from pathlib import Path

import pytest

from deeptutor.capabilities.marginnote4.store import MarginNoteStore
from deeptutor.knowledge.manager import KnowledgeBaseManager


@pytest.mark.parametrize("response", ["no", "eof"])
def test_cancelled_delete_preserves_marginnote_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    database = tmp_path / "library.db"
    store = MarginNoteStore(database)
    device, _token = store.pair_device(device_name="iPad")
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_marginnote4_kb("Library", db_path=str(database))
    original_config = manager.config_file.read_bytes()
    original_database = database.read_bytes()

    def answer(_prompt: str) -> str:
        if response == "eof":
            raise EOFError
        return response

    monkeypatch.setattr("builtins.input", answer)
    if response == "eof":
        with pytest.raises(EOFError):
            manager.delete_knowledge_base("Library")
    else:
        assert manager.delete_knowledge_base("Library") is False

    assert database.is_file()
    assert database.read_bytes() == original_database
    assert manager.config_file.read_bytes() == original_config
    assert [item.device_id for item in store.list_devices()] == [device.device_id]
