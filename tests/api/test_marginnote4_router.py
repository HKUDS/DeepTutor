"""Auth boundary of the MarginNote 4 device bridge.

``/sync`` and ``/heartbeat`` are the only endpoints in the app reachable
without a DeepTutor session — a paired device presents
``Authorization: MarginNote <device_id>:<token>`` instead. Two properties of
that boundary are pinned here because both were wrong when the bridge landed:

* an unauthenticated request must not write anything to disk, and
* a token must not be issued into a workspace the sync path cannot read.

Mounted on a bare FastAPI app so the suite does not boot every other router.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import marginnote4
from deeptutor.api.routers.auth import require_auth
from deeptutor.services.path_service import PathService


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    yield tmp_path
    PathService.reset_instance()


@pytest.fixture
def client(home: Path):
    app = FastAPI()
    app.include_router(marginnote4.router, prefix="/api/v1/marginnote4")
    # Session auth is the subject of its own tests; here it only needs to be
    # out of the way so the device boundary is what gets exercised.
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def _mn4_dir() -> Path:
    return PathService.get_instance().user_data_dir / "marginnote4"


def test_unauthenticated_sync_writes_nothing_to_disk(client) -> None:
    """A store is created by constructing it, so auth must come first.

    ``_store_for`` mkdir's and installs the schema. Reaching it before the
    token check turned ``POST /sync`` into an unauthenticated file-creation
    primitive: one database per distinct ``X-MN4-KB`` value, from a caller with
    no credentials at all.
    """
    for n in range(5):
        response = client.post(
            "/api/v1/marginnote4/sync",
            json={"cursor": "", "objects": [], "deleted_ids": []},
            headers={
                "Authorization": "MarginNote fake-device:fake-token",
                "X-MN4-KB": f"invented-{n}",
            },
        )
        assert response.status_code == 403

    assert not _mn4_dir().exists()


def test_unauthenticated_heartbeat_writes_nothing_to_disk(client) -> None:
    response = client.post(
        "/api/v1/marginnote4/heartbeat",
        headers={
            "Authorization": "MarginNote fake-device:fake-token",
            "X-MN4-KB": "invented",
        },
    )
    assert response.status_code == 403
    assert not _mn4_dir().exists()


@pytest.mark.parametrize(
    "header",
    [None, "Bearer abc", "MarginNote no-colon-here"],
)
def test_malformed_device_credentials_are_rejected(client, header) -> None:
    headers = {} if header is None else {"Authorization": header}
    response = client.post("/api/v1/marginnote4/heartbeat", headers=headers)
    assert response.status_code == 401
    assert not _mn4_dir().exists()


def test_pair_then_sync_round_trip(client) -> None:
    paired = client.post("/api/v1/marginnote4/pair", json={"device_name": "iPad"})
    assert paired.status_code == 200, paired.text
    body = paired.json()

    auth = {"Authorization": f"MarginNote {body['device_id']}:{body['token']}"}
    synced = client.post(
        "/api/v1/marginnote4/sync",
        json={
            "cursor": "c1",
            "objects": [
                {"object_id": "o1", "object_type": "note", "title": "Attention"},
            ],
            "deleted_ids": [],
        },
        headers=auth,
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["stored"] == 1

    beat = client.post("/api/v1/marginnote4/heartbeat", headers=auth)
    assert beat.status_code == 200
    assert beat.json()["object_count"] == 1


def test_revoked_device_cannot_sync(client) -> None:
    body = client.post("/api/v1/marginnote4/pair", json={}).json()
    assert client.delete(f"/api/v1/marginnote4/devices/{body['device_id']}").status_code == 200

    response = client.post(
        "/api/v1/marginnote4/heartbeat",
        headers={"Authorization": f"MarginNote {body['device_id']}:{body['token']}"},
    )
    assert response.status_code == 403


def test_pair_refuses_when_sync_would_read_another_workspace(client, monkeypatch, tmp_path) -> None:
    """Pairing has a session, ``/sync`` does not — so they can resolve apart.

    ``/pair`` runs under ``require_auth`` and lands in the caller's own
    workspace; the device endpoints carry no session and resolve the default
    one. For any account where those differ, pairing used to succeed and then
    every sync 403'd forever. Refuse the credential instead of issuing a dead
    one.
    """
    monkeypatch.setattr(
        marginnote4,
        "_device_db_path",
        lambda kb_name: tmp_path / "some-other-workspace" / f"{kb_name}.db",
    )

    response = client.post("/api/v1/marginnote4/pair", json={})
    assert response.status_code == 501
    assert "different workspaces" in response.json()["detail"]


def test_sync_batch_is_bounded(client) -> None:
    """An oversized batch is refused by validation, before any work starts."""
    body = client.post("/api/v1/marginnote4/pair", json={}).json()
    oversized = [
        {"object_id": f"o{i}", "object_type": "note"} for i in range(marginnote4.MAX_SYNC_BATCH + 1)
    ]

    response = client.post(
        "/api/v1/marginnote4/sync",
        json={"cursor": "", "objects": oversized, "deleted_ids": []},
        headers={"Authorization": f"MarginNote {body['device_id']}:{body['token']}"},
    )
    assert response.status_code == 422
