from __future__ import annotations

from deeptutor.services.memory.service import MemoryService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def test_memory_service_snapshot_is_empty_without_file(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    service = MemoryService(
        path_service=type(
            "PathServiceStub",
            (),
            {"get_memory_dir": lambda self: tmp_path / "memory"},
        )(),
        store=store,
    )

    snapshot = service.read_snapshot()

    assert snapshot.content == ""
    assert snapshot.exists is False
    assert snapshot.updated_at is None


async def _no_change_llm(**_kwargs) -> str:
    return "NO_CHANGE"


async def _rewrite_llm(**_kwargs) -> str:
    return "## Preferences\n- Prefer concise answers.\n\n## Context\n- Working on DeepTutor memory."


def test_memory_service_refresh_turn_writes_rewritten_document(monkeypatch, tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    service = MemoryService(
        path_service=type(
            "PathServiceStub",
            (),
            {"get_memory_dir": lambda self: tmp_path / "memory"},
        )(),
        store=store,
    )
    monkeypatch.setattr("deeptutor.services.memory.service.llm_complete", _rewrite_llm)

    import asyncio

    result = asyncio.run(
        service.refresh_from_turn(
            user_message="Please remember that I like concise answers.",
            assistant_message="Sure, I'll keep answers concise.",
            session_id="s1",
            capability="chat",
            language="en",
        )
    )

    assert result.changed is True
    assert "## Preferences" in result.content
    assert "concise answers" in result.content
    assert service.memory_path.exists()


def test_memory_service_refresh_turn_skips_when_model_returns_no_change(
    monkeypatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    service = MemoryService(
        path_service=type(
            "PathServiceStub",
            (),
            {"get_memory_dir": lambda self: tmp_path / "memory"},
        )(),
        store=store,
    )
    monkeypatch.setattr("deeptutor.services.memory.service.llm_complete", _no_change_llm)

    import asyncio

    result = asyncio.run(
        service.refresh_from_turn(
            user_message="What is 2+2?",
            assistant_message="4",
            session_id="s1",
            capability="chat",
            language="en",
        )
    )

    assert result.changed is False
    assert result.content == ""
    assert service.memory_path.exists() is False
