from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _client(mu_isolated_root, monkeypatch) -> tuple[TestClient, dict]:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import multi_user as multi_user_router
    from deeptutor.book import engine as engine_module
    from deeptutor.book import storage as storage_module
    from deeptutor.book.models import Book
    from deeptutor.book.storage import BookStorage
    from deeptutor.multi_user.identity import save_user
    from deeptutor.multi_user.paths import get_admin_path_service
    from deeptutor.services.auth import TokenPayload, hash_password

    root = save_user("root", hash_password("root-password"), role="admin")
    guardian = save_user("guardian", hash_password("guardian-password"))
    learner = save_user("learner", hash_password("learner-password"), preset="learner")
    stranger = save_user("stranger", hash_password("stranger-password"))
    tokens = {
        "root-token": TokenPayload(username="root", role="admin", user_id=root["id"]),
        "guardian-token": TokenPayload(username="guardian", role="user", user_id=guardian["id"]),
        "learner-token": TokenPayload(username="learner", role="user", user_id=learner["id"]),
        "stranger-token": TokenPayload(username="stranger", role="user", user_id=stranger["id"]),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", False)

    storage_module._storages.clear()
    engine_module._engines.clear()
    BookStorage(path_service=get_admin_path_service()).save_book(
        Book(id="bk_approved", title="Approved")
    )
    BookStorage(path_service=get_admin_path_service()).save_book(
        Book(id="bk_private", title="Private")
    )

    app = FastAPI()
    app.include_router(multi_user_router.router, prefix="/api/multi-user")
    return TestClient(app), {
        "root": root,
        "guardian": guardian,
        "learner": learner,
    }


def test_admin_can_authorize_and_revoke_guardians(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    guardian_id = users["guardian"]["id"]
    learner_id = users["learner"]["id"]

    self_relation = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": guardian_id,
            "learner_user_id": guardian_id,
            "permissions": ["view_reports"],
        },
    )
    assert self_relation.status_code == 400

    admin_target = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["root"]["id"],
            "learner_user_id": learner_id,
            "permissions": ["view_reports"],
        },
    )
    assert admin_target.status_code == 403

    non_learner_target = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": guardian_id,
            "learner_user_id": users["guardian"]["id"],
            "permissions": ["view_reports"],
        },
    )
    assert non_learner_target.status_code == 400
    assert "requires a learner account" in non_learner_target.json()["detail"]

    learner_as_guardian = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": learner_id,
            "learner_user_id": learner_id,
            "permissions": ["view_reports"],
        },
    )
    assert learner_as_guardian.status_code == 400
    assert "cannot be guardians" in learner_as_guardian.json()["detail"]

    created = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={"guardian_user_id": guardian_id, "learner_user_id": learner_id},
    )
    assert created.status_code == 201
    relationship = created.json()["relationship"]
    assert relationship["guardian_username"] == "guardian"
    assert relationship["learner_username"] == "learner"
    assert relationship["revoked_at"] is None

    duplicate = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={"guardian_user_id": guardian_id, "learner_user_id": learner_id},
    )
    assert duplicate.status_code == 409

    reverse = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={"guardian_user_id": learner_id, "learner_user_id": guardian_id},
    )
    assert reverse.status_code == 400

    mine = client.get("/api/multi-user/me/guardianships", headers=_auth("guardian-token"))
    assert mine.status_code == 200
    assert mine.json()["relationships"][0]["id"] == relationship["id"]

    self_revoked = client.delete(
        f"/api/multi-user/me/guardianships/{relationship['id']}",
        headers=_auth("guardian-token"),
    )
    assert self_revoked.status_code == 200
    assert self_revoked.json()["relationship"]["revocation_reason"] == "self_revoked"
    assert (
        client.get("/api/multi-user/me/guardianships", headers=_auth("guardian-token")).json()[
            "relationships"
        ]
        == []
    )

    replacement = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={"guardian_user_id": guardian_id, "learner_user_id": learner_id},
    ).json()["relationship"]

    revoked = client.delete(
        f"/api/multi-user/guardians/{replacement['id']}",
        headers=_auth("root-token"),
    )
    assert revoked.status_code == 200
    assert revoked.json()["relationship"]["revoked_at"] is not None
    assert (
        client.get("/api/multi-user/me/guardianships", headers=_auth("guardian-token")).json()[
            "relationships"
        ]
        == []
    )
    assert (
        client.get(
            "/api/multi-user/guardians",
            headers=_auth("root-token"),
        ).json()["relationships"]
        == []
    )
    history = client.get(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        params={"include_revoked": True},
    ).json()["relationships"]
    assert len(history) == 2


def test_guardian_report_requires_active_relationship_and_is_audited(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    guardian_id = users["guardian"]["id"]
    learner_id = users["learner"]["id"]
    report_url = f"/api/multi-user/learners/{learner_id}/guardian-report"

    assert client.get(report_url, headers=_auth("stranger-token")).status_code == 403
    assert client.get(report_url, headers=_auth("learner-token")).status_code == 403
    assert client.get(report_url, headers=_auth("guardian-token")).status_code == 403

    created = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": guardian_id,
            "learner_user_id": learner_id,
            "permissions": ["view_reports"],
        },
    )
    assert created.status_code == 201

    report = client.get(report_url, headers=_auth("guardian-token"))
    assert report.status_code == 200
    body = report.json()
    assert body["learner"]["username"] == "learner"
    assert body["assigned_materials"] == []
    assert body["book_permission"]["default"] == "none"

    audit_path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    report_event = next(event for event in events if event["action"] == "guardian_report_view")
    assert report_event["guardian_user_id"] == guardian_id
    assert report_event["learner_user_id"] == learner_id
    assert "learner-password" not in audit_path.read_text()


def test_guardian_can_assign_only_read_access_to_approved_books(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    learner_id = users["learner"]["id"]
    created = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["guardian"]["id"],
            "learner_user_id": learner_id,
            "permissions": ["assign_materials", "view_reports"],
        },
    )
    assert created.status_code == 201

    materials_url = f"/api/multi-user/learners/{learner_id}/materials"
    denied = client.put(materials_url, headers=_auth("stranger-token"), json={"book_ids": []})
    assert denied.status_code == 403
    unknown = client.put(
        materials_url,
        headers=_auth("guardian-token"),
        json={"book_ids": ["bk_missing"]},
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == "Unknown approved book id: bk_missing"

    assigned = client.put(
        materials_url,
        headers=_auth("guardian-token"),
        json={"book_ids": ["bk_private", "bk_approved"]},
    )
    assert assigned.status_code == 200
    permission = assigned.json()["book_permission"]
    assert permission["books"] == {"bk_private": "read", "bk_approved": "read"}
    assert permission["create"] is True
    assert permission["default"] == "none"

    catalog = client.get(materials_url, headers=_auth("guardian-token"))
    assert catalog.status_code == 200
    assert {item["book_id"] for item in catalog.json()["materials"] if item["assigned"]} == {
        "bk_private",
        "bk_approved",
    }

    from deeptutor.multi_user.book_permission import BookPermission
    from deeptutor.multi_user.identity import set_book_permission

    assert set_book_permission("learner", BookPermission(create=True, default="read"))
    narrowed = client.put(
        materials_url,
        headers=_auth("guardian-token"),
        json={"book_ids": ["bk_approved"]},
    )
    assert narrowed.status_code == 200
    assert narrowed.json()["book_permission"]["default"] == "read"
    assert narrowed.json()["book_permission"]["books"] == {"bk_private": "none"}

    report = client.get(
        f"/api/multi-user/learners/{learner_id}/guardian-report",
        headers=_auth("guardian-token"),
    )
    assert report.status_code == 200
    assert {item["book_id"] for item in report.json()["assigned_materials"]} == {
        "bk_approved",
    }

    reset = client.post(
        f"/api/multi-user/learners/{learner_id}/credentials/reset",
        headers=_auth("guardian-token"),
        json={"new_password": "replacement-password"},
    )
    assert reset.status_code == 403


def test_guardian_can_adjust_only_the_exposed_learning_restrictions(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    learner_id = users["learner"]["id"]
    created = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["guardian"]["id"],
            "learner_user_id": learner_id,
            "permissions": ["manage_restrictions"],
        },
    )
    assert created.status_code == 201

    url = f"/api/multi-user/learners/{learner_id}/restrictions"
    assert client.get(url, headers=_auth("stranger-token")).status_code == 403
    before = client.get(url, headers=_auth("guardian-token"))
    assert before.status_code == 200
    assert before.json()["restrictions"]["age_band"] == "9-12"

    changed = client.put(
        url,
        headers=_auth("guardian-token"),
        json={
            "age_band": "13-15",
            "allow_upload": True,
            "allowed_surfaces": ["reading"],
            "extensions": [],
        },
    )
    assert changed.status_code == 200
    assert changed.json()["restrictions"] == {
        "age_band": "13-15",
        "allow_upload": True,
        "allowed_surfaces": ["reading"],
        "extensions": [],
    }

    from deeptutor.multi_user.grants import load_grant

    grant = load_grant(learner_id)
    assert grant["learning_policy"]["allowed_capabilities"] == [
        "chat",
        "immersive_reading",
    ]
    assert grant["learning_policy"]["reading"]["material_ids"] == []


def test_guardian_can_reset_local_credentials_without_returning_or_auditing_secret(
    mu_isolated_root, monkeypatch
):
    client, users = _client(mu_isolated_root, monkeypatch)
    learner_id = users["learner"]["id"]
    created = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["guardian"]["id"],
            "learner_user_id": learner_id,
            "permissions": ["reset_credentials"],
        },
    )
    assert created.status_code == 201

    from deeptutor.api.routers import multi_user as multi_user_router
    from deeptutor.multi_user.device_credentials import (
        begin_device_session,
        issue_device_credential,
        validate_device_token,
    )
    from deeptutor.services.auth import verify_password

    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", True)
    unsupported = client.post(
        f"/api/multi-user/learners/{learner_id}/credentials/reset",
        headers=_auth("guardian-token"),
        json={"new_password": "replacement-password"},
    )
    assert unsupported.status_code == 400
    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", False)

    _device, pairing_code, pin = issue_device_credential(
        user_id=learner_id,
        device_name="Learner tablet",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        daily_limit_minutes=30,
    )
    session = begin_device_session(pairing_code, pin)
    assert session is not None
    device, _username, _role, _user_id, session_nonce = session
    assert validate_device_token(learner_id, device["id"], session_nonce) is True

    reset = client.post(
        f"/api/multi-user/learners/{learner_id}/credentials/reset",
        headers=_auth("guardian-token"),
        json={"new_password": "replacement-password"},
    )
    assert reset.status_code == 200
    assert reset.json()["ok"] is True
    assert "temporary_password" not in reset.json()
    assert "new_password" not in reset.json()

    from deeptutor.multi_user.identity import load_users

    learner_hash = load_users()["learner"]["hash"]
    assert verify_password("learner-password", learner_hash) is False
    assert verify_password("replacement-password", learner_hash) is True
    assert validate_device_token(learner_id, device["id"], session_nonce) is False

    audit_path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    assert "replacement-password" not in audit_path.read_text()

    admin_reset = client.post(
        f"/api/multi-user/learners/{learner_id}/credentials/reset",
        headers=_auth("root-token"),
        json={"new_password": "admin-replacement-password"},
    )
    assert admin_reset.status_code == 200
    learner_hash = load_users()["learner"]["hash"]
    assert verify_password("admin-replacement-password", learner_hash) is True
    assert "admin-replacement-password" not in audit_path.read_text()


def test_user_deletion_revokes_related_guardian_records(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    created = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["guardian"]["id"],
            "learner_user_id": users["learner"]["id"],
            "permissions": ["view_reports"],
        },
    )
    assert created.status_code == 201

    from deeptutor.multi_user.identity import delete_user

    assert delete_user("learner") is True
    history = client.get(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        params={"include_revoked": True},
    ).json()["relationships"]
    assert len(history) == 1
    assert history[0]["revoked_at"] is not None
    assert history[0]["revocation_reason"] == "user_deleted"


def test_guardian_access_rechecks_the_current_account_presets(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    learner_id = users["learner"]["id"]
    created = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["guardian"]["id"],
            "learner_user_id": learner_id,
            "permissions": ["view_reports"],
        },
    )
    assert created.status_code == 201

    from deeptutor.multi_user.identity import set_preset

    assert set_preset("learner", "standard") is True
    report = client.get(
        f"/api/multi-user/learners/{learner_id}/guardian-report",
        headers=_auth("guardian-token"),
    )
    assert report.status_code == 403
