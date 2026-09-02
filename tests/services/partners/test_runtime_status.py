from __future__ import annotations

from deeptutor.services.partners.runtime_status import PartnerRuntimeStatusRepository


def test_runtime_status_is_shared_and_does_not_persist_channel_credentials(tmp_path) -> None:
    path = tmp_path / "status.sqlite3"
    writer = PartnerRuntimeStatusRepository(path)
    reader = PartnerRuntimeStatusRepository(path)

    written = writer.set(
        "ada",
        owner_id="worker-a",
        running=True,
        state="running",
        payload={
            "partner_id": "ada",
            "name": "Ada",
            "channels": {"telegram": {"token": "secret"}},
        },
        started_at="2026-09-01T12:00:00",
    )

    assert "channels" not in written
    status = reader.get("ada")
    assert status is not None
    assert status["running"] is True
    assert status["runtime_owner_id"] == "worker-a"
    assert status["name"] == "Ada"
    assert "channels" not in status

    writer.delete("ada")
    assert reader.get("ada") is None
