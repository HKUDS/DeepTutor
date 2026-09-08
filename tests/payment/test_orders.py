"""Tests for the online order engine (create / notify / fulfill).

These cover the store state machine, gateway signature verification, amount
reconciliation, idempotent fulfillment, and the learner-facing API routes.
Path isolation follows the multi_user tests: every module that derives paths
from ``SYSTEM_ROOT`` is monkey-patched onto a per-test tmp tree, and the
identity/grants stores are pointed at the same tree.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.multi_user import identity
from deeptutor.multi_user import paths as mpaths
from deeptutor.multi_user.grants import load_grant
from deeptutor.payment.gateways import SignatureVerificationError


@pytest.fixture
def payment_env(tmp_path, monkeypatch):
    """Point every payment/multi-user path at a per-test tree and seed users."""
    admin_root = (tmp_path / "data").resolve()
    system_root = admin_root / "system"

    from deeptutor.multi_user import audit, grants
    from deeptutor.payment import gateways, notify, orders, provisioning, service

    for module in (mpaths, identity, grants, audit):
        monkeypatch.setattr(module, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(mpaths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mpaths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(mpaths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(mpaths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(mpaths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "missing-secret")
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")
    monkeypatch.setattr(audit, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(gateways, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(service, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(orders, "SYSTEM_ROOT", system_root)
    # notify/provisioning resolve SYSTEM_ROOT through the modules above; the
    # templates they import (orders/gateways) already carry the patched root.

    # Seed one admin + one learner.
    identity.save_user("root", "hash", role="admin")
    alice = identity.save_user("alice", "hash", role="user", preset="learner")

    # Set the request-local current user to alice for grant writes.
    from deeptutor.multi_user.context import set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    token = set_current_user(
        CurrentUser(
            id=alice["id"],
            username="alice",
            role="user",
            scope=UserScope(
                kind="user", user_id=alice["id"], root=admin_root / "users" / alice["id"]
            ),
        )
    )

    yield {
        "admin_root": admin_root,
        "system_root": system_root,
        "alice": alice,
        "alice_id": alice["id"],
        "monkeypatch": monkeypatch,
    }

    from deeptutor.multi_user.context import reset_current_user

    reset_current_user(token)


def _write_plans(env, plans):
    import json

    service = __import__("deeptutor.payment.service", fromlist=["plans_path"])
    path = service.plans_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"plans": plans}, ensure_ascii=False), encoding="utf-8")


def _write_gateways(env, gateways_dict):
    import json

    gateways = __import__("deeptutor.payment.gateways", fromlist=["gateways_path"])
    path = gateways.gateways_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gateways_dict, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Order store
# ---------------------------------------------------------------------------


def test_create_and_fetch_order(payment_env):
    from deeptutor.payment.orders import create_order, get_order, get_order_by_trade_no

    env = payment_env
    order = create_order(
        user_id=env["alice_id"],
        username="alice",
        plan={"id": "p1", "name": "标准版", "price_fen": 2990},
        gateway="epay",
    )
    assert order["status"] == "pending"
    assert order["amount_fen"] == 2990
    assert order["order_no"].startswith("DT")
    assert order["order_id"].startswith("po_")

    fetched = get_order(order["order_id"])
    assert fetched["order_id"] == order["order_id"]
    assert get_order_by_trade_no(order["order_no"])["order_id"] == order["order_id"]


def test_order_expiry(payment_env):
    from datetime import timedelta

    from deeptutor.payment.orders import (
        create_order,
        expire_stale_orders,
        get_order,
    )

    env = payment_env
    order = create_order(
        user_id=env["alice_id"],
        username="alice",
        plan={"id": "p1", "price_fen": 100},
        gateway="epay",
    )
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    expired = expire_stale_orders(now=now + timedelta(hours=1))
    assert expired >= 1
    assert get_order(order["order_id"])["status"] == "expired"


def test_invalid_transition_rejected(payment_env):
    from deeptutor.payment.orders import (
        OrderError,
        create_order,
        transition_order,
    )

    env = payment_env
    order = create_order(
        user_id=env["alice_id"],
        username="alice",
        plan={"id": "p1", "price_fen": 100},
        gateway="epay",
    )
    with pytest.raises(OrderError):
        transition_order(order["order_id"], "granted")  # pending -> granted is invalid


# ---------------------------------------------------------------------------
# EPay notify + fulfillment
# ---------------------------------------------------------------------------


def test_epay_notify_fulfills_order(payment_env):
    import hashlib

    from deeptutor.payment.gateways import _epay_sign, gateways_path
    from deeptutor.payment.notify import handle_epay_notify
    from deeptutor.payment.orders import create_order, get_order

    env = payment_env
    _write_gateways(
        env,
        {
            "epay": {
                "enabled": True,
                "gateway_url": "https://pay.example.com",
                "pid": "1000",
                "merchant_key": "secret-key",
                "sign_type": "MD5",
            }
        },
    )

    plan = {
        "id": "p1",
        "name": "标准版",
        "price_fen": 2990,
        "duration_days": 365,
        "knowledge_bases": [{"name": "admin:kb:数学"}],
        "models": {"llm": [{"profile_id": "deepseek", "model_ids": ["ds-r1"]}]},
    }
    order = create_order(
        user_id=env["alice_id"],
        username="alice",
        plan=plan,
        gateway="epay",
    )

    params = {
        "pid": "1000",
        "trade_no": "epay-tx-1",
        "out_trade_no": order["order_no"],
        "trade_status": "TRADE_SUCCESS",
        "money": "29.90",
        "name": "标准版",
    }
    params["sign_type"] = "MD5"
    params["sign"] = _epay_sign(params, "secret-key")

    result = handle_epay_notify(params)
    assert result == "success"

    refreshed = get_order(order["order_id"])
    assert refreshed["status"] == "granted"
    assert refreshed["granted_at"] is not None

    # Grant was persisted with the plan's kb + model.
    grant = load_grant(env["alice_id"])
    kb_names = [item.get("name") for item in grant.get("knowledge_bases", [])]
    assert "admin:kb:数学" in kb_names
    assert grant["models"]["llm"][0]["profile_id"] == "deepseek"


def test_epay_notify_wrong_sign_rejected(payment_env):
    from deeptutor.payment.gateways import gateways_path
    from deeptutor.payment.notify import handle_epay_notify
    from deeptutor.payment.orders import create_order

    env = payment_env
    _write_gateways(
        env,
        {
            "epay": {
                "enabled": True,
                "gateway_url": "https://pay.example.com",
                "pid": "1000",
                "merchant_key": "secret-key",
            }
        },
    )
    order = create_order(
        user_id=env["alice_id"],
        username="alice",
        plan={"id": "p1", "price_fen": 100},
        gateway="epay",
    )
    params = {
        "pid": "1000",
        "out_trade_no": order["order_no"],
        "trade_status": "TRADE_SUCCESS",
        "money": "1.00",
        "sign": "deadbeef",
    }
    assert handle_epay_notify(params) == "fail"


def test_epay_notify_amount_mismatch_rejected(payment_env):
    from deeptutor.payment.gateways import _epay_sign, gateways_path
    from deeptutor.payment.notify import handle_epay_notify
    from deeptutor.payment.orders import create_order

    env = payment_env
    _write_gateways(
        env,
        {
            "epay": {
                "enabled": True,
                "gateway_url": "https://pay.example.com",
                "pid": "1000",
                "merchant_key": "secret-key",
            }
        },
    )
    order = create_order(
        user_id=env["alice_id"],
        username="alice",
        plan={"id": "p1", "price_fen": 2990},
        gateway="epay",
    )
    params = {
        "pid": "1000",
        "out_trade_no": order["order_no"],
        "trade_status": "TRADE_SUCCESS",
        "money": "0.01",
    }
    params["sign_type"] = "MD5"
    params["sign"] = _epay_sign(params, "secret-key")
    assert handle_epay_notify(params) == "fail"


def test_epay_duplicate_notify_is_idempotent(payment_env):
    from deeptutor.payment.gateways import _epay_sign, gateways_path
    from deeptutor.payment.notify import handle_epay_notify
    from deeptutor.payment.orders import create_order, get_order, list_orders

    env = payment_env
    _write_gateways(
        env,
        {
            "epay": {
                "enabled": True,
                "gateway_url": "https://pay.example.com",
                "pid": "1000",
                "merchant_key": "secret-key",
            }
        },
    )
    order = create_order(
        user_id=env["alice_id"],
        username="alice",
        plan={"id": "p1", "price_fen": 100},
        gateway="epay",
    )
    params = {
        "pid": "1000",
        "out_trade_no": order["order_no"],
        "trade_status": "TRADE_SUCCESS",
        "money": "1.00",
    }
    params["sign_type"] = "MD5"
    params["sign"] = _epay_sign(params, "secret-key")

    assert handle_epay_notify(params) == "success"
    assert handle_epay_notify(params) == "success"
    refreshed = get_order(order["order_id"])
    assert refreshed["status"] == "granted"
    assert refreshed["notify_count"] == 2  # both callbacks recorded, both OK


# ---------------------------------------------------------------------------
# Provisioning (save_grant + set_book_permission)
# ---------------------------------------------------------------------------


def test_provision_plan_binds_grant_and_books(payment_env):
    from deeptutor.book.engine import BookEngine
    from deeptutor.book.models import Book
    from deeptutor.book.storage import BookStorage
    from deeptutor.multi_user.book_permission import normalize_book_permission
    from deeptutor.multi_user.paths import get_admin_path_service
    from deeptutor.payment.provisioning import provision_plan

    env = payment_env
    # Create a shared admin book.
    from deeptutor.book import engine as engine_module
    from deeptutor.book import storage as storage_module

    storage_module._storages.clear()
    engine_module._engines.clear()
    BookStorage(path_service=get_admin_path_service()).save_book(
        Book(id="bk_shared", title="Shared")
    )

    env["monkeypatch"].setattr(
        identity,
        "get_user_by_id",
        lambda uid: ("alice", {"id": uid, "role": "user", "preset": "learner"}),
    )

    provision_plan(
        plan={
            "id": "p1",
            "name": "标准版",
            "duration_days": 365,
            "books": ["bk_shared"],
            "knowledge_bases": [{"name": "admin:kb:数学"}],
        },
        user_id=env["alice_id"],
        username="alice",
    )

    grant = load_grant(env["alice_id"])
    kb_names = [item.get("name") for item in grant.get("knowledge_bases", [])]
    assert "admin:kb:数学" in kb_names

    # Book permission bound read-only (a logical ACL — access is resolved
    # from the user record, not by copying the book into the learner scope).
    record = identity.get_user("alice") or {}
    perm = normalize_book_permission(record.get("book_permission"))
    assert perm.level_for("bk_shared") == "read"


def test_provision_plan_merges_existing_grant(payment_env):
    from deeptutor.payment.provisioning import provision_plan

    env = payment_env
    provision_plan(
        plan={"id": "p1", "knowledge_bases": [{"name": "admin:kb:甲"}]},
        user_id=env["alice_id"],
        username="alice",
    )
    provision_plan(
        plan={"id": "p2", "knowledge_bases": [{"name": "admin:kb:乙"}]},
        user_id=env["alice_id"],
        username="alice",
    )
    grant = load_grant(env["alice_id"])
    names = {item.get("name") for item in grant.get("knowledge_bases", [])}
    assert {"admin:kb:甲", "admin:kb:乙"} <= names


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


def _make_api_client(payment_env):
    from deeptutor.api.routers import payment_online
    from deeptutor.api.routers.auth import require_auth

    app = FastAPI()
    app.include_router(payment_online.router, prefix="/api/payment")
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def test_plans_endpoint(payment_env):
    _write_plans(
        payment_env,
        [
            {"id": "p1", "name": "标准版", "price_fen": 2990, "period": "monthly"},
            {"id": "p2", "name": "高级版", "price_fen": 9900, "period": "yearly"},
        ],
    )
    _write_gateways(payment_env, {"wechat": {"enabled": True}})
    client = _make_api_client(payment_env)
    resp = client.get("/api/payment/plans")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["plans"]) == 2
    assert "wechat" in body["gateways"]


def test_create_order_endpoint_epay(payment_env):
    _write_plans(
        payment_env,
        [{"id": "p1", "name": "标准版", "price_fen": 2990, "period": "monthly"}],
    )
    _write_gateways(
        payment_env,
        {
            "epay": {
                "enabled": True,
                "gateway_url": "https://pay.example.com",
                "pid": "1000",
                "merchant_key": "secret-key",
            }
        },
    )
    client = _make_api_client(payment_env)
    resp = client.post(
        "/api/payment/orders/create",
        json={"plan_id": "p1", "gateway": "epay"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["gateway"] == "epay"
    assert body["amount_fen"] == 2990
    assert "pay_url" in body and "pay.example.com" in body["pay_url"]


def test_create_order_endpoint_missing_plan(payment_env):
    _write_plans(payment_env, [])
    _write_gateways(payment_env, {"epay": {"enabled": True, "pid": "1", "merchant_key": "k"}})
    client = _make_api_client(payment_env)
    resp = client.post(
        "/api/payment/orders/create",
        json={"plan_id": "missing", "gateway": "epay"},
    )
    assert resp.status_code == 404


def test_notify_endpoint_public(payment_env):
    """The notify endpoint must not require auth."""
    _write_gateways(
        payment_env,
        {
            "epay": {
                "enabled": True,
                "gateway_url": "https://pay.example.com",
                "pid": "1000",
                "merchant_key": "secret-key",
            }
        },
    )
    from deeptutor.payment.orders import create_order

    order = create_order(
        user_id=payment_env["alice_id"],
        username="alice",
        plan={"id": "p1", "price_fen": 100},
        gateway="epay",
    )
    from deeptutor.payment.gateways import _epay_sign

    params = {
        "pid": "1000",
        "out_trade_no": order["order_no"],
        "trade_status": "TRADE_SUCCESS",
        "money": "1.00",
    }
    params["sign_type"] = "MD5"
    params["sign"] = _epay_sign(params, "secret-key")

    client = _make_api_client(payment_env)
    resp = client.post("/api/payment/notify/epay", data=params)
    assert resp.status_code == 200
    assert resp.text == "success"


def test_status_endpoint(payment_env):
    from deeptutor.payment.orders import create_order

    env = payment_env
    order = create_order(
        user_id=env["alice_id"],
        username="alice",
        plan={"id": "p1", "price_fen": 100},
        gateway="epay",
    )
    client = _make_api_client(payment_env)
    resp = client.get(f"/api/payment/orders/{order['order_id']}/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    assert resp.json()["granted"] is False


# ---------------------------------------------------------------------------
# WeChat APIv3 signature verification
# ---------------------------------------------------------------------------


def test_wechat_signature_verification_accepts_valid(payment_env, tmp_path):
    """A callback signed by the platform cert passes; a tampered one fails."""
    import base64
    from datetime import datetime, timezone

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.x509 import CertificateBuilder, Name, NameAttribute, random_serial_number
    from cryptography.x509.oid import NameOID

    from deeptutor.payment.gateways import _verify_wechat_signature, gateways_path

    # Generate a throwaway platform cert for the "wechat server".
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = Name([NameAttribute(NameOID.COMMON_NAME, "wechat-platform")])
    cert = (
        CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(random_serial_number())
        .not_valid_before(datetime(2020, 1, 1))
        .not_valid_after(datetime(2035, 1, 1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    serial = format(cert.serial_number, "x").upper()

    certs_dir = tmp_path / "wechat-certs"
    certs_dir.mkdir()
    (certs_dir / f"{serial}.pem").write_bytes(cert_pem)

    _write_gateways(
        payment_env,
        {
            "wechat": {
                "enabled": True,
                "platform_certs_dir": str(certs_dir),
                "api_v3_key": "0123456789abcdef0123456789abcdef",
            }
        },
    )

    body = b'{"event_type":"TRANSACTION.SUCCESS","resource":{}}'
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    nonce = "nonce123"
    message = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n"
    signature = key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())

    headers = {
        "wechatpay-timestamp": timestamp,
        "wechatpay-nonce": nonce,
        "wechatpay-serial": serial,
        "wechatpay-signature": base64.b64encode(signature).decode(),
    }
    # Should not raise.
    _verify_wechat_signature({"platform_certs_dir": str(certs_dir)}, headers, body)

    # Tamper with the body -> must raise.
    with pytest.raises(SignatureVerificationError):
        _verify_wechat_signature({"platform_certs_dir": str(certs_dir)}, headers, b"tampered")


def test_wechat_notify_rejects_bad_cert(payment_env):
    from deeptutor.payment.notify import handle_wechat_notify

    headers = {
        "wechatpay-timestamp": "1",
        "wechatpay-nonce": "n",
        "wechatpay-serial": "unknown-serial",
        "wechatpay-signature": "AA==",
    }
    _write_gateways(
        payment_env, {"wechat": {"enabled": True, "platform_certs_dir": "/nonexistent"}}
    )
    result = handle_wechat_notify(headers, b"{}")
    assert result["code"] == "FAIL"
