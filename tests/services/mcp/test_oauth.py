"""MCP OAuth: where the grant lives, and who is allowed to complete one.

A refresh token here authorises *a person's* account on a third-party service, so
the properties worth pinning are about isolation and about which callbacks may
finish a flow — not about the protocol, which is the SDK's.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import stat

import pytest

from deeptutor.services.mcp import oauth


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


def _token(access: str = "tok-1", refresh: str = "ref-1") -> object:
    from mcp.shared.auth import OAuthToken

    return OAuthToken(access_token=access, token_type="Bearer", refresh_token=refresh, scope="read")


async def _store(owner: str, server: str, access: str = "tok-1") -> None:
    await oauth.OwnerTokenStorage(owner, server).set_tokens(_token(access))


# ── where the grant lives ─────────────────────────────────────────────────


def test_the_store_is_outside_every_sandbox_mounted_tree(roots: Path) -> None:
    """The exec sandbox mounts the workspace roots; it never mounts data/system.

    A refresh token readable from a sandboxed shell is, in a multi-account
    deployment, readable by every other account.
    """
    asyncio.run(_store("u_ada", "notion"))
    path = oauth._store_path("u_ada", "notion")

    assert path.is_relative_to(roots / "system")
    assert not path.is_relative_to(roots / "users")
    assert not path.is_relative_to(roots / "user" / "workspace")


def test_the_store_file_is_owner_only(roots: Path) -> None:
    asyncio.run(_store("u_ada", "notion"))
    path = oauth._store_path("u_ada", "notion")

    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
    assert stat.S_IMODE(path.parent.stat().st_mode) == stat.S_IRWXU


def test_one_accounts_grant_is_invisible_to_another(roots: Path) -> None:
    asyncio.run(_store("u_ada", "notion", access="ada-token"))

    assert oauth.oauth_state("u_bob", "notion").authorized is False
    bob = asyncio.run(oauth.OwnerTokenStorage("u_bob", "notion").get_tokens())
    assert bob is None


def test_two_servers_for_one_account_do_not_share_a_grant(roots: Path) -> None:
    asyncio.run(_store("u_ada", "notion", access="notion-token"))

    assert oauth.oauth_state("u_ada", "linear").authorized is False


@pytest.mark.parametrize("server", ["../escape", "a/b", "", ".hidden", "x" * 65])
def test_an_unsafe_server_name_cannot_address_a_file(server: str) -> None:
    """The name becomes a filename, exactly as in the static secret store."""
    with pytest.raises(ValueError, match="Unsafe"):
        oauth._store_path("u_ada", server)


def test_state_reports_presence_and_never_the_token(roots: Path) -> None:
    asyncio.run(_store("u_ada", "notion", access="super-secret"))

    state = oauth.oauth_state("u_ada", "notion")

    assert state.authorized is True
    assert state.scope == "read"
    assert "super-secret" not in repr(state)


def test_a_torn_store_reads_as_unauthorized(roots: Path) -> None:
    """Rather than failing every connect: this sends the account back through
    consent, which is recoverable."""
    asyncio.run(_store("u_ada", "notion"))
    oauth._store_path("u_ada", "notion").write_text("{ truncated", encoding="utf-8")

    assert oauth.oauth_state("u_ada", "notion").authorized is False


def test_a_token_and_a_client_registration_share_one_file(roots: Path) -> None:
    from mcp.shared.auth import OAuthClientInformationFull

    storage = oauth.OwnerTokenStorage("u_ada", "notion")
    asyncio.run(storage.set_tokens(_token()))
    asyncio.run(
        storage.set_client_info(
            OAuthClientInformationFull.model_validate(
                {
                    "client_id": "cid-1",
                    "redirect_uris": ["https://x.example/cb"],
                    "token_endpoint_auth_method": "client_secret_post",
                }
            )
        )
    )

    saved = json.loads(oauth._store_path("u_ada", "notion").read_text(encoding="utf-8"))
    assert saved["tokens"]["access_token"] == "tok-1"
    assert saved["client"]["client_id"] == "cid-1"
    # A refresh rotates the token without disturbing the registration.
    asyncio.run(storage.set_tokens(_token(access="tok-2")))
    saved = json.loads(oauth._store_path("u_ada", "notion").read_text(encoding="utf-8"))
    assert saved["tokens"]["access_token"] == "tok-2"
    assert saved["client"]["client_id"] == "cid-1"


def test_forget_drops_the_registration_with_the_tokens(roots: Path) -> None:
    """The registration belongs to the consent being discarded; reusing it would
    record a fresh consent against the old identity."""
    from mcp.shared.auth import OAuthClientInformationFull

    storage = oauth.OwnerTokenStorage("u_ada", "notion")
    asyncio.run(storage.set_tokens(_token()))
    asyncio.run(
        storage.set_client_info(
            OAuthClientInformationFull.model_validate(
                {"client_id": "cid-1", "redirect_uris": ["https://x.example/cb"]}
            )
        )
    )

    oauth.forget("u_ada", "notion")

    assert oauth.oauth_state("u_ada", "notion").authorized is False
    assert asyncio.run(storage.get_client_info()) is None


def test_forgetting_an_unsafe_name_is_a_no_op() -> None:
    oauth.forget("u_ada", "../escape")  # must not raise


# ── who may complete a flow ───────────────────────────────────────────────


def test_an_unknown_state_completes_nothing() -> None:
    """A forged or replayed callback must not be able to finish a consent."""
    assert oauth.complete_authorization("never-issued", "code-1") is False


def test_a_state_cannot_be_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _exercise() -> tuple[bool, bool]:
        loop = asyncio.get_running_loop()
        flow = oauth._PendingFlow(owner_id="u_ada", server="notion", result=loop.create_future())
        monkeypatch.setitem(oauth._PENDING, "state-1", flow)
        first = oauth.complete_authorization("state-1", "code-1")
        second = oauth.complete_authorization("state-1", "code-2")
        return first, second

    first, second = asyncio.run(_exercise())
    assert first is True
    assert second is False, "the second callback for one state must not win"


def test_completing_a_flow_hands_the_code_to_its_own_waiter() -> None:
    async def _exercise() -> tuple[str, str | None]:
        loop = asyncio.get_running_loop()
        flow = oauth._PendingFlow(owner_id="u_ada", server="notion", result=loop.create_future())
        oauth._PENDING["state-xyz"] = flow
        try:
            assert oauth.complete_authorization("state-xyz", "the-code") is True
            return await asyncio.wait_for(flow.result, timeout=1)
        finally:
            oauth._PENDING.pop("state-xyz", None)

    code, state = asyncio.run(_exercise())
    assert code == "the-code"
    assert state == "state-xyz"


# ── who may start one ─────────────────────────────────────────────────────


def test_the_non_interactive_form_refuses_to_open_a_consent() -> None:
    """A background reconnect has nobody in front of it. Blocking there would
    hang the connection task on a screen nothing will ever open.

    (That the refusal really reaches the caller through the SDK was verified
    against Notion's live server; here the rule itself is pinned.)"""
    redirect, callback = oauth.refusing_handlers("notion")

    with pytest.raises(oauth.AuthorizationRequired):
        asyncio.run(redirect("https://consent.example/authorize"))
    with pytest.raises(oauth.AuthorizationRequired):
        asyncio.run(callback())


def test_build_auth_produces_an_httpx_auth(roots: Path) -> None:
    import httpx

    auth = oauth.build_auth(
        server_url="https://mcp.example/mcp",
        server_name="notion",
        owner_id="u_ada",
        redirect_uri="https://app.example/cb",
    )
    assert isinstance(auth, httpx.Auth), "it attaches to the client the transport builds"


def test_the_refusal_names_the_server_that_needs_authorizing() -> None:
    exc = oauth.AuthorizationRequired("notion")
    assert exc.server_name == "notion"
    assert "notion" in str(exc)


def test_a_needs_auth_failure_is_not_classified_as_broken() -> None:
    """The store shows a Connect button for one and an error for the other."""
    from deeptutor.services.mcp.manager import _needs_authorization

    wrapped = ExceptionGroup("tg", [oauth.AuthorizationRequired("notion")])

    assert _needs_authorization(wrapped) is True
    assert _needs_authorization(ExceptionGroup("tg", [RuntimeError("500")])) is False


# ── the redirect URI ──────────────────────────────────────────────────────


def test_the_redirect_uri_follows_the_browsing_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """So the common deployment needs no configuration at all."""
    monkeypatch.delenv("DEEPTUTOR_PUBLIC_URL", raising=False)

    assert oauth.oauth_redirect_uri("https://tutor.example.edu") == (
        f"https://tutor.example.edu{oauth.CALLBACK_PATH}"
    )


def test_an_operator_who_states_the_public_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reverse proxy terminates on a hostname the app never sees."""
    monkeypatch.setenv("DEEPTUTOR_PUBLIC_URL", "https://public.example/")

    assert oauth.oauth_redirect_uri("http://internal:8001") == (
        f"https://public.example{oauth.CALLBACK_PATH}"
    )


def test_the_client_registration_declares_exactly_one_redirect(monkeypatch) -> None:
    monkeypatch.delenv("DEEPTUTOR_PUBLIC_URL", raising=False)
    metadata = oauth.client_metadata(oauth.oauth_redirect_uri("https://x.example"))

    assert [str(uri) for uri in metadata.redirect_uris] == [
        f"https://x.example{oauth.CALLBACK_PATH}"
    ]
    assert "refresh_token" in metadata.grant_types, "without it every session needs re-consent"
    assert metadata.client_name == "DeepTutor"
