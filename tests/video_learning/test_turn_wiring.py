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
