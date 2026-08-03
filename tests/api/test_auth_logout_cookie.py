"""Regression test for #623.

``Response.delete_cookie()`` defaults ``secure=False``. The logout endpoint
passed only ``samesite=_SAMESITE`` (no ``secure``), so when
``cookie_secure=true`` (``_SAMESITE="none"``) the expiry header became
``SameSite=None`` without ``Secure`` — an invalid combination browsers
reject outright, leaving the original ``dt_token`` cookie in place and the
user still signed in after clicking "Sign out".
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_logout_sets_secure_when_cookie_secure_enabled(monkeypatch) -> None:
    from deeptutor.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "_SECURE", True)
    monkeypatch.setattr(auth_router, "_SAMESITE", "none")

    app = FastAPI()
    app.add_api_route("/logout", auth_router.logout, methods=["POST"])

    with TestClient(app) as client:
        resp = client.post("/logout")

    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "Max-Age=0" in set_cookie
    assert "samesite=none" in set_cookie.lower()
    assert "secure" in set_cookie.lower(), (
        "logout must set Secure on the deletion cookie when cookie_secure=true, "
        "otherwise browsers reject the invalid SameSite=None (no Secure) "
        "combination and never clear dt_token — see #623."
    )


def test_logout_omits_secure_when_cookie_secure_disabled(monkeypatch) -> None:
    """Local dev (cookie_secure=false → SameSite=Lax) must not gain a stray
    Secure attribute — browsers drop Secure cookies over plain HTTP."""
    from deeptutor.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "_SECURE", False)
    monkeypatch.setattr(auth_router, "_SAMESITE", "lax")

    app = FastAPI()
    app.add_api_route("/logout", auth_router.logout, methods=["POST"])

    with TestClient(app) as client:
        resp = client.post("/logout")

    set_cookie = resp.headers.get("set-cookie", "")
    assert "Max-Age=0" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "secure" not in set_cookie.lower()
