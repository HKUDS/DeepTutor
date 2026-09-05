from deeptutor.services.session.turn_runtime import (
    _request_snapshot_metadata,
    _timed_media_id,
    _timed_media_viewport,
)


def test_timed_media_fields_are_normalized() -> None:
    assert _timed_media_id(" ABCDEF0123456789 ") == "abcdef0123456789"
    assert _timed_media_id("../../etc/passwd") == ""
    assert _timed_media_viewport({"time_seconds": -5}) == {"time_seconds": 0.0}
    assert _timed_media_viewport({"time_seconds": 999999}) == {"time_seconds": 86400}


def test_timed_media_id_is_saved_for_regenerate() -> None:
    metadata = _request_snapshot_metadata(
        payload={"timed_media_id": "0123456789abcdef"},
        content="explain",
        capability="immersive_watching",
        config={},
        attachments=[],
        notebook_references=[],
        history_references=[],
        partner_group_references=[],
        question_notebook_references=[],
        book_references=[],
        persona="",
        memory_references=[],
        llm_selection=None,
    )
    snapshot = metadata["request_snapshot"]
    assert snapshot["timedMediaId"] == "0123456789abcdef"
    assert "timedMediaViewport" not in snapshot


def test_watching_workspace_migrates_legacy_preferences() -> None:
    from deeptutor.services.session._turn_runtime_shared import _workspace_mode
    from deeptutor.services.session.workspace_preferences import upgrade_workspace_preferences

    assert upgrade_workspace_preferences({"capability": "immersive_watching"}) == {
        "capability": "immersive_watching",
        "workspace_mode": "immersive_watching",
    }
    assert _workspace_mode("immersive_watching") == "immersive_watching"
    assert upgrade_workspace_preferences({"capability": "chat", "timed_media_id": "stale"}) == {
        "capability": "chat",
        "timed_media_id": "stale",
    }


import pytest


@pytest.mark.asyncio
async def test_watching_turn_persists_owner_validated_binding(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from deeptutor.services.session.sqlite_store import SQLiteSessionStore
    from deeptutor.services.session.turn_runtime import TurnRuntimeManager

    store = SQLiteSessionStore(tmp_path / "sessions.db")
    runtime = TurnRuntimeManager(store)
    seen = []
    monkeypatch.setattr(
        "deeptutor.video_learning.get_timed_media_store",
        lambda: SimpleNamespace(get=lambda value: seen.append(value)),
    )

    async def no_execution(execution):
        pass

    monkeypatch.setattr(runtime, "_run_turn", no_execution)
    session, turn = await runtime.start_turn(
        {
            "content": "Explain here",
            "capability": "immersive_watching",
            "workspace_mode": "immersive_watching",
            "timed_media_id": "0123456789abcdef",
            "language": "en",
        }
    )
    await runtime._executions[turn["id"]].task
    loaded = await store.get_session(session["id"])
    assert loaded["preferences"]["workspace_mode"] == "immersive_watching"
    assert loaded["preferences"]["timed_media_id"] == "0123456789abcdef"
    assert seen == ["0123456789abcdef"]


@pytest.mark.asyncio
async def test_watching_turn_rejects_another_owners_material(tmp_path, monkeypatch) -> None:
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore
    from deeptutor.services.session.turn_runtime import TurnRuntimeManager
    from deeptutor.video_learning import TimedMediaNotFound

    class PrivateStore:
        def get(self, material_id):
            raise TimedMediaNotFound("Video not found")

    monkeypatch.setattr("deeptutor.video_learning.get_timed_media_store", PrivateStore)
    runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "sessions.db"))
    with pytest.raises(TimedMediaNotFound):
        await runtime.start_turn(
            {
                "content": "Explain here",
                "capability": "immersive_watching",
                "timed_media_id": "0123456789abcdef",
                "language": "en",
            }
        )
