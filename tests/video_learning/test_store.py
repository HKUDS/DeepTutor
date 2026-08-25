from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from deeptutor.video_learning.store import (
    VideoLearningConflict,
    VideoLearningNotFound,
    VideoLearningStore,
)


@pytest.fixture
def store(tmp_path: Path) -> VideoLearningStore:
    return VideoLearningStore(tmp_path / "remote.db")


def test_pairing_claim_and_one_time_token_delivery(store: VideoLearningStore) -> None:
    pairing = store.create_pairing()
    claimed, device, token = store.claim_pairing(code=pairing.code, owner_id="user-1")
    assert claimed.claimed is True
    assert device.owner_id == "user-1"
    assert store.verify_token(device.device_id, token) is not None

    first = store.pairing_status(pairing.pairing_id, pairing.claim_secret)
    assert first["status"] == "claimed"
    assert first["token"] == token

    second = store.pairing_status(pairing.pairing_id, pairing.claim_secret)
    assert second["status"] == "claimed"
    assert "token" not in second


def test_pairing_rejects_reuse_and_expiry(store: VideoLearningStore, monkeypatch) -> None:
    pairing = store.create_pairing()
    store.claim_pairing(code=pairing.code, owner_id="user-1")
    with pytest.raises(VideoLearningConflict):
        store.claim_pairing(code=pairing.code, owner_id="user-2")

    expired = store.create_pairing()
    with store._connect() as conn:
        conn.execute(
            "UPDATE pairings SET expires_at = ? WHERE pairing_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), expired.pairing_id),
        )
    with pytest.raises(VideoLearningConflict):
        store.claim_pairing(code=expired.code, owner_id="user-1")


def test_session_commands_notes_and_isolation(store: VideoLearningStore) -> None:
    pairing = store.create_pairing()
    _, device, token = store.claim_pairing(code=pairing.code, owner_id="owner-a")
    assert store.verify_token(device.device_id, token)

    session = store.upsert_session(
        device=device,
        instance_origin="http://127.0.0.1:3000",
        video_id="dQw4w9WgXcQ",
        title="Demo",
        position_ms=12_500,
        duration_ms=60_000,
        playback_state="playing",
        playback_rate=1.0,
    )
    command = store.enqueue_command(
        session=session,
        command_type="seek",
        payload={"position_ms": 20_000},
        command_id="cmd-1",
    )
    again = store.enqueue_command(
        session=session,
        command_type="seek",
        payload={"position_ms": 99_000},
        command_id="cmd-1",
    )
    assert again.payload["position_ms"] == 20_000
    assert command.command_id == again.command_id

    pending = store.pending_commands(device.device_id, session.session_id)
    assert [c.command_id for c in pending] == ["cmd-1"]
    acked = store.ack_command(device_id=device.device_id, command_id="cmd-1", ok=True)
    assert acked.status == "acked"
    assert store.pending_commands(device.device_id, session.session_id) == []

    note = store.create_note(
        owner_id="owner-a",
        video_id="dQw4w9WgXcQ",
        position_ms=session.position_ms,
        body="important beat",
        title=session.title,
        instance_origin=session.instance_origin,
    )
    assert store.list_notes("owner-a", "dQw4w9WgXcQ")[0].note_id == note.note_id
    assert store.list_notes("owner-b", "dQw4w9WgXcQ") == []
    assert store.revoke_device("owner-a", device.device_id) is True
    assert store.verify_token(device.device_id, token) is None


def test_offline_session_rejects_commands(store: VideoLearningStore) -> None:
    pairing = store.create_pairing()
    _, device, _token = store.claim_pairing(code=pairing.code, owner_id="owner-a")
    session = store.upsert_session(
        device=device,
        instance_origin="http://127.0.0.1:3000",
        video_id="abc12345678",
        title="Demo",
        position_ms=0,
        duration_ms=10_000,
        playback_state="paused",
        playback_rate=1.0,
    )
    with store._connect() as conn:
        conn.execute(
            "UPDATE sessions SET last_heartbeat_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat(), session.session_id),
        )
    session = store.get_session(session.session_id)
    assert session is not None
    with pytest.raises(VideoLearningConflict):
        store.enqueue_command(session=session, command_type="pause")
