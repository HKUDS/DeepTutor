"""Promotion to admin must also remove the account from group rosters.

The point-of-use guard (`_require_live_member`) stops a lead from acting on a
promoted admin. This is the other half: the stale roster entry should not exist
in the first place, because a lead still sees it, still gets told "member", and
any future endpoint that forgets the guard inherits the hole.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def combined_client(mu_isolated_root, monkeypatch):
    """Auth + multi-user routers on one app, so a role change can be observed
    through the group API in the same test."""
    import deeptutor.api.routers.auth as auth_router
    import deeptutor.api.routers.multi_user as mu_router
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload, hash_password

    root = save_user("root", hash_password("root-password"), role="admin")
    lead = save_user("lead", hash_password("lead-password"), role="user")
    member = save_user("member", hash_password("member-password"), role="user")

    tokens = {
        "root-token": TokenPayload(username="root", role="admin", user_id=root["id"]),
        "lead-token": TokenPayload(username="lead", role="user", user_id=lead["id"]),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(mu_router, "POCKETBASE_ENABLED", False)

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    app.include_router(mu_router.router, prefix="/api/multi-user")
    return TestClient(app), {"root": root, "lead": lead, "member": member}


def test_promoting_a_member_removes_them_from_the_roster(combined_client):
    client, users = combined_client

    created = client.post(
        "/api/multi-user/groups",
        headers=_auth("root-token"),
        json={
            "name": "cohort",
            "lead_user_id": users["lead"]["id"],
            "member_user_ids": [users["member"]["id"]],
        },
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["group"]["id"]
    assert created.json()["group"]["member_user_ids"] == [users["member"]["id"]]

    promoted = client.put(
        "/api/auth/users/member/role",
        headers=_auth("root-token"),
        json={"role": "admin"},
    )
    assert promoted.status_code == 200, promoted.text

    after = client.get(f"/api/multi-user/groups/{group_id}", headers=_auth("lead-token")).json()
    assert after["group"]["member_user_ids"] == [], "a promoted admin must not stay on the roster"


def test_demotion_does_not_re_add_anybody(combined_client):
    """Removal is one-way: demoting an admin must not resurrect the old entry."""
    client, users = combined_client

    created = client.post(
        "/api/multi-user/groups",
        headers=_auth("root-token"),
        json={
            "name": "cohort",
            "lead_user_id": users["lead"]["id"],
            "member_user_ids": [users["member"]["id"]],
        },
    )
    group_id = created.json()["group"]["id"]

    client.put("/api/auth/users/member/role", headers=_auth("root-token"), json={"role": "admin"})
    client.put("/api/auth/users/member/role", headers=_auth("root-token"), json={"role": "user"})

    after = client.get(f"/api/multi-user/groups/{group_id}", headers=_auth("lead-token")).json()
    assert after["group"]["member_user_ids"] == []
