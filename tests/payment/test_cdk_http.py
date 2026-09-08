"""HTTP-level tests for the payment CDK router.

Uses a minimal FastAPI app with the payment router mounted, mirroring the
``tests/api/test_book_permission_api.py`` pattern: the router's own
``require_auth`` / ``require_admin`` dependencies are overridden so the tests
exercise the endpoint logic without a real JWT round-trip.  The ``require_auth``
override installs a seeded learner through the same ``_install_current_user``
channel the real dependency uses, so ``get_current_user()`` inside the handler
resolves to the learner exactly as it does in production.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app(pay_isolated_root, *, learner: str | None = None) -> TestClient:
    from deeptutor.api.routers import payment as payment_router
    from deeptutor.api.routers.auth import _install_current_user, require_admin, require_auth
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload, hash_password

    app = FastAPI()
    app.include_router(payment_router.router, prefix="/api/payment")
    app.dependency_overrides[require_admin] = lambda: None

    if learner is not None:
        # Seed root first so ``save_user`` does not promote the learner to
        # admin (the store's first account auto-becomes admin).
        save_user("root", hash_password("password1234"), role="admin")  # type: ignore[arg-type]
        record = save_user(learner, hash_password("password1234"), role="user")  # type: ignore[arg-type]

        async def _auth_override():
            # Same install path as the real require_auth.  Must be ``async def``
            # — a sync dependency is dispatched via ``anyio.to_thread.run_sync``
            # whose ContextVar.set is discarded (#481), so the handler would
            # fall back to the local admin.
            return _install_current_user(
                TokenPayload(username=learner, role="user", user_id=record["id"])
            )

        app.dependency_overrides[require_auth] = _auth_override

    return TestClient(app)


def test_admin_batch_lifecycle(pay_isolated_root):
    client = _build_app(pay_isolated_root)

    create = client.post(
        "/api/payment/cdk/batches",
        json={"plan": {"id": "plan_monthly", "name": "月度会员", "valid_days": 30}, "count": 5},
    )
    assert create.status_code == 201
    body = create.json()
    batch_id = body["batch"]["id"]
    codes = body["codes"]
    assert len(codes) == 5

    listing = client.get("/api/payment/cdk/batches")
    assert listing.status_code == 200
    assert any(b["id"] == batch_id for b in listing.json())

    detail = client.get(f"/api/payment/cdk/batches/{batch_id}")
    assert detail.status_code == 200
    assert detail.json()["total_codes"] == 5

    codes_meta = client.get(f"/api/payment/cdk/batches/{batch_id}/codes")
    assert codes_meta.status_code == 200
    assert len(codes_meta.json()) == 5

    exported = client.get(f"/api/payment/cdk/batches/{batch_id}/export?fmt=json")
    assert exported.status_code == 200
    assert set(exported.json()["codes"]) == set(codes)

    csv_export = client.get(f"/api/payment/cdk/batches/{batch_id}/export?fmt=csv")
    assert csv_export.status_code == 200
    assert "text/csv" in csv_export.headers["content-type"]
    assert codes[0] in csv_export.text


def test_redeem_endpoint(pay_isolated_root):
    client = _build_app(pay_isolated_root, learner="alice")

    create = client.post(
        "/api/payment/cdk/batches",
        json={"plan": {"id": "plan_m", "name": "月卡", "valid_days": 30}, "count": 1},
    )
    code = create.json()["codes"][0]

    resp = client.post("/api/payment/cdk/redeem", json={"code": code})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["idempotent"] is False
    assert payload["plan"]["id"] == "plan_m"
    assert payload["grant"]["user_id"] != "local-admin"

    # Same account retry is idempotent.
    again = client.post("/api/payment/cdk/redeem", json={"code": code})
    assert again.status_code == 200
    assert again.json()["idempotent"] is True


def test_redeem_invalid_code(pay_isolated_root):
    client = _build_app(pay_isolated_root, learner="alice")
    resp = client.post("/api/payment/cdk/redeem", json={"code": "BADCODE"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_code"


def test_admin_required_for_generation(pay_isolated_root):
    """``require_admin`` rejects a non-admin token with 403."""
    from fastapi import HTTPException
    import pytest

    from deeptutor.api.routers import auth as auth_router
    from deeptutor.services.auth import TokenPayload

    original = auth_router.AUTH_ENABLED
    auth_router.AUTH_ENABLED = True
    try:
        import asyncio

        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                auth_router.require_admin(
                    TokenPayload(username="bob", role="user", user_id="u_bob")
                )
            )
        assert exc.value.status_code == 403
    finally:
        auth_router.AUTH_ENABLED = original


def test_redeem_requires_auth(pay_isolated_root):
    """``require_auth`` rejects a request with no token when auth is enabled."""
    from fastapi import HTTPException
    import pytest

    from deeptutor.api.routers import auth as auth_router

    original = auth_router.AUTH_ENABLED
    auth_router.AUTH_ENABLED = True
    try:
        import asyncio

        with pytest.raises(HTTPException) as exc:
            asyncio.run(auth_router.require_auth(authorization=None, dt_token=None))
        assert exc.value.status_code == 401
    finally:
        auth_router.AUTH_ENABLED = original
