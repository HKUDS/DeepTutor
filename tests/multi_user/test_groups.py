"""Group (cohort) tests: admin-managed groups with a scoped lead.

A group is an administrative container, not an RBAC role: one ordinary user is
nominated as its lead and may manage that group's roster, reset a member's
password and read the group report — without ever becoming an admin. The tests
pin both directions: what the lead can do, and exactly where that stops.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _client(mu_isolated_root, monkeypatch) -> tuple[TestClient, dict]:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import multi_user as multi_user_router
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload, hash_password

    root = save_user("root", hash_password("root-password"), role="admin")
    lead = save_user("lead", hash_password("lead-password"))
    member = save_user("member", hash_password("member-password"))
    stranger = save_user("stranger", hash_password("stranger-password"))
    tokens = {
        "root-token": TokenPayload(username="root", role="admin", user_id=root["id"]),
        "lead-token": TokenPayload(username="lead", role="user", user_id=lead["id"]),
        "member-token": TokenPayload(username="member", role="user", user_id=member["id"]),
        "stranger-token": TokenPayload(username="stranger", role="user", user_id=stranger["id"]),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", False)

    app = FastAPI()
    app.include_router(multi_user_router.router, prefix="/api/multi-user")
    return TestClient(app), {
        "root": root,
        "lead": lead,
        "member": member,
        "stranger": stranger,
    }


def _seed_people() -> dict[str, dict]:
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import hash_password

    return {
        "admin": save_user("boss", hash_password("boss-password"), role="admin"),
        "lead": save_user("lead2", hash_password("lead2-password")),
        "other": save_user("other", hash_password("other-password")),
        "m1": save_user("m1", hash_password("m1-password")),
        "m2": save_user("m2", hash_password("m2-password")),
    }


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------


def test_group_rejects_admin_accounts(mu_isolated_root):
    """Admins already own the workspace; a group that could contain one would
    turn the lead's scoped power into a path to an admin account."""
    from deeptutor.multi_user.groups import create_group

    people = _seed_people()

    with pytest.raises(ValueError):
        create_group(
            "Team",
            lead_user_id=people["admin"]["id"],
            created_by=people["admin"]["id"],
        )
    with pytest.raises(ValueError):
        create_group(
            "Team",
            lead_user_id=people["lead"]["id"],
            member_user_ids=[people["admin"]["id"]],
            created_by=people["admin"]["id"],
        )


def test_group_drops_duplicate_and_lead_entries(mu_isolated_root):
    from deeptutor.multi_user.groups import create_group

    people = _seed_people()
    group = create_group(
        "Team",
        lead_user_id=people["lead"]["id"],
        member_user_ids=[
            people["m1"]["id"],
            people["m2"]["id"],
            people["m1"]["id"],
            people["lead"]["id"],
        ],
        created_by=people["admin"]["id"],
    )

    assert group["member_user_ids"] == [people["m1"]["id"], people["m2"]["id"]]
    assert group["lead_user_id"] == people["lead"]["id"]


def test_group_name_is_validated(mu_isolated_root):
    from deeptutor.multi_user.groups import create_group

    people = _seed_people()
    for bad_name in ("", "   ", "x" * 65, "bad\nname"):
        with pytest.raises(ValueError):
            create_group(
                bad_name,
                lead_user_id=people["lead"]["id"],
                created_by=people["admin"]["id"],
            )


def test_groups_led_by_is_scoped_to_the_lead(mu_isolated_root):
    from deeptutor.multi_user.groups import create_group, delete_group, get_group, groups_led_by

    people = _seed_people()
    mine = create_group("Mine", lead_user_id=people["lead"]["id"], created_by=people["admin"]["id"])
    theirs = create_group(
        "Theirs", lead_user_id=people["other"]["id"], created_by=people["admin"]["id"]
    )

    assert [g["id"] for g in groups_led_by(people["lead"]["id"])] == [mine["id"]]
    assert [g["id"] for g in groups_led_by(people["other"]["id"])] == [theirs["id"]]
    assert groups_led_by(people["m1"]["id"]) == []

    assert delete_group(mine["id"]) is True
    assert get_group(mine["id"]) is None
    assert delete_group("g_missing") is False


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


def test_admin_creates_group_and_lead_manages_its_roster(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)

    created = client.post(
        "/api/multi-user/groups",
        headers=_auth("root-token"),
        json={"name": "Team A", "lead_user_id": users["lead"]["id"]},
    )
    assert created.status_code == 201
    group_id = created.json()["group"]["id"]

    listed = client.get("/api/multi-user/groups", headers=_auth("lead-token"))
    assert listed.status_code == 200
    assert [g["id"] for g in listed.json()["groups"]] == [group_id]

    updated = client.put(
        f"/api/multi-user/groups/{group_id}/members",
        headers=_auth("lead-token"),
        json={"member_user_ids": [users["member"]["id"]]},
    )
    assert updated.status_code == 200
    assert updated.json()["group"]["member_user_ids"] == [users["member"]["id"]]

    roster = client.get(f"/api/multi-user/groups/{group_id}", headers=_auth("lead-token")).json()[
        "group"
    ]
    assert roster["lead"]["username"] == "lead"
    assert [m["username"] for m in roster["members"]] == ["member"]


def test_admin_sees_every_group_while_a_stranger_sees_none(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)

    client.post(
        "/api/multi-user/groups",
        headers=_auth("root-token"),
        json={"name": "Team A", "lead_user_id": users["lead"]["id"]},
    )

    admin_view = client.get("/api/multi-user/groups", headers=_auth("root-token")).json()
    assert len(admin_view["groups"]) == 1

    stranger_view = client.get("/api/multi-user/groups", headers=_auth("stranger-token")).json()
    assert stranger_view["groups"] == []


def test_only_the_lead_or_an_admin_may_change_the_roster(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)

    group_id = client.post(
        "/api/multi-user/groups",
        headers=_auth("root-token"),
        json={"name": "Team A", "lead_user_id": users["lead"]["id"]},
    ).json()["group"]["id"]

    denied = client.put(
        f"/api/multi-user/groups/{group_id}/members",
        headers=_auth("stranger-token"),
        json={"member_user_ids": [users["stranger"]["id"]]},
    )
    assert denied.status_code == 403

    # The member is inside the group, but that grants no authority over it.
    client.put(
        f"/api/multi-user/groups/{group_id}/members",
        headers=_auth("lead-token"),
        json={"member_user_ids": [users["member"]["id"]]},
    )
    by_member = client.put(
        f"/api/multi-user/groups/{group_id}/members",
        headers=_auth("member-token"),
        json={"member_user_ids": []},
    )
    assert by_member.status_code == 403


def test_lead_resets_a_member_password_but_never_an_admin(mu_isolated_root, monkeypatch):
    from deeptutor.multi_user.identity import get_user

    client, users = _client(mu_isolated_root, monkeypatch)
    before = get_user("member")["hash"]

    group_id = client.post(
        "/api/multi-user/groups",
        headers=_auth("root-token"),
        json={
            "name": "Team A",
            "lead_user_id": users["lead"]["id"],
            "member_user_ids": [users["member"]["id"]],
        },
    ).json()["group"]["id"]

    reset = client.put(
        f"/api/multi-user/groups/{group_id}/members/member/password",
        headers=_auth("lead-token"),
        json={"new_password": "brand-new-pass"},
    )
    assert reset.status_code == 200
    assert get_user("member")["hash"] != before

    # An admin account is not a group member, and must stay out of reach.
    assert (
        client.put(
            f"/api/multi-user/groups/{group_id}/members/root/password",
            headers=_auth("lead-token"),
            json={"new_password": "brand-new-pass"},
        ).status_code
        == 403
    )


def test_group_report_reports_status_not_conversation_content(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)

    group_id = client.post(
        "/api/multi-user/groups",
        headers=_auth("root-token"),
        json={
            "name": "Team A",
            "lead_user_id": users["lead"]["id"],
            "member_user_ids": [users["member"]["id"]],
        },
    ).json()["group"]["id"]

    report = client.get(f"/api/multi-user/groups/{group_id}/report", headers=_auth("lead-token"))
    assert report.status_code == 200
    body = report.json()

    assert body["group"]["id"] == group_id
    assert {entry["username"] for entry in body["members"]} == {"lead", "member"}
    for entry in body["members"]:
        assert set(entry) == {
            "user_id",
            "username",
            "role",
            "preset",
            "disabled",
            "must_change_password",
            "last_active_at",
            "grant_summary",
        }, "the report must describe accounts, never their conversation content"

    assert (
        client.get(
            f"/api/multi-user/groups/{group_id}/report",
            headers=_auth("stranger-token"),
        ).status_code
        == 403
    )


def test_group_management_is_admin_only(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)

    created = client.post(
        "/api/multi-user/groups",
        headers=_auth("root-token"),
        json={"name": "Team A", "lead_user_id": users["lead"]["id"]},
    ).json()["group"]["id"]

    assert (
        client.post(
            "/api/multi-user/groups",
            headers=_auth("lead-token"),
            json={"name": "Team B", "lead_user_id": users["lead"]["id"]},
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/multi-user/groups/{created}", headers=_auth("lead-token")).status_code
        == 403
    )
    assert (
        client.delete(f"/api/multi-user/groups/{created}", headers=_auth("root-token")).status_code
        == 200
    )
