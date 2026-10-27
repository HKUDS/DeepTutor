"""Unit tests for the ``read_note`` tool: the agent's read half of a notebook record.

``list_notebook`` deliberately reports only a clipped summary per record, and
``write_note`` in edit mode replaces the whole body. Until now the agent could
neither read a body nor extend one, so the only safe "keep one evolving record"
pattern was a new record per step (issue #2049)."""

from __future__ import annotations

from deeptutor.tools.read_note import (
    MAX_BODY_CHARS,
    MAX_VALID_IDS_LISTED,
    read_notebook_record,
)


class _FakeManager:
    """Minimal NotebookManager stand-in for unit tests."""

    def __init__(self, notebooks=(), records=None):
        self._notebooks = list(notebooks)
        self._records = dict(records or {})

    def list_notebooks(self):
        return list(self._notebooks)

    def get_records(self, notebook_id):
        return [
            r for r in self._records.values() if r.get("notebook_id", notebook_id) == notebook_id
        ]

    def get_record(self, notebook_id, record_id):
        record = self._records.get(record_id)
        return record if record and record.get("notebook_id", notebook_id) == notebook_id else None


def _record(**overrides):
    record = {
        "id": "rec-1",
        "title": "Q3 — gradient sign",
        "type": "mistake",
        "summary": "Sign flipped when moving the term across.",
        "output": "Step 2 got the sign wrong.",
        "created_at": 1_700_000_000.0,
        "notebook_id": "nb-1",
    }
    record.update(overrides)
    return record


def _manager(**overrides):
    return _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}],
        records={_record(**overrides)["id"]: _record(**overrides)},
    )


def test_returns_the_record_body_and_its_header() -> None:
    outcome = read_notebook_record(
        notebook_id="nb-1", record_id="rec-1", notebook_manager=_manager()
    )

    assert outcome.ok is True
    assert "**Q3 — gradient sign**" in outcome.text
    assert "Sign flipped when moving the term across." in outcome.text
    assert "Step 2 got the sign wrong." in outcome.text
    assert outcome.summary["record_id"] == "rec-1"
    assert outcome.summary["notebook_id"] == "nb-1"


def test_a_long_body_is_capped_and_the_cap_is_stated() -> None:
    """A silently shortened body is worse than a long one: the agent would
    rewrite the record from an incomplete copy."""
    body = "x" * (MAX_BODY_CHARS + 500)
    outcome = read_notebook_record(
        notebook_id="nb-1", record_id="rec-1", notebook_manager=_manager(output=body)
    )

    assert outcome.ok is True
    assert outcome.text.count("x") == MAX_BODY_CHARS
    assert f"{len(body)} characters" in outcome.text
    assert outcome.summary["chars"] == len(body)
    assert outcome.summary["truncated"] is True


def test_unknown_record_names_the_ids_that_can_be_read() -> None:
    """The model has to be able to correct itself from the error alone."""
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}],
        records={
            "rec-1": _record(),
            "rec-2": _record(id="rec-2", title="Q4 — chain rule"),
        },
    )
    outcome = read_notebook_record(notebook_id="nb-1", record_id="rec-9", notebook_manager=manager)

    assert outcome.ok is False
    assert "rec-9" in outcome.error
    assert "`rec-1`" in outcome.error and "`rec-2`" in outcome.error


def test_unknown_notebook_names_the_notebooks_that_exist() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}, {"id": "nb-2", "name": "Reading log"}],
        records={"rec-1": _record()},
    )
    outcome = read_notebook_record(notebook_id="nb-9", record_id="rec-1", notebook_manager=manager)

    assert outcome.ok is False
    assert "nb-9" in outcome.error
    assert "`nb-1`" in outcome.error and "`nb-2`" in outcome.error


def test_a_blank_record_id_says_what_to_call_instead() -> None:
    outcome = read_notebook_record(notebook_id="nb-1", record_id="  ", notebook_manager=_manager())

    assert outcome.ok is False
    assert "record_id is required" in outcome.error
    assert "list_notebook" in outcome.error


def test_read_note_is_wired_where_its_siblings_are() -> None:
    """Registering the class is not enough: it needs the same mount gate,
    the same toggle surface, and prompt hints in both shipped languages."""
    from deeptutor.agents._shared.tool_composition import _CONDITIONAL_MOUNT_FLAGS
    from deeptutor.tools.builtin import CONFIGURABLE_BUILTIN_TOOL_NAMES
    from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPECS
    from deeptutor.tools.prompting import load_prompt_hints

    assert "read_note" in {spec.name for spec in BUILTIN_TOOL_SPECS}
    from deeptutor.agents.visualize.capability import _VISUALIZE_SAFE_BUILTINS

    assert _CONDITIONAL_MOUNT_FLAGS["read_note"] == "has_notebooks"
    # Visualize reuses the chat loop's read surface; a notebook the agent can
    # list but not read would be a dead end there.
    assert "read_note" in _VISUALIZE_SAFE_BUILTINS
    assert "read_note" in CONFIGURABLE_BUILTIN_TOOL_NAMES
    for language in ("en", "zh"):
        hints = load_prompt_hints("read_note", language=language)
        assert hints.short_description and hints.when_to_use


def test_unknown_record_does_not_dump_every_id_in_a_large_notebook() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Mistakes"}],
        records={f"rec-{i}": _record(id=f"rec-{i}") for i in range(30)},
    )
    outcome = read_notebook_record(notebook_id="nb-1", record_id="rec-x", notebook_manager=manager)

    assert outcome.ok is False
    assert outcome.error.count("`rec-") == MAX_VALID_IDS_LISTED
    assert "+10 more" in outcome.error


def test_reads_a_record_created_by_the_real_manager(tmp_path) -> None:
    """The fakes share the test author's assumptions; the store is the truth."""
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

    outcome = read_notebook_record(
        notebook_id=notebook["id"], record_id=record_id, notebook_manager=manager
    )

    assert outcome.ok is True
    assert "Step 1." in outcome.text
    assert outcome.summary["chars"] == len("Step 1.")


def test_execute_returns_the_rendered_note_and_metadata(tmp_path, monkeypatch) -> None:
    from deeptutor.services.notebook.service import NotebookManager
    from deeptutor.tools.builtin import ReadNoteTool

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

    import deeptutor.services.notebook as notebook_pkg

    monkeypatch.setattr(notebook_pkg, "get_notebook_manager", lambda: manager)
    result = __import__("asyncio").run(
        ReadNoteTool().execute(notebook_id=notebook["id"], record_id=record_id)
    )

    assert result.success is True
    assert "Step 1." in result.content
    assert result.metadata["record_id"] == record_id


def test_a_damaged_notebook_is_reported_not_raised(tmp_path) -> None:
    from deeptutor.services.notebook.service import NotebookManager

    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Target")["id"]
    (manager.base_dir / f"{notebook_id}.json").write_text("{ broken", encoding="utf-8")

    outcome = read_notebook_record(
        notebook_id=notebook_id, record_id="whatever", notebook_manager=manager
    )

    assert outcome.ok is False
    assert "Failed to load" in outcome.error


def test_a_truncated_body_is_cut_on_a_line_boundary() -> None:
    """A mid-line cut can leave a fence open, and the hint tells the model to
    quote what it keeps back into `write_note`."""
    body = "```python\n" + "print(1)\n" * 2000
    outcome = read_notebook_record(
        notebook_id="nb-1", record_id="rec-1", notebook_manager=_manager(output=body)
    )

    assert outcome.ok is True
    # Closed fence, then the notice outside it, so the notice is not read as code.
    assert outcome.text.count("```") % 2 == 0
    assert outcome.text.rstrip().endswith("in the record, showing the first 11997.)_")


def test_unknown_notebook_error_caps_the_id_list() -> None:
    """Thirty notebooks should not all come back in one error."""
    manager = _FakeManager(
        notebooks=[{"id": f"nb-{i}", "name": f"N{i}"} for i in range(30)],
        records={},
    )
    outcome = read_notebook_record(notebook_id="nb-9x", record_id="rec-1", notebook_manager=manager)

    assert outcome.ok is False
    assert outcome.error.count("`nb-") == MAX_VALID_IDS_LISTED
    assert f"+{30 - MAX_VALID_IDS_LISTED} more" in outcome.error
