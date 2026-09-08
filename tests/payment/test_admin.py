"""Tests for the RIC-546 admin commerce-management layer.

Covers the gateway-config write path (validation + secret round-trip), the
pricing-plan model (normalisation + CRUD through the admin API) and the order
ledger admin views (refund flag + filters).  Path isolation follows the other
payment tests: every module that derives paths from ``SYSTEM_ROOT`` is
monkey-patched onto a per-test tmp tree.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.multi_user import identity
from deeptutor.multi_user import paths as mpaths
from deeptutor.multi_user.grants import load_grant


@pytest.fixture
def payment_env(tmp_path, monkeypatch):
    """Point every payment/multi-user path at a per-test tree and seed users."""
    admin_root = (tmp_path / "data").resolve()
    system_root = admin_root / "system"

    from deeptutor.multi_user import audit, grants
    from deeptutor.payment import admin, gateways, orders, service

    for module in (mpaths, identity, grants, audit, gateways, orders, service):
        monkeypatch.setattr(module, "SYSTEM_ROOT", system_root)
    # ``admin`` re-exports path helpers from gateways/service and never imports
    # SYSTEM_ROOT itself, so no module-level patch is needed for it.
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

    # Seed one admin + one learner.
    identity.save_user("root", "hash", role="admin")
    alice = identity.save_user("alice", "hash", role="user", preset="learner")

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


def _make_admin_client(payment_env):
    from deeptutor.api.routers import payment_admin
    from deeptutor.api.routers.auth import require_admin

    app = FastAPI()
    app.include_router(payment_admin.router, prefix="/api/payment")
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app)


# ---------------------------------------------------------------------------
# Gateway configuration
# ---------------------------------------------------------------------------


def test_gateway_config_save_and_redact(payment_env):
    client = _make_admin_client(payment_env)
    resp = client.post(
        "/api/payment/admin/gateways",
        json={
            "wechat": {
                "enabled": True,
                "appid": "wx123",
                "mchid": "1000",
                "api_v3_key": "super-secret",
                "merchant_serial_no": "SN001",
            },
            "epay": {"enabled": False, "pid": "1", "merchant_key": "epay-key"},
            "cdk": {"enabled": True},
        },
    )
    assert resp.status_code == 200
    body = resp.json()["gateways"]
    # Credential-shaped keys must be redacted on the wire.
    assert body["wechat"]["api_v3_key"] == "***"
    assert body["epay"]["merchant_key"] == "***"
    # Non-secret keys survive intact.
    assert body["wechat"]["mchid"] == "1000"

    # On disk the real secret is stored.
    from deeptutor.payment import admin

    stored = admin.load_gateway_config()
    assert stored["wechat"]["api_v3_key"] == "super-secret"


def test_gateway_config_mask_round_trip_keeps_secret(payment_env):
    from deeptutor.payment import admin

    admin.save_gateways({"wechat": {"enabled": True, "api_v3_key": "real-secret", "mchid": "1"}})
    client = _make_admin_client(payment_env)
    # GET returns the mask; POST the mask back as "keep stored value".
    redacted = client.get("/api/payment/admin/gateways").json()["gateways"]
    assert redacted["wechat"]["api_v3_key"] == "***"

    resp = client.post(
        "/api/payment/admin/gateways",
        json={
            "wechat": {
                "enabled": True,
                "api_v3_key": "***",
                "mchid": "1",
            }
        },
    )
    assert resp.status_code == 200
    stored = admin.load_gateway_config()
    assert stored["wechat"]["api_v3_key"] == "real-secret"


def test_gateway_config_rejects_unknown_channel(payment_env):
    client = _make_admin_client(payment_env)
    resp = client.post(
        "/api/payment/admin/gateways",
        json={"bitcoin": {"enabled": True}},
    )
    assert resp.status_code == 400
    assert "unsupported gateway" in resp.json()["detail"]


def test_gateway_config_rejects_non_bool_enabled(payment_env):
    client = _make_admin_client(payment_env)
    resp = client.post(
        "/api/payment/admin/gateways",
        json={"wechat": {"enabled": "yes"}},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Pricing plans — model
# ---------------------------------------------------------------------------


def test_normalize_plan_full_bundle(payment_env):
    from deeptutor.payment.admin import normalize_plan

    plan = normalize_plan(
        {
            "id": "plan_standard",
            "name": "标准版",
            "price_fen": 2990,
            "period": "monthly",
            "duration_days": 30,
            "books": ["bk_shared"],
            "knowledge_bases": [{"name": "admin:kb:math"}, "admin:kb:exam"],
            "models": {"llm": [{"profile_id": "prof_a", "model_ids": ["m1", "m2"]}]},
            "skills": ["skill_1"],
            "perks": ["RAG 题库", "专属答疑"],
            "tag": "popular",
            "recommended": True,
        }
    )
    assert plan["id"] == "plan_standard"
    assert plan["price_fen"] == 2990
    assert plan["books"] == ["bk_shared"]
    assert {kb["name"] for kb in plan["knowledge_bases"]} == {"admin:kb:math", "admin:kb:exam"}
    assert plan["models"]["llm"] == [{"profile_id": "prof_a", "model_ids": ["m1", "m2"]}]
    assert plan["perks"] == ["RAG 题库", "专属答疑"]
    assert plan["tag"] == "popular"
    assert plan["recommended"] is True


def test_normalize_plan_rejects_bad_price_and_period(payment_env):
    from deeptutor.payment.admin import PlanValidationError, normalize_plan

    with pytest.raises(PlanValidationError, match="price_fen"):
        normalize_plan({"id": "p", "name": "x", "price_fen": -5})
    with pytest.raises(PlanValidationError, match="period"):
        normalize_plan({"id": "p", "name": "x", "price_fen": 100, "period": "weekly"})
    with pytest.raises(PlanValidationError, match="id"):
        normalize_plan({"name": "x", "price_fen": 100})
    with pytest.raises(PlanValidationError, match="name"):
        normalize_plan({"id": "p", "price_fen": 100})


def test_provision_plan_uses_admin_normalised_bundle(payment_env):
    """The admin plan shape must provision identically to the cashier path."""
    from deeptutor.payment.admin import normalize_plan, upsert_plan
    from deeptutor.payment.orders import create_order
    from deeptutor.payment.provisioning import provision_plan

    plan = upsert_plan(
        {
            "id": "p1",
            "name": "标准版",
            "price_fen": 2990,
            "knowledge_bases": [{"name": "admin:kb:数学"}],
        }
    )
    order = create_order(
        user_id=payment_env["alice_id"],
        username="alice",
        plan=plan,
        gateway="epay",
    )
    assert order["amount_fen"] == 2990
    provision_plan(
        plan=plan,
        user_id=payment_env["alice_id"],
        username="alice",
    )
    grant = load_grant(payment_env["alice_id"])
    kb_names = {item.get("name") for item in grant.get("knowledge_bases", [])}
    assert "admin:kb:数学" in kb_names


# ---------------------------------------------------------------------------
# Pricing plans — API
# ---------------------------------------------------------------------------


def test_plan_crud_via_api(payment_env):
    client = _make_admin_client(payment_env)

    # Create
    resp = client.post(
        "/api/payment/admin/plans",
        json={
            "plan": {
                "id": "p_monthly",
                "name": "月卡",
                "price_fen": 2990,
                "period": "monthly",
                "duration_days": 30,
                "books": ["bk_1"],
            }
        },
    )
    assert resp.status_code == 201
    assert resp.json()["plan"]["id"] == "p_monthly"

    # List
    assert client.get("/api/payment/admin/plans").json()["plans"][0]["id"] == "p_monthly"

    # Read one
    assert client.get("/api/payment/admin/plans/p_monthly").json()["plan"]["name"] == "月卡"

    # Update
    resp = client.put(
        "/api/payment/admin/plans/p_monthly",
        json={
            "plan": {
                "id": "p_monthly",
                "name": "月卡(改)",
                "price_fen": 1990,
                "period": "monthly",
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json()["plan"]["price_fen"] == 1990

    # Delete
    assert client.delete("/api/payment/admin/plans/p_monthly").json()["deleted"] == "p_monthly"
    assert client.get("/api/payment/admin/plans/p_monthly").status_code == 404


def test_plan_update_id_mismatch_rejected(payment_env):
    client = _make_admin_client(payment_env)
    client.post(
        "/api/payment/admin/plans",
        json={"plan": {"id": "p1", "name": "x", "price_fen": 100}},
    )
    resp = client.put(
        "/api/payment/admin/plans/p2",
        json={"plan": {"id": "p1", "name": "x", "price_fen": 100}},
    )
    assert resp.status_code == 400


def test_plan_duplicate_ids_rejected(payment_env):
    from deeptutor.payment.admin import PlanValidationError, save_plans

    with pytest.raises(PlanValidationError, match="unique"):
        save_plans(
            [
                {"id": "p1", "name": "a", "price_fen": 100},
                {"id": "p1", "name": "b", "price_fen": 200},
            ]
        )


# ---------------------------------------------------------------------------
# Order ledger — admin views
# ---------------------------------------------------------------------------


def test_admin_order_list_and_refund(payment_env):
    from deeptutor.payment.orders import create_order

    order = create_order(
        user_id=payment_env["alice_id"],
        username="alice",
        plan={"id": "p1", "name": "月卡", "price_fen": 2990},
        gateway="epay",
    )
    client = _make_admin_client(payment_env)

    rows = client.get("/api/payment/admin/orders").json()
    assert rows["count"] == 1
    assert rows["orders"][0]["order_id"] == order["order_id"]
    assert rows["orders"][0]["status"] == "pending"

    # Filter by user.
    assert (
        client.get("/api/payment/admin/orders", params={"user_id": "nobody"}).json()["count"] == 0
    )

    # Refund.
    resp = client.post(
        f"/api/payment/admin/orders/{order['order_id']}/refund",
        json={"reason": "用户申请退款"},
    )
    assert resp.status_code == 200
    assert resp.json()["order"]["status"] == "refunded"
    assert resp.json()["order"]["refund_reason"] == "用户申请退款"

    # Detail shows the refunded state.
    detail = client.get(f"/api/payment/admin/orders/{order['order_id']}").json()["order"]
    assert detail["status"] == "refunded"


def test_admin_order_view_exposes_admin_fields(payment_env):
    """The admin ledger view must carry the admin-console fields."""
    from deeptutor.payment.orders import create_order

    order = create_order(
        user_id=payment_env["alice_id"],
        username="alice",
        plan={"id": "p1", "name": "月卡", "price_fen": 2990},
        gateway="epay",
    )
    client = _make_admin_client(payment_env)
    detail = client.get(f"/api/payment/admin/orders/{order['order_id']}").json()["order"]
    assert detail["order_id"] == order["order_id"]
    assert detail["order_no"] == order["order_no"]
    assert detail["user_id"] == payment_env["alice_id"]
    assert detail["username"] == "alice"
    assert detail["plan_id"] == "p1"
    assert detail["plan_name"] == "月卡"
    assert detail["amount_fen"] == 2990
    assert detail["status"] == "pending"
    assert detail["plan_snapshot"]["id"] == "p1"


def test_admin_refund_already_refunded_is_idempotent(payment_env):
    from deeptutor.payment.orders import TRANSITION_EXTRA_REFUND, create_order, transition_order

    order = create_order(
        user_id=payment_env["alice_id"],
        username="alice",
        plan={"id": "p1", "price_fen": 100},
        gateway="epay",
    )
    transition_order(order["order_id"], "refunded", extra=TRANSITION_EXTRA_REFUND("first"))
    client = _make_admin_client(payment_env)
    resp = client.post(
        f"/api/payment/admin/orders/{order['order_id']}/refund",
        json={"reason": "again"},
    )
    assert resp.status_code == 200
    assert resp.json()["order"]["status"] == "refunded"


def test_admin_order_unknown_id_404(payment_env):
    client = _make_admin_client(payment_env)
    assert client.get("/api/payment/admin/orders/po_nope").status_code == 404
