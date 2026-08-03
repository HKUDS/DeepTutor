"""The CLI apps API: who can install, and who can only choose.

The router is auth-gated with ``require_admin`` on two routes rather than on the
whole thing, which is only defensible if those two are genuinely the privileged
half. These tests pin that split, and the rule that keeps *enable* from becoming
a way around the grant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import space_cli_apps
from deeptutor.services.cli_apps.models import AppRuntime, InstallKind
from deeptutor.services.cli_apps.paths import abi_stamp
from deeptutor.services.cli_apps.state import InstalledApp, record_install

REAL_APP = "blender"


@pytest.fixture(autouse=True)
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)
    return admin_root


@pytest.fixture
def caller(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A switchable identity: owner id, grant, and exec policy."""
    state: dict[str, Any] = {"owner": "u_ada", "granted": set(), "exec": None}
    monkeypatch.setattr(space_cli_apps, "current_owner_id", lambda: state["owner"])
    monkeypatch.setattr(space_cli_apps, "allowed_cli_apps", lambda: state["granted"])
    monkeypatch.setattr(space_cli_apps, "exec_override", lambda: state["exec"])
    return state


@pytest.fixture
def client(caller: dict[str, Any]) -> TestClient:
    app = FastAPI()
    app.include_router(space_cli_apps.router, prefix="/api/v1/space/cli-apps")
    return TestClient(app)


def _install(app_id: str = REAL_APP) -> None:
    record_install(
        InstalledApp(
            id=app_id,
            entry_point=f"cli-anything-{app_id}",
            runtime=AppRuntime.PYTHON,
            kind=InstallKind.PINNED_HARNESS,
            target="git+https://example.invalid/x.git@abc",
            pin="abc",
            abi=abi_stamp(),
            installed_at="2026-07-29T00:00:00+00:00",
        )
    )


# ── reading ───────────────────────────────────────────────────────────────


def test_the_catalog_is_readable_without_being_an_admin(client: TestClient) -> None:
    body = client.get("/api/v1/space/cli-apps/catalog").json()

    assert body["total"] > 0
    assert body["catalog_pin"]
    assert all(row["installable"] for row in body["entries"]), (
        "the default listing should not show cards nobody here can install"
    )


def test_asking_for_everything_includes_the_refusals_with_their_reasons(
    client: TestClient,
) -> None:
    """Hiding them would make the store look smaller than the ecosystem is."""
    body = client.get("/api/v1/space/cli-apps/catalog?installable_only=false&limit=60").json()
    refused = [row for row in body["entries"] if not row["installable"]]

    assert refused
    assert all(row["unsupported_reason"] for row in refused)


def test_a_catalog_row_says_whether_the_install_is_pinned(client: TestClient) -> None:
    body = client.get("/api/v1/space/cli-apps/catalog?q=jumpserver").json()
    row = next(item for item in body["entries"] if item["id"] == "jumpserver")

    assert row["pinned"] is True
    assert row["trust"] == "first-party"


def test_an_ungranted_account_sees_the_app_but_not_as_usable(
    client: TestClient, caller: dict[str, Any]
) -> None:
    """Hiding it would leave the reader unable to ask their admin for it by name."""
    _install()
    body = client.get("/api/v1/space/cli-apps/apps").json()
    row = body["apps"][0]

    assert row["id"] == REAL_APP
    assert row["granted"] is False
    assert row["enabled"] is False
    assert row["tool_name"] == f"cli_{REAL_APP}"


def test_an_account_denied_code_execution_is_told_so_once(
    client: TestClient, caller: dict[str, Any]
) -> None:
    _install()
    caller["granted"] = {REAL_APP}
    caller["exec"] = False

    body = client.get("/api/v1/space/cli-apps/apps").json()
    assert body["access"]["exec_denied"] is True


def test_an_administrator_reads_as_unrestricted(client: TestClient, caller: dict[str, Any]) -> None:
    _install()
    caller["granted"] = None

    body = client.get("/api/v1/space/cli-apps/apps").json()
    assert body["access"]["unrestricted"] is True
    assert body["apps"][0]["granted"] is True


# ── choosing ──────────────────────────────────────────────────────────────


def test_an_account_can_switch_off_an_app_it_was_granted(
    client: TestClient, caller: dict[str, Any]
) -> None:
    _install()
    caller["granted"] = {REAL_APP}

    body = client.put(
        f"/api/v1/space/cli-apps/apps/{REAL_APP}/enabled", json={"enabled": False}
    ).json()

    assert body["apps"][0]["enabled"] is False
    # And the response is fresh state, so the switch cannot show the old value.
    again = client.get("/api/v1/space/cli-apps/apps").json()
    assert again["apps"][0]["enabled"] is False


def test_switching_on_an_app_the_grant_denies_is_refused(
    client: TestClient, caller: dict[str, Any]
) -> None:
    """Otherwise the preference file records interest in a denied app, and a later
    grant switches it on without anybody choosing that."""
    _install()
    caller["granted"] = set()

    response = client.put(f"/api/v1/space/cli-apps/apps/{REAL_APP}/enabled", json={"enabled": True})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "cli.not_granted"


def test_toggling_an_app_that_is_not_installed_is_a_404(
    client: TestClient, caller: dict[str, Any]
) -> None:
    caller["granted"] = None
    response = client.put(
        "/api/v1/space/cli-apps/apps/never-installed/enabled", json={"enabled": True}
    )
    assert response.status_code == 404


def test_one_accounts_preference_does_not_reach_another(
    client: TestClient, caller: dict[str, Any]
) -> None:
    _install()
    caller["granted"] = {REAL_APP}
    client.put(f"/api/v1/space/cli-apps/apps/{REAL_APP}/enabled", json={"enabled": False})

    caller["owner"] = "u_bob"
    assert client.get("/api/v1/space/cli-apps/apps").json()["apps"][0]["enabled"] is True


# ── installing ────────────────────────────────────────────────────────────


def test_installing_and_removing_require_an_administrator() -> None:
    """Asserted on the routes themselves: installing runs a third-party setup.py
    in the application container, and that gate is the feature's whole premise."""
    from deeptutor.api.routers.auth import require_admin

    gated = {
        (route.path, method)
        for route in space_cli_apps.router.routes
        for method in getattr(route, "methods", set())
        if any(
            dep.call is require_admin
            for dep in getattr(route, "dependant", None).dependencies  # type: ignore[union-attr]
        )
    }
    assert ("/catalog/{app_id}/install", "POST") in gated
    assert ("/apps/{app_id}", "DELETE") in gated
    # And the read/choose routes are not gated, or a learner could not use the page.
    assert not any(path == "/apps" and method == "GET" for path, method in gated)
    assert not any("enabled" in path for path, _method in gated)


def test_installing_something_not_in_the_catalog_is_a_404(client: TestClient) -> None:
    response = client.post("/api/v1/space/cli-apps/catalog/no-such-app/install")
    assert response.status_code == 404


def test_a_failed_install_answers_with_its_log(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.cli_apps.installer import InstallOutcome

    async def _fail(entry: Any) -> InstallOutcome:
        return InstallOutcome(
            ok=False,
            app_id=entry.id,
            code="cli.install_failed",
            message="`pip` exited 1",
            log="$ pip install ...\nERROR: No matching distribution",
        )

    monkeypatch.setattr("deeptutor.services.cli_apps.installer.install_app", _fail)
    response = client.post(f"/api/v1/space/cli-apps/catalog/{REAL_APP}/install")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "cli.install_failed"
    assert "No matching distribution" in detail["log"]


def test_installing_an_unsupported_entry_is_refused_with_its_reason(
    client: TestClient,
) -> None:
    """``jimeng`` publishes ``curl … | bash``; the store shows it and the API
    refuses it, rather than the entry quietly not existing."""
    response = client.post("/api/v1/space/cli-apps/catalog/jimeng/install")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "cli.not_installable"
    assert "shell" in detail["message"].lower()


def test_uninstalling_answers_with_the_resulting_list(
    client: TestClient, caller: dict[str, Any]
) -> None:
    _install()
    caller["granted"] = None

    body = client.delete(f"/api/v1/space/cli-apps/apps/{REAL_APP}").json()
    assert body["apps"] == []
