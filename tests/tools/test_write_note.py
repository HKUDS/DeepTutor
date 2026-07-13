"""Unit tests for the ``write_note`` tool (append + edit modes)."""

from __future__ import annotations

from deeptutor.tools.write_note import (
    ALL_TURNS_SENTINEL,
    DEFAULT_TURNS_TO_INCLUDE,
    MAX_NOTE_CHARS,
    MAX_TITLE_CHARS,
    write_note,
)


class _FakeManager:
    """Notebook manager stand-in. Tracks last add / update for assertions."""

    def __init__(
        self,
        notebooks=(),
        records_by_nb=None,
        raise_on_add: bool = False,
        raise_on_update: bool = False,
    ):
        self._notebooks = list(notebooks)
        self._records = dict(records_by_nb or {})
        self._raise_on_add = raise_on_add
        self._raise_on_update = raise_on_update
        self.last_add = None
        self.last_update = None

    def list_notebooks(self):
        return list(self._notebooks)

    def get_record(self, notebook_id, record_id):
        for rec in self._records.get(notebook_id, []):
            if str(rec.get("id")) == record_id:
                return rec
        return None

    def add_record(self, **kwargs):
        if self._raise_on_add:
            raise RuntimeError("disk full")
        self.last_add = kwargs
        return {"record": {"id": "rec-123"}, "added_to_notebooks": kwargs["notebook_ids"]}

    def update_record(self, notebook_id, record_id, **kwargs):
        if self._raise_on_update:
            raise RuntimeError("io error")
        target = self.get_record(notebook_id, record_id)
        if target is None:
            return None
        target.update(kwargs)
        self.last_update = {"notebook_id": notebook_id, "record_id": record_id, **kwargs}
        return target


_SAMPLE_HISTORY = [
    {"role": "user", "content": "What is a vector?"},
    {"role": "assistant", "content": "A vector is..."},
    {"role": "user", "content": "And a tensor?"},
    {"role": "assistant", "content": "A tensor generalises..."},
]


# ---------------------------------------------------------------------------
# Mode validation + shared error paths
# ---------------------------------------------------------------------------


def test_rejects_unknown_mode() -> None:
    outcome = write_note(
        mode="rewrite",
        notebook_id="nb-1",
        notebook_manager=_FakeManager(notebooks=[{"id": "nb-1", "name": "N"}]),
    )
    assert outcome.ok is False
    assert "Unknown mode" in outcome.error


def test_rejects_unknown_notebook() -> None:
    outcome = write_note(
        mode="append",
        notebook_id="bogus",
        title="t",
        conversation_history=_SAMPLE_HISTORY,
        notebook_manager=_FakeManager(notebooks=[{"id": "nb-1", "name": "N"}]),
    )
    assert outcome.ok is False
    assert "Unknown notebook_id" in outcome.error


# ---------------------------------------------------------------------------
# Append mode
# ---------------------------------------------------------------------------


def test_append_writes_real_transcript_by_default() -> None:
    manager = _FakeManager(notebooks=[{"id": "nb-1", "name": "Math"}])
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="Vectors",
        turns_to_include=2,
        note="Bookmark for review.",
        conversation_history=_SAMPLE_HISTORY,
        current_user_message="",
        notebook_manager=manager,
    )
    assert outcome.ok is True
    assert outcome.mode == "append"
    body = manager.last_add["output"]
    assert "### User" in body and "### Assistant" in body
    assert "What is a vector?" in body
    assert "A tensor generalises..." in body
    # Note prefix appears above the transcript.
    assert "Bookmark for review." in body
    assert body.index("Bookmark") < body.index("### User")
    assert manager.last_add["metadata"]["mode"] == "append"
    assert manager.last_add["metadata"]["explicit_content"] is False


def test_append_with_explicit_content_skips_auto_transcript() -> None:
    """When the agent passes `content`, it's saved verbatim — supports
    the 'save an agent-authored summary' use case."""
    manager = _FakeManager(notebooks=[{"id": "nb-1", "name": "N"}])
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="Summary",
        content="### My summary\n\nThings to remember.",
        conversation_history=_SAMPLE_HISTORY,
        notebook_manager=manager,
    )
    assert outcome.ok is True
    body = manager.last_add["output"]
    assert "Things to remember." in body
    # The default Q&A transcript headings should NOT appear when
    # explicit content was provided.
    assert "### User" not in body
    assert manager.last_add["metadata"]["explicit_content"] is True


def test_append_accepts_all_sentinel_for_turns() -> None:
    manager = _FakeManager(notebooks=[{"id": "nb-1", "name": "N"}])
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="Everything",
        turns_to_include=ALL_TURNS_SENTINEL,
        conversation_history=_SAMPLE_HISTORY,
        current_user_message="latest question",
        notebook_manager=manager,
    )
    assert outcome.ok is True
    body = manager.last_add["output"]
    # All four history pairs + the current question should be in the body.
    assert "What is a vector?" in body
    assert "And a tensor?" in body
    assert "latest question" in body


def test_append_requires_title() -> None:
    manager = _FakeManager(notebooks=[{"id": "nb-1", "name": "N"}])
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="   ",
        conversation_history=_SAMPLE_HISTORY,
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "title" in outcome.error.lower()


def test_append_refuses_empty_history_without_content() -> None:
    manager = _FakeManager(notebooks=[{"id": "nb-1", "name": "N"}])
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="t",
        conversation_history=[],
        current_user_message="",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "nothing to save" in outcome.error.lower()


def test_append_surfaces_manager_errors_as_outcome() -> None:
    manager = _FakeManager(notebooks=[{"id": "nb-1", "name": "N"}], raise_on_add=True)
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="t",
        conversation_history=_SAMPLE_HISTORY,
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "Save failed" in outcome.error


# ---------------------------------------------------------------------------
# Edit mode
# ---------------------------------------------------------------------------


def test_edit_requires_record_id() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "N"}],
        records_by_nb={"nb-1": [{"id": "r1", "title": "old"}]},
    )
    outcome = write_note(
        mode="edit",
        notebook_id="nb-1",
        title="new",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "record_id" in outcome.error.lower()


def test_edit_rejects_unknown_record() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "N"}],
        records_by_nb={"nb-1": [{"id": "r1", "title": "old"}]},
    )
    outcome = write_note(
        mode="edit",
        notebook_id="nb-1",
        record_id="r-missing",
        title="new",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "not found" in outcome.error.lower()
    assert "list_notebook" in outcome.error  # tells the LLM where to discover ids


def test_edit_requires_at_least_one_field_changed() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "N"}],
        records_by_nb={"nb-1": [{"id": "r1", "title": "old"}]},
    )
    outcome = write_note(
        mode="edit",
        notebook_id="nb-1",
        record_id="r1",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "at least one" in outcome.error.lower()


def test_edit_patches_title_and_content() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "N"}],
        records_by_nb={"nb-1": [{"id": "r1", "title": "old", "output": "old body"}]},
    )
    outcome = write_note(
        mode="edit",
        notebook_id="nb-1",
        record_id="r1",
        title="new title",
        content="new body",
        notebook_manager=manager,
    )
    assert outcome.ok is True
    assert outcome.mode == "edit"
    assert outcome.record_id == "r1"
    assert manager.last_update == {
        "notebook_id": "nb-1",
        "record_id": "r1",
        "title": "new title",
        "output": "new body",
    }


def test_edit_surfaces_manager_errors_as_outcome() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "N"}],
        records_by_nb={"nb-1": [{"id": "r1", "title": "old"}]},
        raise_on_update=True,
    )
    outcome = write_note(
        mode="edit",
        notebook_id="nb-1",
        record_id="r1",
        title="new",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "Edit failed" in outcome.error


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------


def test_default_turns_to_include_is_three() -> None:
    assert DEFAULT_TURNS_TO_INCLUDE == 3


def test_clips_oversized_title_and_note() -> None:
    manager = _FakeManager(notebooks=[{"id": "nb-1", "name": "N"}])
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="x" * (MAX_TITLE_CHARS + 50),
        note="y" * (MAX_NOTE_CHARS + 100),
        conversation_history=_SAMPLE_HISTORY,
        notebook_manager=manager,
    )
    assert outcome.ok is True
    assert manager.last_add["title"].endswith("…")
    assert len(manager.last_add["title"]) <= MAX_TITLE_CHARS + 1
    # The clipped note appears in the body with an ellipsis.
    assert "…" in manager.last_add["output"]
