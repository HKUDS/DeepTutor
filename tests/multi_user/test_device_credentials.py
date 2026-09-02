from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _client(mu_isolated_root, monkeypatch) -> tuple[TestClient, dict]:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import create_token, hash_password

    admin = save_user("root", hash_password("root-password"), role="admin")
    learner = save_user("learner", hash_password("learner-password"), preset="learner")
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "device-credential-test-secret")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    client = TestClient(app)
    return client, {
        "admin": admin,
        "learner": learner,
        "admin_token": create_token("root", "admin", admin["id"]),
    }


def test_admin_issue_lists_and_secrets_are_not_persisted(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    learner_id = users["learner"]["id"]

    created = client.post(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
        json={
            "user_id": learner_id,
            "device_name": "Learner tablet",
            "expires_in_days": 30,
            "daily_limit_minutes": 30,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["pairing_code"].startswith("dc_")
    assert len(body["pin"]) == 6 and body["pin"].isdigit()
    assert body["device"]["user_id"] == learner_id
    assert body["device"]["daily_limit_minutes"] == 30

    listed = client.get(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
    )
    assert listed.status_code == 200
    device = listed.json()["devices"][0]
    assert device["username"] == "learner"
    assert "pairing_code_hash" not in device
    assert "pin_hash" not in device

    stored = mu_isolated_root.joinpath(
        "data", "system", "auth", "device_credentials.json"
    ).read_text(encoding="utf-8")
    assert body["pairing_code"] not in stored
    assert body["pin"] not in stored
    audit = mu_isolated_root.joinpath("data", "system", "audit", "usage.jsonl").read_text(
        encoding="utf-8"
    )
    assert body["pairing_code"] not in audit
    assert body["pin"] not in audit


def test_only_admins_can_issue_device_credentials(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    from deeptutor.services.auth import create_token

    learner_token = create_token(
        "learner",
        "user",
        users["learner"]["id"],
    )
    denied = client.post(
        "/api/auth/devices",
        headers=_auth(learner_token),
        json={
            "user_id": users["learner"]["id"],
            "device_name": "Learner tablet",
            "expires_in_days": 30,
            "daily_limit_minutes": 30,
        },
    )
    assert denied.status_code == 403

    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import hash_password

    standard = save_user("standard", hash_password("standard-password"))
    wrong_preset = client.post(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
        json={
            "user_id": standard["id"],
            "device_name": "Standard tablet",
            "expires_in_days": 30,
            "daily_limit_minutes": 30,
        },
    )
    assert wrong_preset.status_code == 400
    assert "learner" in wrong_preset.json()["detail"]


def test_only_admins_can_list_and_revoke_device_credentials(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    from deeptutor.services.auth import create_token

    learner_token = create_token(
        "learner",
        "user",
        users["learner"]["id"],
    )
    empty = client.get("/api/auth/devices", headers=_auth(users["admin_token"]))
    assert empty.status_code == 200
    assert empty.json() == {"devices": []}

    assert client.get("/api/auth/devices", headers=_auth(learner_token)).status_code == 403
    assert (
        client.delete(
            "/api/auth/devices/dc_missing",
            headers=_auth(learner_token),
        ).status_code
        == 403
    )
    assert (
        client.delete(
            "/api/auth/devices/dc_missing",
            headers=_auth(users["admin_token"]),
        ).status_code
        == 404
    )


def test_device_login_returns_normal_identity_and_revocation_invalidates_token(
    mu_isolated_root, monkeypatch
):
    client, users = _client(mu_isolated_root, monkeypatch)
    learner_id = users["learner"]["id"]
    issued = client.post(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
        json={
            "user_id": learner_id,
            "device_name": "Learner tablet",
            "expires_in_days": 30,
            "daily_limit_minutes": 30,
        },
    ).json()

    unknown_code = client.post(
        "/api/auth/device-login",
        json={"pairing_code": "dc_not-real", "pin": "123456"},
    )
    assert unknown_code.status_code == 401

    wrong_pin = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": "000000"},
    )
    assert wrong_pin.status_code == 401

    login = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["username"] == "learner"
    assert body["role"] == "user"
    token = login.cookies["dt_token"]

    status = client.get("/api/auth/status", headers=_auth(token))
    assert status.status_code == 200
    assert status.json()["username"] == "learner"

    revoked = client.delete(
        f"/api/auth/devices/{issued['device']['id']}",
        headers=_auth(users["admin_token"]),
    )
    assert revoked.status_code == 200
    revoked_status = client.get("/api/auth/status", headers=_auth(token))
    assert revoked_status.status_code == 200
    assert revoked_status.json()["authenticated"] is False
    assert (
        client.post(
            "/api/auth/device-login",
            json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
        ).status_code
        == 401
    )


def test_relogin_rotates_the_lease_and_charges_elapsed_usage(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    issued = client.post(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
        json={
            "user_id": users["learner"]["id"],
            "device_name": "Learner tablet",
            "expires_in_days": 30,
            "daily_limit_minutes": 30,
        },
    ).json()
    first = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    first_token = first.cookies["dt_token"]
    started = datetime.fromisoformat(
        client.get("/api/auth/devices", headers=_auth(users["admin_token"])).json()["devices"][0][
            "last_heartbeat_at"
        ]
    )

    from deeptutor.multi_user import device_credentials

    monkeypatch.setattr(device_credentials, "utc_now", lambda: _add_seconds(started, 60))
    second = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    assert second.status_code == 200
    second_token = second.cookies["dt_token"]

    first_status = client.get("/api/auth/status", headers=_auth(first_token))
    assert first_status.json()["authenticated"] is False
    assert (
        client.get("/api/auth/status", headers=_auth(second_token)).json()["authenticated"] is True
    )
    listed = client.get("/api/auth/devices", headers=_auth(users["admin_token"])).json()["devices"]
    assert listed[0]["used_seconds"] == 60


def test_pin_failures_are_rate_limited(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    issued = client.post(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
        json={
            "user_id": users["learner"]["id"],
            "device_name": "Learner tablet",
            "expires_in_days": 30,
            "daily_limit_minutes": 30,
        },
    ).json()
    wrong_pin = "000001" if issued["pin"] == "000000" else "000000"
    for _ in range(5):
        denied = client.post(
            "/api/auth/device-login",
            json={"pairing_code": issued["pairing_code"], "pin": wrong_pin},
        )
        assert denied.status_code == 401

    locked = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    assert locked.status_code == 401

    from deeptutor.multi_user import device_credentials

    records = json.loads(device_credentials.DEVICE_CREDENTIALS_FILE.read_text())
    locked_until = datetime.fromisoformat(records[0]["pin_locked_until"])
    monkeypatch.setattr(
        device_credentials,
        "utc_now",
        lambda: locked_until + timedelta(seconds=1),
    )
    recovered = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    assert recovered.status_code == 200


def test_expired_and_deleted_accounts_fail_closed(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    learner_id = users["learner"]["id"]
    issued = client.post(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
        json={
            "user_id": learner_id,
            "device_name": "Learner tablet",
            "expires_in_days": 1,
            "daily_limit_minutes": 30,
        },
    ).json()

    from deeptutor.multi_user import device_credentials

    real_now = device_credentials.utc_now
    future = datetime.fromisoformat(issued["device"]["expires_at"])
    if future.tzinfo is None:
        future = future.replace(tzinfo=timezone.utc)
    monkeypatch.setattr(device_credentials, "utc_now", lambda: future + timedelta(seconds=1))
    assert (
        client.post(
            "/api/auth/device-login",
            json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
        ).status_code
        == 401
    )
    monkeypatch.setattr(device_credentials, "utc_now", real_now)

    login = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    assert login.status_code == 200
    token = login.cookies["dt_token"]

    monkeypatch.setattr(device_credentials, "utc_now", lambda: future + timedelta(seconds=1))
    expired_status = client.get("/api/auth/status", headers=_auth(token))
    assert expired_status.status_code == 200
    assert expired_status.json()["authenticated"] is False
    monkeypatch.setattr(device_credentials, "utc_now", real_now)

    from deeptutor.multi_user.identity import delete_user

    assert delete_user("learner") is True
    deleted_status = client.get("/api/auth/status", headers=_auth(token))
    assert deleted_status.status_code == 200
    assert deleted_status.json()["authenticated"] is False


def test_disabled_account_fails_closed(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    issued = client.post(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
        json={
            "user_id": users["learner"]["id"],
            "device_name": "Learner tablet",
            "expires_in_days": 30,
            "daily_limit_minutes": 30,
        },
    ).json()
    login = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    assert login.status_code == 200
    token = login.cookies["dt_token"]

    from deeptutor.multi_user import identity

    users_on_disk = json.loads(identity.USERS_FILE.read_text(encoding="utf-8"))
    users_on_disk["learner"]["disabled"] = True
    identity.USERS_FILE.write_text(json.dumps(users_on_disk), encoding="utf-8")

    assert (
        client.post(
            "/api/auth/device-login",
            json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
        ).status_code
        == 401
    )
    disabled_status = client.get("/api/auth/status", headers=_auth(token))
    assert disabled_status.status_code == 200
    assert disabled_status.json()["authenticated"] is False


def test_heartbeat_enforces_freshness_daily_limit_and_day_rollover(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    learner_id = users["learner"]["id"]
    issued = client.post(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
        json={
            "user_id": learner_id,
            "device_name": "Learner tablet",
            "expires_in_days": 30,
            "daily_limit_minutes": 5,
        },
    ).json()
    login = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    assert login.status_code == 200
    token = login.cookies["dt_token"]

    listed = client.get(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
    ).json()["devices"]
    started = datetime.fromisoformat(listed[0]["last_heartbeat_at"])

    from deeptutor.multi_user import device_credentials

    monkeypatch.setattr(device_credentials, "utc_now", lambda: started)
    first = client.post("/api/auth/device/heartbeat", headers=_auth(token))
    assert first.status_code == 200
    assert first.json()["remaining_seconds"] == 300

    monkeypatch.setattr(device_credentials, "utc_now", lambda: _add_seconds(started, 60))
    second = client.post("/api/auth/device/heartbeat", headers=_auth(token))
    assert second.status_code == 200
    assert second.json()["used_seconds"] == 60
    assert client.get("/api/auth/status", headers=_auth(token)).status_code == 200

    monkeypatch.setattr(device_credentials, "utc_now", lambda: _add_seconds(started, 300))
    limited = client.post("/api/auth/device/heartbeat", headers=_auth(token))
    assert limited.status_code == 200
    assert limited.json()["ok"] is False
    assert limited.json()["remaining_seconds"] == 0
    limited_status = client.get("/api/auth/status", headers=_auth(token))
    assert limited_status.status_code == 200
    assert limited_status.json()["authenticated"] is False
    assert (
        client.post(
            "/api/auth/device-login",
            json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
        ).status_code
        == 401
    )

    monkeypatch.setattr(device_credentials, "utc_now", lambda: _add_seconds(started, 86_400))
    rolled = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    assert rolled.status_code == 200
    rolled_list = client.get(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
    ).json()["devices"]
    assert rolled_list[0]["used_seconds"] == 0


def test_stale_heartbeat_cannot_access_authenticated_api(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    learner_id = users["learner"]["id"]
    issued = client.post(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
        json={
            "user_id": learner_id,
            "device_name": "Learner tablet",
            "expires_in_days": 30,
            "daily_limit_minutes": 30,
        },
    ).json()
    login = client.post(
        "/api/auth/device-login",
        json={"pairing_code": issued["pairing_code"], "pin": issued["pin"]},
    )
    token = login.cookies["dt_token"]
    listed = client.get(
        "/api/auth/devices",
        headers=_auth(users["admin_token"]),
    ).json()["devices"]
    started = datetime.fromisoformat(listed[0]["last_heartbeat_at"])

    from deeptutor.multi_user import device_credentials

    monkeypatch.setattr(device_credentials, "utc_now", lambda: _add_seconds(started, 301))
    stale_status = client.get("/api/auth/status", headers=_auth(token))
    assert stale_status.status_code == 200
    assert stale_status.json()["authenticated"] is False
    assert client.post("/api/auth/device/heartbeat", headers=_auth(token)).status_code == 401


def test_pocketbase_mode_rejects_local_device_credentials(mu_isolated_root, monkeypatch):
    client, users = _client(mu_isolated_root, monkeypatch)
    from deeptutor.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", True)
    assert (
        client.post(
            "/api/auth/devices",
            headers=_auth(users["admin_token"]),
            json={
                "user_id": users["learner"]["id"],
                "device_name": "Learner tablet",
                "expires_in_days": 30,
                "daily_limit_minutes": 30,
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/device-login",
            json={"pairing_code": "dc_not-real", "pin": "123456"},
        ).status_code
        == 400
    )


def _add_seconds(value: datetime, seconds: int) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value + timedelta(seconds=seconds)
