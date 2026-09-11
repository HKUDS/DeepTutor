"""Turn-runtime wiring for immersive reading.

The reader's state reaches the model through three seams in
``turn_runtime``: normalisation of the client's fields, the request snapshot
persisted with the user message, and the recovery of that snapshot on a
regenerate. Each is covered here because each fails silently — a turn simply
loses its grounding and the answer quietly gets worse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.services.path_service import PathService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import (
    READING_SELECTION_MAX_CHARS,
    TurnRuntimeManager,
    _reading_material_id,
    _reading_references,
    _reading_viewport,
    _request_snapshot_metadata,
    _workspace_mode,
)

# ---------------------------------------------------------------------------
# material id normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["0123456789abcdef", "ABCDEF0123456789", "  0123456789abcdef  ", "0123abcd"],
)
def test_content_hash_shaped_ids_are_accepted_and_lowercased(value: str) -> None:
    assert _reading_material_id(value) == value.strip().lower()


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "../../etc/passwd",
        "not-hex",
        "0123",  # too short to be a content hash
        "z" * 16,
        "0123456789abcdef/../..",
        123,
        {"id": "0123456789abcdef"},
    ],
)
def test_anything_not_shaped_like_a_material_id_is_rejected(value: object) -> None:
    """The id becomes a filesystem path, so the shape is enforced at the edge."""
    assert _reading_material_id(value) == ""


# ---------------------------------------------------------------------------
# viewport normalisation
# ---------------------------------------------------------------------------


def test_viewport_carries_locator_and_selection() -> None:
    assert _reading_viewport({"locator": 12, "selection": "some text"}) == {
        "locator": 12,
        "selection": "some text",
    }


def test_absent_viewport_fields_are_omitted_not_zeroed() -> None:
    """ "No selection" and "an empty selection" must not look the same."""
    assert _reading_viewport({"locator": 3}) == {"locator": 3}
    assert _reading_viewport({"selection": "x"}) == {"selection": "x"}
    assert _reading_viewport({}) == {}
    assert _reading_viewport({"locator": 0, "selection": "   "}) == {}


@pytest.mark.parametrize("value", [None, "not a dict", 7, [1, 2]])
def test_malformed_viewport_degrades_to_empty(value: object) -> None:
    assert _reading_viewport(value) == {}


def test_nonsense_locators_are_dropped() -> None:
    assert _reading_viewport({"locator": -4}) == {}
    assert _reading_viewport({"locator": "abc"}) == {}
    assert _reading_viewport({"locator": None}) == {}


def test_selection_is_bounded_because_it_enters_the_prompt() -> None:
    viewport = _reading_viewport({"selection": "x" * (READING_SELECTION_MAX_CHARS * 3)})
    assert len(viewport["selection"]) == READING_SELECTION_MAX_CHARS


def test_explicit_reading_references_are_normalized_at_the_turn_boundary() -> None:
    assert _reading_references(
        [
            {
                "material_id": "ABCDEF0123456789",
                "revision": 4,
                "locators": [2, 2, "3"],
            },
            {"material_id": "../../etc", "revision": 1, "locators": [1]},
        ]
    ) == [{"material_id": "abcdef0123456789", "revision": 4, "locators": [2, 3]}]


# ---------------------------------------------------------------------------
# snapshot persistence
# ---------------------------------------------------------------------------


def _snapshot(payload: dict) -> dict:
    metadata = _request_snapshot_metadata(
        content="hi",
        capability="",
        payload=payload,
        attachments=[],
        config={},
        notebook_references=[],
        history_references=[],
        question_notebook_references=[],
        book_references=[],
        persona="",
        memory_references=[],
        partner_group_references=[],
        llm_selection=None,
    )
    return metadata["request_snapshot"]


def test_open_material_is_persisted_with_the_user_message() -> None:
    """A regenerate must re-run with the same document open."""
    snapshot = _snapshot({"reading_material_id": "0123456789abcdef"})
    assert snapshot["readingMaterialId"] == "0123456789abcdef"


def test_workspace_mode_is_persisted_independently_of_the_action() -> None:
    snapshot = _snapshot(
        {
            "workspace_mode": "immersive_reading",
            "reading_material_id": "0123456789abcdef",
        }
    )
    assert snapshot["workspaceMode"] == "immersive_reading"


@pytest.mark.parametrize(
    ("value", "capability", "expected"),
    [
        ("immersive_reading", "deep_research", "immersive_reading"),
        ("mastery_path", "visualize", "mastery_path"),
        (None, "immersive_reading", "immersive_reading"),
        (None, "mastery_path", "mastery_path"),
        ("unknown", "chat", ""),
    ],
)
def test_workspace_mode_is_orthogonal_with_legacy_fallback(
    value: object, capability: str, expected: str
) -> None:
    assert _workspace_mode(value, capability=capability) == expected


def test_a_plain_chat_turn_carries_no_reading_key() -> None:
    assert "readingMaterialId" not in _snapshot({})
    assert "readingMaterialId" not in _snapshot({"reading_material_id": ""})


def test_a_bogus_id_is_not_persisted() -> None:
    assert "readingMaterialId" not in _snapshot({"reading_material_id": "../../etc"})


@pytest.mark.asyncio
async def test_empty_workspace_starts_in_no_material_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    try:
        workspace = ReadingCatalogStore().create_workspace("Empty reading workspace")
        runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "turns.sqlite3"))

        async def _noop_run_turn(_execution) -> None:
            return None

        monkeypatch.setattr(runtime, "_run_turn", _noop_run_turn)
        _session, turn = await runtime.start_turn(
            {
                "type": "start_turn",
                "capability": "chat",
                "workspace_mode": "immersive_reading",
                "reading_workspace_id": workspace.workspace_id,
                "content": "What can I read here?",
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "config": {},
            }
        )

        assert runtime._executions[turn["id"]].payload["reading_material_id"] == ""
        detail = await runtime.store.get_session(_session["id"])
        assert detail is not None
        assert detail["preferences"]["workspace_mode"] == "immersive_reading"
        assert detail["preferences"]["capability"] == "chat"
    finally:
        PathService.reset_instance()


def test_explicit_reading_references_are_persisted_for_retry() -> None:
    snapshot = _request_snapshot_metadata(
        content="hi",
        capability="chat",
        payload={},
        attachments=[],
        config={},
        notebook_references=[],
        history_references=[],
        partner_group_references=[],
        question_notebook_references=[],
        book_references=[],
        reading_references=[{"material_id": "abcdef0123456789", "revision": 1, "locators": [1, 2]}],
        persona="",
        memory_references=[],
        llm_selection=None,
    )["request_snapshot"]

    assert snapshot["readingReferences"] == [
        {"material_id": "abcdef0123456789", "revision": 1, "locators": [1, 2]}
    ]
