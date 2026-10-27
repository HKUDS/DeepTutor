"""Unit tests for the ``write_note`` tool (append + edit modes)."""

from __future__ import annotations

import pytest

from deeptutor.tools.write_note import (
    ALL_TURNS_SENTINEL,
    DEFAULT_TURNS_TO_INCLUDE,
    MAX_CONTENT_CHARS,
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

    def append_to_record(self, notebook_id, record_id, content, *, max_chars=None):
        from deeptutor.services.notebook.service import AppendResult

        target = self.get_record(notebook_id, record_id)
        if target is None:
            return None
        current = str(target.get("output") or "")
        if current and current.rstrip().endswith(content.strip()):
            return AppendResult(record=target, appended=False)
        joined = f"{current}\n\n{content}" if current else content
        if max_chars is not None and len(joined) > max_chars:
            raise ValueError(f"appending would grow past {max_chars}")
        self.update_record(notebook_id, record_id, output=joined)
        return AppendResult(record=target, appended=True)

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


def test_append_reports_failure_when_no_notebook_accepted_it(tmp_path) -> None:
    """A record id comes back even when nothing was written — don't trust it.

    ``add_record`` skips notebooks that are missing or damaged but still
    returns the record it built, so reporting success off the id alone told
    the model it had saved something that never landed.
    """
    from deeptutor.services.notebook.service import NotebookManager
    from deeptutor.tools.write_note import write_note

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Target")["id"]
    # Corrupt the file after listing has learned about it, so the notebook is
    # a valid choice that nonetheless cannot accept the write.
    (manager.base_dir / f"{notebook_id}.json").write_text("{ broken", encoding="utf-8")

    outcome = write_note(
        mode="append",
        notebook_id=notebook_id,
        title="Should not succeed",
        content="body",
        notebook_manager=manager,
        conversation_history=[],
        current_user_message="hi",
    )

    assert outcome.ok is False
    assert "did not accept" in (outcome.error or "")


def test_edit_reports_a_damaged_notebook_instead_of_raising(tmp_path) -> None:
    from deeptutor.services.notebook.service import NotebookManager
    from deeptutor.tools.write_note import write_note

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Target")["id"]
    (manager.base_dir / f"{notebook_id}.json").write_text("{ broken", encoding="utf-8")

    outcome = write_note(
        mode="edit",
        notebook_id=notebook_id,
        record_id="whatever",
        title="New title",
        notebook_manager=manager,
    )

    assert outcome.ok is False
    assert "Could not read notebook" in (outcome.error or "")


# ---------------------------------------------------------------------------
# Append-to mode (#2049)
# ---------------------------------------------------------------------------


def test_append_to_extends_the_body_and_leaves_the_rest_alone() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}],
        records_by_nb={
            "nb-1": [
                {
                    "id": "rec-1",
                    "title": "Q3 — gradient sign",
                    "summary": "Sign flipped.",
                    "output": "Step 1: read the question.",
                }
            ]
        },
    )
    outcome = write_note(
        mode="append_to",
        notebook_id="nb-1",
        record_id="rec-1",
        content="Step 2: differentiated.",
        notebook_manager=manager,
    )

    assert outcome.ok is True
    assert outcome.mode == "append_to"
    assert outcome.record_id == "rec-1"
    assert manager.last_update == {
        "notebook_id": "nb-1",
        "record_id": "rec-1",
        "output": "Step 1: read the question.\n\nStep 2: differentiated.",
    }


def test_append_to_without_a_record_id_points_at_the_other_mode() -> None:
    """`append` (new record) and `append_to` (extend) sit one character apart;
    the error has to say which one the caller wanted."""
    manager = _FakeManager(notebooks=[{"id": "nb-1", "name": "Mistakes"}])
    outcome = write_note(
        mode="append_to",
        notebook_id="nb-1",
        content="Step 2.",
        notebook_manager=manager,
    )

    assert outcome.ok is False
    assert "record_id" in outcome.error and "mode='append'" in outcome.error
    assert manager.last_update is None


def test_append_to_without_content_changes_nothing() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}],
        records_by_nb={"nb-1": [{"id": "rec-1", "output": "Step 1."}]},
    )
    outcome = write_note(
        mode="append_to",
        notebook_id="nb-1",
        record_id="rec-1",
        content="  ",
        notebook_manager=manager,
    )

    assert outcome.ok is False
    assert "content" in outcome.error
    assert manager.last_update is None


def test_append_to_unknown_record_says_what_to_call_instead() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}],
        records_by_nb={"nb-1": [{"id": "rec-1", "output": "Step 1."}]},
    )
    outcome = write_note(
        mode="append_to",
        notebook_id="nb-1",
        record_id="rec-9",
        content="Step 2.",
        notebook_manager=manager,
    )

    assert outcome.ok is False
    assert "rec-9" in outcome.error and "list_notebook" in outcome.error


def test_append_to_an_empty_body_does_not_leave_a_leading_gap() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}],
        records_by_nb={"nb-1": [{"id": "rec-1", "output": ""}]},
    )
    outcome = write_note(
        mode="append_to",
        notebook_id="nb-1",
        record_id="rec-1",
        content="First step.",
        notebook_manager=manager,
    )

    assert outcome.ok is True
    assert manager.last_update["output"] == "First step."


def test_append_to_refuses_rather_than_truncating_earlier_history() -> None:
    """Cutting the older body to fit the cap would delete what the learner
    wrote earlier — the exact loss this mode exists to prevent."""
    almost_full = "x" * (MAX_CONTENT_CHARS - 10)
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}],
        records_by_nb={"nb-1": [{"id": "rec-1", "output": almost_full}]},
    )
    outcome = write_note(
        mode="append_to",
        notebook_id="nb-1",
        record_id="rec-1",
        content="y" * 100,
        notebook_manager=manager,
    )

    assert outcome.ok is False
    assert "past" in outcome.error and "mode='append'" in outcome.error
    assert manager.last_update is None


def test_the_tool_schema_names_append_to_and_separates_it_from_append() -> None:
    from deeptutor.tools.builtin import SaveFavoriteTool

    definition = SaveFavoriteTool().get_definition()
    mode = next(p for p in definition.parameters if p.name == "mode")
    assert "append_to" in (mode.enum or [])
    assert "new record" in mode.description.lower()
    assert "append_to" in definition.description
    content = next(p for p in definition.parameters if p.name == "content")
    assert "append_to" in content.description
    record_id = next(p for p in definition.parameters if p.name == "record_id")
    assert "append_to" in record_id.description


def test_append_to_a_chunk_bigger_than_the_cap_refuses_and_keeps_the_body() -> None:
    """Both halves are capped by the same limit, so an oversized chunk is
    refused up front instead of being clipped on the way in."""
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}],
        records_by_nb={"nb-1": [{"id": "rec-1", "output": "Step 1."}]},
    )
    outcome = write_note(
        mode="append_to",
        notebook_id="nb-1",
        record_id="rec-1",
        content="z" * (MAX_CONTENT_CHARS + 10),
        notebook_manager=manager,
    )

    assert outcome.ok is False
    assert "Append a shorter amount" in outcome.error
    assert manager.last_update is None


def test_append_to_goes_through_the_managers_atomic_join(tmp_path) -> None:
    """The join must happen under the notebook lock: read-modify-write in the
    tool would drop a save that landed between the read and the write."""
    from deeptutor.services.notebook.service import NotebookManager

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook = manager.create_notebook("Mistakes")
    record_id = manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type="solve",
        title="Q3",
        user_query="why?",
        output="Step 1.",
        summary="Sign flipped.",
    )["record"]["id"]

    for step in ("Step 2.", "Step 3."):
        outcome = write_note(
            mode="append_to",
            notebook_id=notebook["id"],
            record_id=record_id,
            content=step,
            notebook_manager=manager,
        )
        assert outcome.ok, outcome.error

    stored = manager.get_record(notebook["id"], record_id)
    assert stored["output"] == "Step 1.\n\nStep 2.\n\nStep 3."
    assert stored["title"] == "Q3" and stored["summary"] == "Sign flipped."
    reloaded = NotebookManager(base_dir=str(tmp_path)).get_record(notebook["id"], record_id)
    assert reloaded["output"] == stored["output"]


def test_the_manager_refuses_an_append_that_would_pass_the_cap(tmp_path) -> None:
    """The tool's cap check reads a snapshot; the lock-time check is the one
    that cannot be invalidated by a concurrent append."""
    from deeptutor.services.notebook.service import NotebookManager

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook = manager.create_notebook("Mistakes")
    record_id = manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type="solve",
        title="Q3",
        user_query="why?",
        output="abc",
        summary="",
    )["record"]["id"]

    with pytest.raises(ValueError, match="past 5"):
        manager.append_to_record(notebook["id"], record_id, "d" * 10, max_chars=5)
    assert manager.get_record(notebook["id"], record_id)["output"] == "abc"


def test_append_to_reports_a_damaged_notebook_instead_of_raising(tmp_path) -> None:
    """The listing tolerates a corrupt file (it shows an unreadable placeholder),
    so a damaged notebook only surfaces here — on the record read."""
    from deeptutor.services.notebook.service import NotebookManager

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Target")["id"]
    (manager.base_dir / f"{notebook_id}.json").write_text("{ broken", encoding="utf-8")

    outcome = write_note(
        mode="append_to",
        notebook_id=notebook_id,
        record_id="whatever",
        content="more",
        notebook_manager=manager,
    )

    assert outcome.ok is False
    assert "Could not read notebook" in (outcome.error or "")


def test_a_retried_append_does_not_duplicate_the_chunk(tmp_path) -> None:
    """A replayed turn resends the same chunk, and a duplicate step would be the
    learner's cleanup job — so the second send writes nothing, and says so."""
    from deeptutor.services.notebook.service import NotebookManager

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Mistakes")["id"]
    record_id = manager.add_record(
        notebook_ids=[notebook_id],
        record_type="solve",
        title="Q3",
        user_query="why?",
        output="Step 1.",
    )["record"]["id"]

    for _ in range(2):
        outcome = write_note(
            mode="append_to",
            notebook_id=notebook_id,
            record_id=record_id,
            content="Step 2.",
            notebook_manager=manager,
        )
        assert outcome.ok is True

    body = manager.get_record(notebook_id, record_id)["output"]
    assert body == "Step 1.\n\nStep 2."


def test_a_repeated_append_tells_the_model_nothing_was_added(tmp_path, monkeypatch) -> None:
    """A retry and a deliberate repeat send the same text, and only the caller
    knows which one it meant. So the answer must say which one happened,
    instead of reporting "Extended record" for a write that never took place.
    """
    import asyncio

    import deeptutor.services.notebook as notebook_pkg
    from deeptutor.services.notebook.service import NotebookManager
    from deeptutor.tools.builtin import SaveFavoriteTool

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Mistakes")["id"]
    record_id = manager.add_record(
        notebook_ids=[notebook_id],
        record_type="solve",
        title="Q3",
        user_query="why?",
        output="Step 1.",
    )["record"]["id"]
    monkeypatch.setattr(notebook_pkg, "get_notebook_manager", lambda: manager)
    tool = SaveFavoriteTool()

    def append() -> object:
        return asyncio.run(
            tool.execute(
                mode="append_to",
                notebook_id=notebook_id,
                record_id=record_id,
                content="Step 2.",
            )
        )

    first = append()
    second = append()

    assert "Extended record" in first.content
    assert second.success is True, "an idempotent replay is not an error"
    assert "Nothing added" in second.content
    assert manager.get_record(notebook_id, record_id)["output"] == "Step 1.\n\nStep 2."


def test_edit_refuses_to_drop_text_it_could_not_have_read(tmp_path) -> None:
    """`read_note` hands back at most 12,000 characters, so a replacement that
    is shorter than a longer stored body was built from a prefix. Saving it
    deletes the tail with no way back, so the edit has to be refused."""
    from deeptutor.services.notebook.service import NotebookManager
    from deeptutor.tools.read_note import MAX_BODY_CHARS, read_notebook_record

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Mistakes")["id"]
    stored = "\n".join(f"step {i:05d}: the reasoning for this step" for i in range(600))
    record_id = manager.add_record(
        notebook_ids=[notebook_id],
        record_type="solve",
        title="Q3",
        user_query="why?",
        output=stored,
    )["record"]["id"]
    assert len(stored) > MAX_BODY_CHARS

    seen = read_notebook_record(
        notebook_id=notebook_id, record_id=record_id, notebook_manager=manager
    )
    assert seen.summary["truncated"] is True
    outcome = write_note(
        mode="edit",
        notebook_id=notebook_id,
        record_id=record_id,
        content=seen.text,
        notebook_manager=manager,
    )

    assert outcome.ok is False
    assert "append_to" in outcome.error
    assert manager.get_record(notebook_id, record_id)["output"] == stored


def test_an_edit_can_shorten_a_long_record_when_it_says_so(tmp_path, monkeypatch) -> None:
    """The refusal above must not be a wall at the function layer: a caller that
    really means to shorten the record passes `allow_shrink`.

    The ``save_favorite`` tool never reaches this path — it refuses to replace
    an archived body at all, which is why the flag is not in its schema — so
    the guard has to hold for direct callers of ``write_note``.
    """
    import deeptutor.services.notebook as notebook_pkg
    from deeptutor.services.notebook.service import NotebookManager

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Mistakes")["id"]
    record_id = manager.add_record(
        notebook_ids=[notebook_id],
        record_type="solve",
        title="Q3",
        user_query="why?",
        output="step " * 4_000,
    )["record"]["id"]
    monkeypatch.setattr(notebook_pkg, "get_notebook_manager", lambda: manager)

    outcome = write_note(
        mode="edit",
        notebook_id=notebook_id,
        record_id=record_id,
        content="Short version.",
        allow_shrink=True,
        notebook_manager=manager,
    )

    assert outcome.ok is True, outcome.error
    assert manager.get_record(notebook_id, record_id)["output"] == "Short version."


def test_the_save_favorite_tool_refuses_to_replace_an_archived_body(tmp_path) -> None:
    """Favorites preserve original content, so a body-replacing edit is refused
    at the tool boundary before ``write_note`` is ever called."""
    import asyncio

    from deeptutor.services.notebook.service import NotebookManager
    from deeptutor.tools.builtin import SaveFavoriteTool

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Mistakes")["id"]
    record_id = manager.add_record(
        notebook_ids=[notebook_id],
        record_type="solve",
        title="Q3",
        user_query="why?",
        output="Step 1.",
    )["record"]["id"]

    result = asyncio.run(
        SaveFavoriteTool().execute(
            mode="edit",
            notebook_id=notebook_id,
            record_id=record_id,
            content="Rewritten.",
            notebook_manager=manager,
        )
    )

    assert result.success is False
    assert "preserve" in result.content
    assert manager.get_record(notebook_id, record_id)["output"] == "Step 1."
    assert "allow_shrink" not in {p.name for p in SaveFavoriteTool().get_definition().parameters}
