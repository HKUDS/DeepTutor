"""Request-scoped regression coverage for generated-output downloads."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.services.auth import TokenPayload
from deeptutor.services.path_service import PathService

OutputAppFactory = Callable[[dict[str, TokenPayload | None]], tuple[TestClient, PathService, Path]]


@pytest.fixture
def output_app(monkeypatch, tmp_path) -> OutputAppFactory:
    from deeptutor.api import main as api_main
    from deeptutor.multi_user import paths as multi_user_paths

    admin_root = tmp_path / "data"
    users_root = admin_root / "users"
    admin_service = PathService(workspace_root=admin_root)
    admin_service.get_public_outputs_root().mkdir(parents=True)

    monkeypatch.setattr(api_main, "AUTH_ENABLED", True)
    monkeypatch.setattr(multi_user_paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(multi_user_paths, "_path_services", {})

    def make_app(tokens: dict[str, TokenPayload | None]) -> tuple[TestClient, PathService, Path]:
        monkeypatch.setattr(api_main, "decode_token", lambda token: tokens.get(token))
        app = FastAPI()
        app.mount(
            "/api/outputs",
            api_main.SafeOutputStaticFiles(
                directory=str(admin_service.get_public_outputs_root()),
                path_service=admin_service,
            ),
        )
        return TestClient(app), admin_service, users_root

    return make_app


def _write_output(root: Path, relative_path: str, contents: bytes) -> None:
    output = root / "user" / relative_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(contents)


def test_authenticated_user_downloads_output_from_own_workspace(output_app) -> None:
    relative_path = "workspace/chat/chat/session-1/code_runs/report.pdf"
    alice = TokenPayload(username="alice", role="user", user_id="u_alice")
    client, _admin_service, users_root = output_app({"alice-token": alice})
    _write_output(users_root / "u_alice", relative_path, b"alice report")

    with client:
        response = client.get(f"/api/outputs/{relative_path}", cookies={"dt_token": "alice-token"})

    assert response.status_code == 200
    assert response.content == b"alice report"


def test_same_output_url_is_isolated_between_users(output_app) -> None:
    relative_path = "workspace/chat/chat/session-1/code_runs/report.docx"
    tokens = {
        "alice-token": TokenPayload(username="alice", role="user", user_id="u_alice"),
        "bob-token": TokenPayload(username="bob", role="user", user_id="u_bob"),
        "carol-token": TokenPayload(username="carol", role="user", user_id="u_carol"),
    }
    client, _admin_service, users_root = output_app(tokens)
    _write_output(users_root / "u_alice", relative_path, b"alice document")
    _write_output(users_root / "u_bob", relative_path, b"bob document")

    with client:
        alice_response = client.get(
            f"/api/outputs/{relative_path}", cookies={"dt_token": "alice-token"}
        )
        bob_response = client.get(
            f"/api/outputs/{relative_path}", cookies={"dt_token": "bob-token"}
        )
        missing_response = client.get(
            f"/api/outputs/{relative_path}", cookies={"dt_token": "carol-token"}
        )

    assert alice_response.content == b"alice document"
    assert bob_response.content == b"bob document"
    assert missing_response.status_code == 404
    assert "u_alice" not in missing_response.text
    assert "u_bob" not in missing_response.text


@pytest.mark.parametrize("cookie", [None, "malformed-token", "expired-token"])
def test_invalid_auth_does_not_fall_back_to_admin_output(output_app, cookie) -> None:
    relative_path = "workspace/chat/chat/session-1/code_runs/admin.pdf"
    client, admin_service, _users_root = output_app(
        {"malformed-token": None, "expired-token": None}
    )
    _write_output(admin_service.workspace_root, relative_path, b"admin secret")
    cookies = {} if cookie is None else {"dt_token": cookie}

    with client:
        response = client.get(f"/api/outputs/{relative_path}", cookies=cookies)

    assert response.status_code == 404
    assert "admin secret" not in response.text
    assert str(admin_service.workspace_root) not in response.text


def test_auth_disabled_uses_local_admin_output(output_app, monkeypatch) -> None:
    from deeptutor.api import main as api_main

    relative_path = "workspace/chat/chat/session-1/code_runs/local.pdf"
    client, admin_service, _users_root = output_app({})
    monkeypatch.setattr(api_main, "AUTH_ENABLED", False)
    _write_output(admin_service.workspace_root, relative_path, b"local output")

    with client:
        response = client.get(f"/api/outputs/{relative_path}")

    assert response.status_code == 200
    assert response.content == b"local output"


def test_private_suffix_is_rejected_for_authenticated_user(output_app) -> None:
    relative_path = "workspace/chat/chat/session-1/code_runs/private.json"
    alice = TokenPayload(username="alice", role="user", user_id="u_alice")
    client, _admin_service, users_root = output_app({"alice-token": alice})
    _write_output(users_root / "u_alice", relative_path, b'{"secret": true}')

    with client:
        response = client.get(f"/api/outputs/{relative_path}", cookies={"dt_token": "alice-token"})

    assert response.status_code == 404
    assert "secret" not in response.text


def test_traversal_is_rejected_for_authenticated_user(output_app) -> None:
    alice = TokenPayload(username="alice", role="user", user_id="u_alice")
    client, _admin_service, users_root = output_app({"alice-token": alice})
    user_root = users_root / "u_alice"
    escaped_file = user_root / "secret.pdf"
    escaped_file.parent.mkdir(parents=True, exist_ok=True)
    escaped_file.write_bytes(b"outside public root")

    with client:
        response = client.get("/api/outputs/%2E%2E/secret.pdf", cookies={"dt_token": "alice-token"})

    assert response.status_code == 404
    assert "outside public root" not in response.text
