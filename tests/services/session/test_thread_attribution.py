from __future__ import annotations

import pytest

from deeptutor.services.session._turn_runtime_shared import (
    _format_selection_tutor_context,
)
from deeptutor.services.session.model_history import SOURCE_MESSAGE_METADATA_KEY
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.thread_attribution import (
    BACKFILL_ATTEMPTED_KEY,
    TUTOR_SOURCE_KEY,
    backfill_thread_sources,
    locate_quote_message,
)


def _quote(text: str) -> dict:
    return {"type": "quote", "extracted_text": text}


async def _thread(store: SQLiteSessionStore, parent_id: str, preferences: dict) -> dict:
    child = await store.ensure_session(None)
    await store.update_session_preferences(
        child["id"],
        {"parent_session_id": parent_id, "session_kind": "selection_tutor", **preferences},
    )
    session = await store.get_session(child["id"])
    assert session is not None
    return session


@pytest.mark.asyncio
async def test_recovers_the_source_from_the_stored_selection(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "selected.db")
    parent = await store.ensure_session(None)
    source = await store.add_message(
        parent["id"],
        "assistant",
        "The **fork** call returns twice: once in the parent, once in the child.",
    )
    await store.add_message(parent["id"], "user", "So why does the child skip it?")
    thread = await _thread(store, parent["id"], {"tutor_selected_text": "fork call returns twice"})
    before = thread["updated_at"]

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert rows[0]["preferences"]["tutor_source_message_id"] == source
    persisted = await store.get_session(thread["session_id"])
    assert persisted is not None
    assert persisted["preferences"]["tutor_source_message_id"] == source
    assert persisted["preferences"][BACKFILL_ATTEMPTED_KEY] is True
    # Recovering an anchor is not activity: the row keeps its place in the list.
    assert persisted["updated_at"] == before


@pytest.mark.asyncio
async def test_recovers_the_source_from_the_threads_quote_attachment(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "quoted.db")
    parent = await store.ensure_session(None)
    source = await store.add_message(parent["id"], "assistant", "It returns twice.")
    child = await store.ensure_session(None)
    await store.update_session_preferences(
        child["id"],
        {"parent_session_id": parent["id"], "session_kind": "selection_tutor"},
    )
    await store.add_message(
        child["id"],
        "user",
        "Why twice?",
        attachments=[{"type": "quote", "extracted_text": "It returns twice."}],
    )
    thread = await store.get_session(child["id"])
    assert thread is not None

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert rows[0]["preferences"]["tutor_source_message_id"] == source
    persisted = await store.get_session(child["id"])
    assert persisted is not None
    assert persisted["preferences"]["tutor_source_message_id"] == source


@pytest.mark.asyncio
async def test_an_ambiguous_passage_is_left_unattributed(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "ambiguous.db")
    parent = await store.ensure_session(None)
    await store.add_message(parent["id"], "assistant", "It returns twice in each process.")
    await store.add_message(parent["id"], "assistant", "Yes: It returns twice in each process.")
    thread = await _thread(
        store, parent["id"], {"tutor_selected_text": "It returns twice in each process."}
    )

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert "tutor_source_message_id" not in rows[0]["preferences"]
    assert rows[0]["preferences"][BACKFILL_ATTEMPTED_KEY] is True


@pytest.mark.asyncio
async def test_a_preferred_assistant_match_wins_over_a_user_echo(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "echo.db")
    parent = await store.ensure_session(None)
    source = await store.add_message(parent["id"], "assistant", "It returns twice.")
    await store.add_message(parent["id"], "user", "It returns twice.")
    thread = await _thread(store, parent["id"], {"tutor_selected_text": "It returns twice."})

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert rows[0]["preferences"]["tutor_source_message_id"] == source


@pytest.mark.asyncio
async def test_a_thread_without_a_passage_is_only_attempted_once(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "bare.db")
    parent = await store.ensure_session(None)
    thread = await _thread(store, parent["id"], {})

    await backfill_thread_sources(store, parent["id"], [thread])
    persisted = await store.get_session(thread["session_id"])
    assert persisted is not None
    assert persisted["preferences"][BACKFILL_ATTEMPTED_KEY] is True
    assert "tutor_source_message_id" not in persisted["preferences"]

    # A second pass has nothing left to attempt, even if the parent changed.
    await store.add_message(parent["id"], "assistant", "A late message.")
    rows = await backfill_thread_sources(store, parent["id"], [persisted])
    assert "tutor_source_message_id" not in rows[0]["preferences"]


@pytest.mark.asyncio
async def test_an_attributed_thread_is_not_revisited(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "attributed.db")
    parent = await store.ensure_session(None)
    await store.add_message(parent["id"], "assistant", "It returns twice.")
    thread = await _thread(
        store,
        parent["id"],
        {"tutor_selected_text": "It returns twice.", "tutor_source_message_id": 99},
    )

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert rows[0]["preferences"]["tutor_source_message_id"] == 99
    assert BACKFILL_ATTEMPTED_KEY not in rows[0]["preferences"]


def test_short_passages_are_not_evidence_of_a_source() -> None:
    messages = [{"id": 1, "role": "assistant", "content": "x = 1"}]

    assert locate_quote_message(messages, "x = 1") is None
    assert locate_quote_message(messages, "x = 1 and y = 2") is None


@pytest.mark.asyncio
async def test_a_deliberately_detached_thread_is_not_recovered(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "detached.db")
    parent = await store.ensure_session(None)
    await store.add_message(parent["id"], "assistant", "It returns twice.")
    thread = await _thread(
        store,
        parent["id"],
        {
            "tutor_selected_text": "It returns twice.",
            "tutor_source_message_id": "",
            BACKFILL_ATTEMPTED_KEY: True,
        },
    )

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert rows[0]["preferences"]["tutor_source_message_id"] == ""


def _selection_prompt(
    *,
    parent_id: str,
    selection: str,
    containing: str,
    role: str,
    language: str = "en",
) -> str:
    return _format_selection_tutor_context(
        {
            "parent_session_id": parent_id,
            "selected_text": selection,
            "source_message_text": containing,
            "source_message_role": role,
        },
        language=language,
    )


@pytest.mark.asyncio
async def test_prompt_role_resolves_a_user_selection_echoed_by_the_assistant(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "prompt-role.db")
    parent = await store.ensure_session(None)
    selection = "It returns twice in each process."
    user_source = await store.add_message(parent["id"], "user", selection)
    await store.add_message(parent["id"], "assistant", f"Yes: {selection}")
    child = await store.ensure_session(None)
    await store.update_session_preferences(
        child["id"],
        {"parent_session_id": parent["id"], "session_kind": "selection_tutor"},
    )
    await store.add_message(
        child["id"],
        "assistant",
        "It returns twice, once in each process.",
        metadata={
            "model_turn": {
                "system": _selection_prompt(
                    parent_id=parent["id"],
                    selection=selection,
                    containing=selection,
                    role="user",
                )
            }
        },
    )
    thread = await store.get_session(child["id"])

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert rows[0]["preferences"][TUTOR_SOURCE_KEY] == user_source


@pytest.mark.asyncio
async def test_prompt_containing_message_disambiguates_a_repeated_passage(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "prompt-containing.db")
    parent = await store.ensure_session(None)
    selection = "It returns twice."
    first = await store.add_message(
        parent["id"], "assistant", "In the parent. It returns twice. Done."
    )
    await store.add_message(parent["id"], "assistant", "In the child. It returns twice. Done.")
    child = await store.ensure_session(None)
    await store.update_session_preferences(
        child["id"],
        {"parent_session_id": parent["id"], "session_kind": "selection_tutor"},
    )
    await store.add_message(
        child["id"],
        "assistant",
        "Because the call continues in both processes.",
        metadata={
            "model_turn": {
                "system": _selection_prompt(
                    parent_id=parent["id"],
                    selection=selection,
                    containing="In the parent. It returns twice. Done.",
                    role="assistant",
                )
            }
        },
    )
    thread = await store.get_session(child["id"])

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert rows[0]["preferences"][TUTOR_SOURCE_KEY] == first


@pytest.mark.asyncio
async def test_a_later_quote_recovers_a_thread_whose_first_message_was_bare(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "later-quote.db")
    parent = await store.ensure_session(None)
    source = await store.add_message(parent["id"], "assistant", "It returns twice.")
    child = await store.ensure_session(None)
    await store.update_session_preferences(
        child["id"],
        {"parent_session_id": parent["id"], "session_kind": "selection_tutor"},
    )
    await store.add_message(child["id"], "user", "What is this about?")
    await store.add_message(
        child["id"], "user", "Why twice?", attachments=[_quote("It returns twice.")]
    )
    thread = await store.get_session(child["id"])

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert rows[0]["preferences"][TUTOR_SOURCE_KEY] == source


@pytest.mark.asyncio
async def test_multiple_quotes_on_one_message_are_not_guessed(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "many-quotes.db")
    parent = await store.ensure_session(None)
    await store.add_message(parent["id"], "assistant", "It returns twice.")
    await store.add_message(parent["id"], "assistant", "The child skips the parent path.")
    child = await store.ensure_session(None)
    await store.update_session_preferences(
        child["id"],
        {"parent_session_id": parent["id"], "session_kind": "selection_tutor"},
    )
    await store.add_message(
        child["id"],
        "user",
        "Why?",
        attachments=[_quote("It returns twice."), _quote("The child skips the parent path.")],
    )
    thread = await store.get_session(child["id"])

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert TUTOR_SOURCE_KEY not in rows[0]["preferences"]
    assert rows[0]["preferences"][BACKFILL_ATTEMPTED_KEY] is True


@pytest.mark.asyncio
async def test_structured_assistant_metadata_recovers_the_source(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "structured.db")
    parent = await store.ensure_session(None)
    source = await store.add_message(parent["id"], "assistant", "It returns twice.")
    child = await store.ensure_session(None)
    await store.update_session_preferences(
        child["id"],
        {"parent_session_id": parent["id"], "session_kind": "selection_tutor"},
    )
    await store.add_message(
        child["id"],
        "assistant",
        "Because both processes continue.",
        metadata={
            SOURCE_MESSAGE_METADATA_KEY: {
                "message_id": source,
                "role": "assistant",
            }
        },
    )
    thread = await store.get_session(child["id"])

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert rows[0]["preferences"][TUTOR_SOURCE_KEY] == source


@pytest.mark.asyncio
async def test_structured_metadata_cannot_point_outside_the_parent(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "structured-invalid.db")
    parent = await store.ensure_session(None)
    await store.add_message(parent["id"], "assistant", "It returns twice.")
    child = await store.ensure_session(None)
    await store.update_session_preferences(
        child["id"],
        {"parent_session_id": parent["id"], "session_kind": "selection_tutor"},
    )
    await store.add_message(
        child["id"],
        "assistant",
        "Because both processes continue.",
        metadata={
            SOURCE_MESSAGE_METADATA_KEY: {
                "message_id": 999,
                "role": "assistant",
            }
        },
    )
    thread = await store.get_session(child["id"])

    rows = await backfill_thread_sources(store, parent["id"], [thread])

    assert TUTOR_SOURCE_KEY not in rows[0]["preferences"]
    assert rows[0]["preferences"][BACKFILL_ATTEMPTED_KEY] is True
