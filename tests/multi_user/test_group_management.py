"""Group management: a lead provisions accounts and hands out resources that
they hold themselves — inside their own roster, and nowhere else.

These tests pin the two boundaries that make the feature safe to delegate:

* a lead can never mint an admin, and never edits `role` at all;
* a lead can never hand out a resource they were not given, so scoped
  oversight cannot become a way around the admin's grant decisions.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _client(mu_isolated_root, monkeypatch) -> tuple[TestClient, dict]:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import multi_user as multi_user_router
    from deeptutor.multi_user.grants import save_grant
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload, hash_password

    root = save_user("root", hash_password("root-password"), role="admin")
    lead = save_user("lead", hash_password("lead-password"))
    member = save_user("member", hash_password("member-password"))
    outsider = save_user("outsider", hash_password("outsider-password"))

    save_grant(
        lead["id"],
        {
            "models": {"llm": [{"profile_id": "p1", "model_ids": ["m1"]}]},
            "knowledge_bases": [{"name": "kb1"}],
            "skills": [{"skill_id": "s1"}],
        },
    )

    tokens = {
        "root-token": TokenPayload(username="root", role="admin", user_id=root["id"]),
        "lead-token": TokenPayload(username="lead", role="user", user_id=lead["id"]),
        "member-token": TokenPayload(username="member", role="user", user_id=member["id"]),
        "outsider-token": TokenPayload(username="outsider", role="user", user_id=outsider["id"]),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", False)

    app = FastAPI()
    app.include_router(multi_user_router.router, prefix="/api/multi-user")
    return TestClient(app), {"root": root, "lead": lead, "member": member, "outsider": outsider}


def _group_with(client: TestClient, users: dict, members: tuple[str, ...] = ()):
    return client.post(
        "/api/multi-user/groups",
        headers=_auth("root-token"),
        json={
            "name": "Team A",
            "lead_user_id": users["lead"]["id"],
            "member_user_ids": list(members),
        },
    ).json()["group"]["id"]


def test_lead_creates_an_account_inside_their_group(mu_isolated_root, monkeypatch):
    from deeptutor.multi_user.identity import get_user

    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users)

    created = client.post(
        f"/api/multi-user/groups/{group_id}/members",
        headers=_auth("lead-token"),
        json={"username": "newbie", "password": "newbie-password"},
    )

    assert created.status_code == 201
    record = get_user("newbie")
    assert record is not None
    assert record["role"] == "user", "a lead must never mint an admin"
    assert record["preset"] == "standard"

    roster = client.get(f"/api/multi-user/groups/{group_id}", headers=_auth("lead-token")).json()[
        "group"
    ]
    assert "newbie" in [member["username"] for member in roster["members"]]


def test_created_account_ignores_an_injected_role(mu_isolated_root, monkeypatch):
    from deeptutor.multi_user.identity import get_user

    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users)

    response = client.post(
        f"/api/multi-user/groups/{group_id}/members",
        headers=_auth("lead-token"),
        json={
            "username": "sneaky",
            "password": "sneaky-password",
            "role": "admin",
            "preset": "learner",
        },
    )

    assert response.status_code == 201
    assert get_user("sneaky")["role"] == "user"
    assert get_user("sneaky")["preset"] == "standard"


def test_duplicate_username_is_refused(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users)

    response = client.post(
        f"/api/multi-user/groups/{group_id}/members",
        headers=_auth("lead-token"),
        json={"username": "member", "password": "another-password"},
    )

    assert response.status_code == 409


def test_outsider_cannot_create_accounts_in_the_group(mu_isolated_root, monkeypatch):
    from deeptutor.multi_user.identity import get_user

    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users)

    response = client.post(
        f"/api/multi-user/groups/{group_id}/members",
        headers=_auth("outsider-token"),
        json={"username": "ghost", "password": "ghost-password"},
    )

    assert response.status_code == 403
    assert get_user("ghost") is None


def test_lead_removes_a_member_without_deleting_the_account(mu_isolated_root, monkeypatch):
    from deeptutor.multi_user.identity import get_user

    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users, members=(users["member"]["id"],))

    removed = client.delete(
        f"/api/multi-user/groups/{group_id}/members/member",
        headers=_auth("lead-token"),
    )

    assert removed.status_code == 200
    assert removed.json()["group"]["member_user_ids"] == []
    assert get_user("member") is not None, "removal must not delete the account"


def test_lead_cannot_remove_someone_outside_the_group(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users)

    response = client.delete(
        f"/api/multi-user/groups/{group_id}/members/outsider",
        headers=_auth("lead-token"),
    )

    assert response.status_code == 403


def test_lead_assigns_only_resources_they_hold(mu_isolated_root, monkeypatch):
    from deeptutor.multi_user.grants import load_grant

    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users, members=(users["member"]["id"],))

    ok = client.put(
        f"/api/multi-user/groups/{group_id}/members/member/grants",
        headers=_auth("lead-token"),
        json={
            "models": [{"profile_id": "p1", "model_ids": ["m1"]}],
            "knowledge_bases": [{"name": "kb1"}],
            "skills": [{"skill_id": "s1"}],
        },
    )
    assert ok.status_code == 200

    member_grant = load_grant(users["member"]["id"])
    assert member_grant["models"]["llm"] == [{"profile_id": "p1", "model_ids": ["m1"]}]
    assert member_grant["knowledge_bases"] == [{"name": "kb1"}]

    denied = client.put(
        f"/api/multi-user/groups/{group_id}/members/member/grants",
        headers=_auth("lead-token"),
        json={"models": [{"profile_id": "p2", "model_ids": ["m9"]}]},
    )
    assert denied.status_code == 403, "a lead must not hand out a resource they lack"


def test_lead_cannot_assign_a_model_they_only_partly_hold(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users, members=(users["member"]["id"],))

    response = client.put(
        f"/api/multi-user/groups/{group_id}/members/member/grants",
        headers=_auth("lead-token"),
        json={"models": [{"profile_id": "p1", "model_ids": ["m1", "m2"]}]},
    )

    assert response.status_code == 403


def test_lead_cannot_touch_execution_or_learning_policy(mu_isolated_root, monkeypatch):
    from deeptutor.multi_user.grants import load_grant

    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users, members=(users["member"]["id"],))

    response = client.put(
        f"/api/multi-user/groups/{group_id}/members/member/grants",
        headers=_auth("lead-token"),
        json={
            "skills": [{"skill_id": "s1"}],
            "exec_enabled": True,
            "learning_policy": {"allowed_capabilities": ["chat"]},
        },
    )

    assert response.status_code == 200
    grant = load_grant(users["member"]["id"])
    assert grant["exec_enabled"] is None, "exec is an admin switch, not a lead one"
    assert grant["learning_policy"] is None


def test_lead_cannot_assign_grants_outside_their_group(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users)

    response = client.put(
        f"/api/multi-user/groups/{group_id}/members/outsider/grants",
        headers=_auth("lead-token"),
        json={"skills": [{"skill_id": "s1"}]},
    )

    assert response.status_code == 403


def test_report_carries_status_but_no_conversation_content(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    group_id = _group_with(client, users, members=(users["member"]["id"],))

    body = client.get(
        f"/api/multi-user/groups/{group_id}/report", headers=_auth("lead-token")
    ).json()

    by_name = {entry["username"]: entry for entry in body["members"]}
    assert set(by_name) == {"lead", "member"}
    for entry in body["members"]:
        assert set(entry) == {
            "user_id",
            "username",
            "role",
            "preset",
            "disabled",
            "must_change_password",
            "grant_summary",
            "last_active_at",
        }, "status only — never conversation content"
