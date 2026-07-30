"""The per-user MCP surface: isolation, refusals, and secret hygiene.

This router is auth-gated rather than admin-gated, which is only defensible
because of what it refuses. Each test below pins one of those refusals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import space_mcp


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the lookup is stubbed; the address policy itself still runs."""
    import socket

    def _getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        addr = "127.0.0.1" if loopback else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0))]

    monkeypatch.setattr("deeptutor.services.mcp.network.socket.getaddrinfo", _getaddrinfo)


@pytest.fixture
def owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Redirect the data roots and make the acting owner switchable."""
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})

    acting = {"id": "u_ada"}
    monkeypatch.setattr(space_mcp, "current_owner_id", lambda: acting["id"])
    monkeypatch.setattr(
        "deeptutor.services.mcp.config.mcp_config_path", lambda: tmp_path / "admin-mcp.json"
    )
    return acting


@pytest.fixture
def client(owner: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    class _Manager:
        def __init__(self) -> None:
            self.reloaded: list[str] = []
            self.warmed: list[str] = []

        async def reload_scope(self, owner_id: str) -> None:
            self.reloaded.append(owner_id)

        async def ensure_started(self) -> None:
            self.warmed.append("_shared")

        async def ensure_scope(self, owner_id: str) -> list[Any]:
            self.warmed.append(owner_id)
            return []

        def status(self, owner_id: str = "_shared") -> list[dict[str, Any]]:
            return []

    manager = _Manager()
    monkeypatch.setattr(space_mcp, "get_mcp_manager", lambda: manager)
    app = FastAPI()
    app.include_router(space_mcp.router, prefix="/api/v1/space/mcp")
    return TestClient(app)


def _remote(url: str = "https://mcp.example.com/mcp") -> dict[str, Any]:
    return {"config": {"url": url}, "secrets": {}}


def test_a_server_is_visible_only_to_its_owner(client: TestClient, owner) -> None:
    assert client.put("/api/v1/space/mcp/servers/mine", json=_remote()).status_code == 200
    assert list(client.get("/api/v1/space/mcp/servers").json()["servers"]) == ["mine"]

    owner["id"] = "u_bob"
    assert client.get("/api/v1/space/mcp/servers").json()["servers"] == {}


def test_one_account_cannot_write_into_anothers_config(client: TestClient, owner) -> None:
    """The owner is resolved server-side and never taken from the request."""
    client.put("/api/v1/space/mcp/servers/shared-name", json=_remote("https://a.example/mcp"))
    owner["id"] = "u_bob"
    client.put("/api/v1/space/mcp/servers/shared-name", json=_remote("https://b.example/mcp"))

    assert client.get("/api/v1/space/mcp/servers").json()["servers"]["shared-name"]["url"] == (
        "https://b.example/mcp"
    )
    owner["id"] = "u_ada"
    assert client.get("/api/v1/space/mcp/servers").json()["servers"]["shared-name"]["url"] == (
        "https://a.example/mcp"
    )


def test_a_stdio_server_is_refused(client: TestClient) -> None:
    response = client.put(
        "/api/v1/space/mcp/servers/local",
        json={"config": {"command": "/bin/sh"}, "secrets": {}},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "mcp.stdio_not_allowed"


def test_a_url_aimed_at_the_deployment_is_refused(client: TestClient) -> None:
    response = client.put(
        "/api/v1/space/mcp/servers/inward",
        json=_remote("http://127.0.0.1:8090/mcp"),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "mcp.blocked_url"


def test_a_credential_is_stored_apart_and_never_echoed(client: TestClient, tmp_path: Path) -> None:
    response = client.put(
        "/api/v1/space/mcp/servers/svc",
        json={
            "config": {"url": "https://svc.example/mcp", "headers": {"X-Key": "sk-live-1"}},
            "secrets": {"api_key": "sk-live-1"},
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "sk-live-1" not in body, "a GET/PUT response must never carry a credential"
    # Both the labelled credential and the header value the client typed: on a
    # self-configured server a header value *is* the credential, and the form has
    # no way to say which row is sensitive.
    assert response.json()["configured_secrets"] == {"svc": ["api_key", "header.X-Key"]}
    # The literal the client pasted into a header was swapped for a reference.
    stored = (tmp_path / "data" / "system" / "user-mcp" / "u_ada.json").read_text(encoding="utf-8")
    assert "sk-live-1" not in stored
    # Positional extraction got there first, so the header row references its
    # own field name; the labelled key is stored too, harmlessly unreferenced.
    assert "${secret:svc/header.X-Key}" in stored


def test_deleting_a_server_also_drops_its_credentials(client: TestClient, tmp_path: Path) -> None:
    client.put(
        "/api/v1/space/mcp/servers/svc",
        json={"config": {"url": "https://svc.example/mcp"}, "secrets": {"api_key": "sk-1"}},
    )
    client.delete("/api/v1/space/mcp/servers/svc")

    from deeptutor.services.mcp.secrets import configured_fields

    assert configured_fields("u_ada", "svc") == set()


def test_the_catalog_hides_admin_only_entries(client: TestClient) -> None:
    """stdio entries are catalogued for the deployment, not for an account."""
    body = client.get("/api/v1/space/mcp/catalog?limit=100").json()
    assert body["entries"], "the curated catalog must not be empty here"
    assert all(entry["self_service"] for entry in body["entries"])
    assert all(entry["transport"] != "stdio" for entry in body["entries"])


def test_every_category_chip_opens_to_something(client: TestClient) -> None:
    body = client.get("/api/v1/space/mcp/catalog?limit=100").json()
    for category, count in body["categories"].items():
        if count == 0:
            continue
        page = client.get(f"/api/v1/space/mcp/catalog?category={category}&limit=100").json()
        assert page["total"] == count


def test_installing_an_admin_only_entry_is_refused(client: TestClient) -> None:
    from deeptutor.services.mcp.catalog import load_catalog

    stdio = next(entry for entry in load_catalog() if not entry.self_service)
    response = client.post(f"/api/v1/space/mcp/catalog/{stdio.id}/install", json={"secrets": {}})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "mcp.entry_admin_only"


def test_installing_an_unknown_entry_is_a_404(client: TestClient) -> None:
    response = client.post("/api/v1/space/mcp/catalog/no-such-thing/install", json={"secrets": {}})
    assert response.status_code == 404


def test_installing_without_a_required_credential_is_refused(client: TestClient) -> None:
    from deeptutor.services.mcp.catalog import load_catalog

    needs_key = next(
        entry
        for entry in load_catalog()
        if entry.self_service and any(field.required for field in entry.fields)
    )
    response = client.post(
        f"/api/v1/space/mcp/catalog/{needs_key.id}/install", json={"secrets": {}}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "mcp.missing_credential"


def test_installing_a_catalog_entry_stores_its_credential_out_of_the_config(
    client: TestClient, tmp_path: Path
) -> None:
    from deeptutor.services.mcp.catalog import load_catalog

    entry = next(
        item
        for item in load_catalog()
        if item.self_service and any(field.required and field.secret for field in item.fields)
    )
    secrets = {field.key: "tok-1" for field in entry.fields if field.required}

    response = client.post(
        f"/api/v1/space/mcp/catalog/{entry.id}/install", json={"secrets": secrets}
    )

    assert response.status_code == 200, response.text
    assert "tok-1" not in response.text
    stored = (tmp_path / "data" / "system" / "user-mcp" / "u_ada.json").read_text(encoding="utf-8")
    assert "tok-1" not in stored
    assert "${secret:" in stored


def _first_free_entry() -> Any:
    """A self-service catalog entry that needs no credential to install."""
    from deeptutor.services.mcp.catalog import load_catalog

    return next(
        entry
        for entry in load_catalog()
        if entry.self_service and not any(field.required for field in entry.fields)
    )


def test_an_entry_installed_under_a_custom_name_still_reads_as_installed(
    client: TestClient,
) -> None:
    """The installer names the server, so the catalog cannot match on the id.

    Reporting "not installed" here is not cosmetic: it offers a second install of
    a service the account already has, which then spends another slot against the
    per-account cap.
    """
    entry = _first_free_entry()
    installed = client.post(
        f"/api/v1/space/mcp/catalog/{entry.id}/install", json={"name": "my-own-name"}
    )
    assert installed.status_code == 200, installed.text

    row = _catalog_entry(client, entry.id)
    assert row["installed"] is True
    assert row["installed_as"] == ["my-own-name"]


def test_a_hand_written_server_is_not_credited_to_a_catalog_entry(
    client: TestClient,
) -> None:
    entry = _first_free_entry()
    client.put("/api/v1/space/mcp/servers/unrelated", json=_remote())

    row = _catalog_entry(client, entry.id)
    assert row["installed"] is False
    assert row["installed_as"] == []


def test_an_entry_installed_before_provenance_existed_still_reads_as_installed(
    client: TestClient, tmp_path: Path
) -> None:
    """Configs written by an earlier release carry no ``catalog_entry``."""
    entry = _first_free_entry()
    path = tmp_path / "data" / "system" / "user-mcp" / "u_ada.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'{{"servers": {{"{entry.id}": {{"url": "https://legacy.example/mcp"}}}}}}',
        encoding="utf-8",
    )

    row = _catalog_entry(client, entry.id)
    assert row["installed"] is True
    assert row["installed_as"] == [entry.id]


def _catalog_entry(client: TestClient, entry_id: str) -> dict[str, Any]:
    page = client.get(f"/api/v1/space/mcp/catalog?q={entry_id}&limit=100").json()
    return next(row for row in page["entries"] if row["id"] == entry_id)


def test_a_name_taken_by_a_deployment_server_is_refused(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "admin-mcp.json").write_text(
        '{"servers": {"github": {"url": "https://admin.example/mcp"}}}', encoding="utf-8"
    )
    response = client.put("/api/v1/space/mcp/servers/github", json=_remote())
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "mcp.name_reserved"


def test_a_header_typed_into_the_form_is_not_stored_or_echoed_in_plaintext(
    client: TestClient, tmp_path: Path
) -> None:
    """The generic "add a server by URL" form has no notion of a secret.

    Somebody pasting ``Authorization: Bearer sk-live-…`` into a header row must
    not have it land on disk or come back out of a GET, so the extraction is
    positional (a header value on a self-configured server is a credential)
    rather than driven by what the client labelled.
    """
    response = client.put(
        "/api/v1/space/mcp/servers/svc",
        json={
            "config": {
                "url": "https://svc.example/mcp",
                "headers": {"Authorization": "Bearer sk-live-SUPERSECRET"},
            },
            "secrets": {},
        },
    )

    assert response.status_code == 200
    assert "sk-live-SUPERSECRET" not in response.text
    stored = (tmp_path / "data" / "system" / "user-mcp" / "u_ada.json").read_text(encoding="utf-8")
    assert "sk-live-SUPERSECRET" not in stored
    assert "${secret:svc/header.Authorization}" in stored
    assert response.json()["configured_secrets"]["svc"] == ["header.Authorization"]


def test_resaving_a_server_keeps_a_credential_it_did_not_re_enter(
    client: TestClient, tmp_path: Path
) -> None:
    """The edit form shows a saved credential as configured, not as its value.

    So the draft it submits carries the reference back — which must be left
    alone rather than stored as the literal placeholder the user was shown.
    """
    client.put(
        "/api/v1/space/mcp/servers/svc",
        json={
            "config": {"url": "https://svc.example/mcp", "headers": {"X-Key": "sk-1"}},
            "secrets": {},
        },
    )
    client.put(
        "/api/v1/space/mcp/servers/svc",
        json={
            "config": {
                "url": "https://svc.example/mcp",
                "headers": {"X-Key": "${secret:svc/header.X-Key}"},
                "tool_timeout": 45,
            },
            "secrets": {},
        },
    )

    from deeptutor.services.mcp.secrets import resolve_references, secret_reference

    assert resolve_references("u_ada", secret_reference("svc", "header.X-Key")) == "sk-1"
    stored = (tmp_path / "data" / "system" / "user-mcp" / "u_ada.json").read_text(encoding="utf-8")
    assert "${secret:svc/header.X-Key}" in stored


def test_the_servers_list_warms_connections_so_status_is_real(client: TestClient) -> None:
    """Nothing else on this route connects them.

    ``ensure_scope`` otherwise runs only at turn time, so the page would sit on
    "connecting / 0 tools" until the user happened to send a message.
    """
    manager = space_mcp.get_mcp_manager()
    client.get("/api/v1/space/mcp/servers")
    assert manager.warmed == ["_shared", "u_ada"]


def test_testing_a_draft_writes_nothing(client: TestClient, tmp_path: Path) -> None:
    """Test must be side-effect free — including under a scratch name.

    Storing the draft's credentials would both surprise the caller and, for a
    name the store itself refuses, raise where a probe result was expected.
    """
    import deeptutor.services.mcp.manager as manager_module

    async def _probe(cfg: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "tools": [], "error": ""}

    original = space_mcp.probe_server
    space_mcp.probe_server = _probe  # type: ignore[assignment]
    try:
        response = client.post(
            "/api/v1/space/mcp/servers/_draft/test",
            json={
                "config": {"url": "https://svc.example/mcp"},
                "secrets": {"api_key": "sk-1"},
            },
        )
    finally:
        space_mcp.probe_server = original  # type: ignore[assignment]

    assert response.status_code == 200
    assert not (tmp_path / "data" / "system" / "user-mcp" / "u_ada.json").exists()
    _ = manager_module
