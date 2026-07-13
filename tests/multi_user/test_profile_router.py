"""Router-level tests for the self-service profile/avatar endpoints.

These mount the real auth router on a throwaway FastAPI app with
``AUTH_ENABLED`` forced on and ``decode_token`` stubbed, so the full
dependency chain (``require_auth`` → contextvar install → handler) runs
against the isolated user store from ``mu_isolated_root``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64
GIF_BYTES = b"GIF89a" + b"\x00" * 64
SVG_BYTES = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"


def _auth(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


@pytest.fixture
def profile_client(mu_isolated_root, monkeypatch):
    """TestClient over the auth router with two seeded users and stub tokens.

    Returns ``(client, users)`` where ``users`` maps username → stored record.
    Valid bearer tokens: ``admin-token`` (alice), ``user-token`` (bob), and
    ``ghost-token`` (a valid JWT whose user is absent from the local store,
    mirroring PocketBase-backed identities).
    """
    import deeptutor.api.routers.auth as auth_router
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload

    alice = save_user("alice", "$2b$12$placeholder", role="admin")
    bob = save_user("bob", "$2b$12$placeholder", role="user")

    tokens = {
        "admin-token": TokenPayload(username="alice", role="admin", user_id=alice["id"]),
        "user-token": TokenPayload(username="bob", role="user", user_id=bob["id"]),
        "ghost-token": TokenPayload(username="ghost", role="user", user_id="u_ghost"),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1/auth")
    return TestClient(app), {"alice": alice, "bob": bob}


def test_profile_endpoints_require_auth(profile_client):
    client, users = profile_client
    requests = [
        ("get", "/api/v1/auth/profile", {}),
        ("put", "/api/v1/auth/profile", {"json": {"avatar": ""}}),
        ("put", "/api/v1/auth/profile/avatar", {"files": {"file": ("a.png", PNG_BYTES)}}),
        ("delete", "/api/v1/auth/profile/avatar", {}),
        ("get", f"/api/v1/auth/avatar/{users['bob']['id']}", {}),
    ]
    for method, url, kwargs in requests:
        response = getattr(client, method)(url, **kwargs)
        assert response.status_code == 401, f"{method.upper()} {url}"


def test_get_profile_returns_own_record(profile_client):
    client, users = profile_client
    body = client.get("/api/v1/auth/profile", headers=_auth("user-token")).json()
    assert body["username"] == "bob"
    assert body["role"] == "user"
    assert body["id"] == users["bob"]["id"]
    assert body["avatar"] == ""


def test_get_profile_falls_back_to_token_claims(profile_client):
    """Identities without a local record (PocketBase mode) still render."""
    client, _ = profile_client
    response = client.get("/api/v1/auth/profile", headers=_auth("ghost-token"))
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "ghost"
    assert body["id"] == "u_ghost"


def test_put_profile_sets_marker_on_own_record_only(profile_client):
    from deeptutor.multi_user.identity import load_users

    client, _ = profile_client
    response = client.put(
        "/api/v1/auth/profile",
        headers=_auth("user-token"),
        json={"avatar": "icon:leaf:teal"},
    )
    assert response.status_code == 200
    users = load_users()
    assert users["bob"]["avatar"] == "icon:leaf:teal"
    assert users["alice"]["avatar"] == ""


def test_put_profile_rejects_img_and_malformed_markers(profile_client):
    client, _ = profile_client
    for bad in ("img:1", "icon:Leaf:teal", "icon:a:b:c", "../etc/passwd"):
        response = client.put(
            "/api/v1/auth/profile",
            headers=_auth("user-token"),
            json={"avatar": bad},
        )
        assert response.status_code == 422, bad


def test_upload_avatar_stores_file_and_bumps_version(profile_client):
    from deeptutor.multi_user.identity import get_avatar_file, load_users

    client, users = profile_client
    bob_id = users["bob"]["id"]

    first = client.put(
        "/api/v1/auth/profile/avatar",
        headers=_auth("user-token"),
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    )
    assert first.status_code == 200
    assert first.json()["avatar"] == "img:1"
    stored = get_avatar_file(bob_id)
    assert stored is not None and stored.suffix == ".png"

    # Re-upload in another format: version bumps, stale extension is removed.
    second = client.put(
        "/api/v1/auth/profile/avatar",
        headers=_auth("user-token"),
        files={"file": ("photo.webp", WEBP_BYTES, "image/webp")},
    )
    assert second.status_code == 200
    assert second.json()["avatar"] == "img:2"
    stored = get_avatar_file(bob_id)
    assert stored is not None and stored.suffix == ".webp"
    assert load_users()["bob"]["avatar"] == "img:2"


def test_upload_avatar_validates_by_magic_bytes_not_filename(profile_client):
    client, _ = profile_client
    # Claimed PNG name/content-type, but GIF and SVG bytes must be rejected.
    for payload in (GIF_BYTES, SVG_BYTES):
        response = client.put(
            "/api/v1/auth/profile/avatar",
            headers=_auth("user-token"),
            files={"file": ("totally-a.png", payload, "image/png")},
        )
        assert response.status_code == 415


def test_upload_avatar_enforces_size_cap(profile_client):
    client, _ = profile_client
    oversized = PNG_BYTES + b"\x00" * (1024 * 1024)
    response = client.put(
        "/api/v1/auth/profile/avatar",
        headers=_auth("user-token"),
        files={"file": ("big.png", oversized, "image/png")},
    )
    assert response.status_code == 413


def test_upload_avatar_disabled_in_pocketbase_mode(profile_client, monkeypatch):
    import deeptutor.api.routers.auth as auth_router

    client, _ = profile_client
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", True)
    response = client.put(
        "/api/v1/auth/profile/avatar",
        headers=_auth("user-token"),
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 400


def test_delete_avatar_removes_file_and_resets_marker(profile_client):
    from deeptutor.multi_user.identity import get_avatar_file, load_users

    client, users = profile_client
    client.put(
        "/api/v1/auth/profile/avatar",
        headers=_auth("user-token"),
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    )

    response = client.delete("/api/v1/auth/profile/avatar", headers=_auth("user-token"))
    assert response.status_code == 200
    assert get_avatar_file(users["bob"]["id"]) is None
    assert load_users()["bob"]["avatar"] == ""


def test_picking_icon_after_upload_drops_the_image_file(profile_client):
    from deeptutor.multi_user.identity import get_avatar_file

    client, users = profile_client
    client.put(
        "/api/v1/auth/profile/avatar",
        headers=_auth("user-token"),
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    )
    client.put(
        "/api/v1/auth/profile",
        headers=_auth("user-token"),
        json={"avatar": "icon:leaf:teal"},
    )
    assert get_avatar_file(users["bob"]["id"]) is None


def test_avatar_serving_headers_and_visibility(profile_client):
    client, users = profile_client
    client.put(
        "/api/v1/auth/profile/avatar",
        headers=_auth("user-token"),
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    )

    # Any authenticated user may view (admin table shows all avatars).
    response = client.get(f"/api/v1/auth/avatar/{users['bob']['id']}", headers=_auth("admin-token"))
    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "private" in response.headers["cache-control"]


def test_admin_user_deletion_removes_avatar_file(profile_client):
    """Deleting an account must not leave its avatar image orphaned on disk."""
    from deeptutor.multi_user.identity import get_avatar_file

    client, users = profile_client
    client.put(
        "/api/v1/auth/profile/avatar",
        headers=_auth("user-token"),
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    )
    assert get_avatar_file(users["bob"]["id"]) is not None

    response = client.delete("/api/v1/auth/users/bob", headers=_auth("admin-token"))
    assert response.status_code == 200
    assert get_avatar_file(users["bob"]["id"]) is None


def test_avatar_serving_rejects_missing_and_malformed_ids(profile_client):
    client, users = profile_client
    # No avatar stored for alice yet.
    missing = client.get(f"/api/v1/auth/avatar/{users['alice']['id']}", headers=_auth("user-token"))
    assert missing.status_code == 404
    # Traversal-shaped ids never reach the filesystem layer.
    for bad in ("..%2F..%2Fauth_secret", ".."):
        response = client.get(f"/api/v1/auth/avatar/{bad}", headers=_auth("user-token"))
        assert response.status_code == 404, bad


def test_auth_status_exposes_avatar_marker(profile_client):
    client, _ = profile_client
    client.put(
        "/api/v1/auth/profile",
        headers=_auth("user-token"),
        json={"avatar": "icon:star:rose"},
    )
    body = client.get("/api/v1/auth/status", headers=_auth("user-token")).json()
    assert body["authenticated"] is True
    assert body["avatar"] == "icon:star:rose"

    anonymous = client.get("/api/v1/auth/status").json()
    assert anonymous["authenticated"] is False
    assert anonymous["avatar"] == ""
