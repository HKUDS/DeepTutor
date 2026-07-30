"""OAuth 2.1 for MCP servers that require it.

Most hosted MCP servers moved to OAuth: Notion, Linear, Sentry, Asana, monday,
Canva and Prisma all answer an unauthenticated request with ``401``. A store that
only knows how to put a static API key in a header cannot offer any of them, so
this module adds the missing half.

The protocol work is the MCP SDK's — :class:`mcp.client.auth.OAuthClientProvider`
does discovery (RFC 9728 → RFC 8414), dynamic client registration (RFC 7591),
authorization-code + PKCE, and refresh. It is an ``httpx.Auth``, so it attaches
to the client each transport already builds and no transport shape changes. What
this module owns is the three things the SDK delegates:

**Where the tokens live.** Per ``(owner, server)`` under the owner's secrets
tree — the one branch of ``data/`` the exec sandbox never mounts. A refresh token
authorises *a person's* account on a third-party service; anything a sandboxed
shell can read is, in a multi-account deployment, readable by every account. The
sibling module :mod:`deeptutor.services.mcp.secrets` holds static credentials in
the same tree for the same reason.

**Who may start a flow.** Only an explicit user action. A background reconnect
has no human in front of it, so it must never block on a consent screen: the
non-interactive path raises :class:`AuthorizationRequired` the moment the SDK
asks to redirect, and the server's status becomes ``needs_auth`` so the UI can
offer a Connect button instead of retrying forever.

**What we tell the provider about ourselves.** One client registration per
``(owner, server)``, stored beside the tokens. Registrations are not shared
across accounts: a client id issued for one person's consent must not become the
identity another person's consent is recorded against.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import stat
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    import httpx
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)

#: Subdirectory of the owner's secrets tree. A sibling of ``private/mcp`` (static
#: credentials) rather than the same file: one holds a flat key→value map, this
#: holds a token set plus a client registration.
_OAUTH_SUBDIR = ("private", "mcp-oauth")

#: Same rule as the static secret store: the server name becomes a filename.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

#: How DeepTutor introduces itself on a consent screen.
CLIENT_NAME = "DeepTutor"
CLIENT_URI = "https://deeptutor.info"


class AuthorizationRequired(RuntimeError):
    """This server needs a person to authorise it, and nobody is present.

    Raised from the non-interactive redirect handler, so a background reconnect
    reports "needs authorization" instead of hanging on a consent screen that
    nothing will ever open.
    """

    def __init__(self, server_name: str) -> None:
        super().__init__(f"MCP server {server_name!r} needs to be authorized")
        self.server_name = server_name


@dataclass(frozen=True, slots=True)
class OAuthState:
    """What the UI needs to know about one server's authorization."""

    authorized: bool
    #: Present once authorized: which scopes the provider granted.
    scope: str = ""


# ── storage ───────────────────────────────────────────────────────────────


def _store_path(owner_id: str, server: str) -> Path:
    from deeptutor.multi_user.paths import owner_secrets_dir

    if not _SAFE_NAME_RE.match(server):
        raise ValueError(f"Unsafe MCP server name for an OAuth store: {server!r}")
    path = owner_secrets_dir(owner_id)
    for part in _OAUTH_SUBDIR:
        path = path / part
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)
    return path / f"{server}.json"


def _read(owner_id: str, server: str) -> dict[str, Any]:
    try:
        path = _store_path(owner_id, server)
    except ValueError:
        return {}
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A torn or hand-edited file reads as "not authorized", which sends the
        # account back through consent rather than failing every connect.
        logger.warning("unreadable MCP OAuth store at %s; treating as empty", path)
        return {}
    return data if isinstance(data, dict) else {}


def _write(owner_id: str, server: str, data: dict[str, Any]) -> None:
    path = _store_path(owner_id, server)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def forget(owner_id: str, server: str) -> None:
    """Drop this server's tokens and client registration.

    Called when a server is deleted or re-authorized. Removing the *registration*
    too is deliberate: it belongs to the consent that is being discarded, and
    reusing it against a fresh consent conflates two grants.
    """
    try:
        _store_path(owner_id, server).unlink(missing_ok=True)
    except ValueError:
        return


def oauth_state(owner_id: str, server: str) -> OAuthState:
    """Whether *server* is authorized for *owner_id*. Never returns a token."""
    tokens = _read(owner_id, server).get("tokens")
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        return OAuthState(authorized=False)
    return OAuthState(authorized=True, scope=str(tokens.get("scope") or ""))


class OwnerTokenStorage:
    """:class:`mcp.client.auth.TokenStorage` over one owner's secrets tree.

    One instance per ``(owner, server)``. The SDK calls these four methods; every
    read and write goes to the same 0600 file, so a refresh that rotates the
    token persists without any other bookkeeping.
    """

    def __init__(self, owner_id: str, server: str) -> None:
        self._owner = owner_id
        self._server = server

    async def get_tokens(self) -> "OAuthToken | None":
        from mcp.shared.auth import OAuthToken

        raw = _read(self._owner, self._server).get("tokens")
        if not isinstance(raw, dict):
            return None
        try:
            return OAuthToken.model_validate(raw)
        except Exception:
            logger.warning("stored MCP OAuth token for %s is unusable", self._server)
            return None

    async def set_tokens(self, tokens: "OAuthToken") -> None:
        data = _read(self._owner, self._server)
        data["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        _write(self._owner, self._server, data)

    async def get_client_info(self) -> "OAuthClientInformationFull | None":
        from mcp.shared.auth import OAuthClientInformationFull

        raw = _read(self._owner, self._server).get("client")
        if not isinstance(raw, dict):
            return None
        try:
            return OAuthClientInformationFull.model_validate(raw)
        except Exception:
            # A registration we cannot parse is worse than none: the SDK would
            # authenticate with a half-built client. Re-register instead.
            logger.warning("stored MCP OAuth client for %s is unusable", self._server)
            return None

    async def set_client_info(self, client_info: "OAuthClientInformationFull") -> None:
        data = _read(self._owner, self._server)
        data["client"] = client_info.model_dump(mode="json", exclude_none=True)
        _write(self._owner, self._server, data)


# ── provider construction ─────────────────────────────────────────────────


#: Path the provider sends the browser back to. Mounted by the API router.
CALLBACK_PATH = "/api/v1/space/mcp/oauth/callback"

#: Where the app believes it is reachable. Overridable because a reverse proxy
#: terminates on a hostname the app never sees, and the redirect URI has to be
#: the one the *browser* can reach.
_PUBLIC_URL_ENV = "DEEPTUTOR_PUBLIC_URL"

#: Single-container compose publishes the frontend here (see docker-compose.yml).
_DEFAULT_PUBLIC_URL = "http://localhost:3782"


def oauth_redirect_uri(origin: str = "") -> str:
    """The redirect URI to register and to expect the browser back on.

    *origin* is the origin the person is actually browsing, which the route that
    starts a flow can read off its own request — that makes the common
    deployment work with no configuration. ``DEEPTUTOR_PUBLIC_URL`` overrides it
    for a reverse proxy that rewrites the host, and it wins on purpose: an
    operator who has stated the public URL means it.

    A registration is bound to its redirect URI, so changing this invalidates
    existing ones; :func:`forget` clears the pair together.
    """
    configured = os.environ.get(_PUBLIC_URL_ENV, "").strip().rstrip("/")
    base = configured or origin.strip().rstrip("/") or _DEFAULT_PUBLIC_URL
    return f"{base}{CALLBACK_PATH}"


def client_metadata(redirect_uri: str) -> "Any":
    """How DeepTutor registers itself with an authorization server."""
    from mcp.shared.auth import OAuthClientMetadata

    # Validated through the model rather than constructed with bare strings: the
    # SDK's fields are `AnyUrl`, and a redirect URI that is not a URL has to fail
    # here rather than at the authorization server.
    return OAuthClientMetadata.model_validate(
        {
            "client_name": CLIENT_NAME,
            "client_uri": CLIENT_URI,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
        }
    )
    # No `scope`: the MCP spec lets the authorization server decide, and asking
    # for scopes we do not understand is how a consent screen gets refused.


def build_auth(
    *,
    server_url: str,
    server_name: str,
    owner_id: str,
    redirect_uri: str,
    redirect_handler: Any = None,
    callback_handler: Any = None,
) -> "httpx.Auth":
    """An ``httpx.Auth`` that authenticates MCP requests to *server_url*.

    With no handlers this is the **non-interactive** form: it will use and refresh
    stored tokens, and raise :class:`AuthorizationRequired` rather than start a
    flow. Passing handlers makes it interactive, which only the route that a
    person clicked may do.
    """
    from mcp.client.auth import OAuthClientProvider

    refuse_redirect, refuse_callback = refusing_handlers(server_name)
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=client_metadata(redirect_uri),
        storage=OwnerTokenStorage(owner_id, server_name),
        redirect_handler=redirect_handler or refuse_redirect,
        callback_handler=callback_handler or refuse_callback,
    )


def refusing_handlers(server_name: str) -> tuple[Any, Any]:
    """The handler pair a *non-interactive* caller gets.

    Named rather than inlined so the rule has somewhere to be tested: a
    connection task has nobody in front of it, so the moment the SDK wants to
    open a consent screen the answer is "a person has to do this", immediately,
    rather than a coroutine that never returns.
    """

    async def _redirect(_authorize_url: str) -> None:
        raise AuthorizationRequired(server_name)

    async def _callback() -> tuple[str, str | None]:
        raise AuthorizationRequired(server_name)

    return _redirect, _callback


# ── the interactive flow ──────────────────────────────────────────────────


@dataclass(slots=True)
class _PendingFlow:
    """One consent in progress."""

    owner_id: str
    server: str
    #: Resolved by the callback route with ``(code, state)``.
    result: "asyncio.Future[tuple[str, str | None]]"
    #: Set once the SDK hands us the URL to send the person to.
    authorize_url: str = ""
    task: "asyncio.Task[None] | None" = None


#: Flows awaiting a callback, keyed by the ``state`` the SDK generated.
#:
#: Keyed on ``state`` rather than on ``(owner, server)`` because ``state`` is what
#: comes back on the redirect, and matching a callback to a flow by anything the
#: *caller* supplies would let one person's redirect complete another's consent.
_PENDING: "dict[str, _PendingFlow]" = {}

#: A consent screen left open forever is a leaked task and a leaked pending entry.
FLOW_TIMEOUT_S = 600.0


async def begin_authorization(
    *,
    server_url: str,
    server_name: str,
    owner_id: str,
    redirect_uri: str,
) -> str:
    """Start a consent flow and return the URL to send the person to.

    The SDK drives the whole exchange, so this runs it as a task and waits only
    for the point where it produces an authorize URL; the task then blocks on the
    callback future until the route resolves it.

    Any previous authorization for this server is discarded first: re-authorizing
    means the stored grant is unwanted, and keeping a client registration issued
    for it would record the new consent against the old identity.
    """
    import asyncio

    forget(owner_id, server_name)
    loop = asyncio.get_running_loop()
    url_ready: asyncio.Future[str] = loop.create_future()
    flow = _PendingFlow(owner_id=owner_id, server=server_name, result=loop.create_future())

    async def _redirect(authorize_url: str) -> None:
        flow.authorize_url = authorize_url
        # `state` is inside the URL the SDK built; it is the only value the
        # provider will echo back, so it is what the callback can be matched on.
        state = _state_from(authorize_url)
        if not state:
            if not url_ready.done():
                url_ready.set_exception(
                    RuntimeError("authorization URL carried no state parameter")
                )
            return
        _PENDING[state] = flow
        if not url_ready.done():
            url_ready.set_result(authorize_url)

    async def _callback() -> tuple[str, str | None]:
        return await flow.result

    async def _drive() -> None:
        # Touching the server is what makes the SDK notice it has no token and
        # start the flow; the request itself is expected to fail or succeed
        # afterwards and its outcome is not interesting here.
        import httpx

        auth = build_auth(
            server_url=server_url,
            server_name=server_name,
            owner_id=owner_id,
            redirect_uri=redirect_uri,
            redirect_handler=_redirect,
            callback_handler=_callback,
        )
        try:
            async with httpx.AsyncClient(auth=auth, timeout=30.0) as client:
                await client.post(server_url, json={})
        except Exception as exc:  # noqa: BLE001 - reported through the futures
            if not url_ready.done():
                url_ready.set_exception(exc)
        finally:
            for key, pending in list(_PENDING.items()):
                if pending is flow:
                    _PENDING.pop(key, None)

    flow.task = asyncio.create_task(_drive(), name=f"mcp-oauth-{server_name}")
    try:
        return await asyncio.wait_for(url_ready, timeout=30.0)
    except Exception:
        flow.task.cancel()
        raise


def complete_authorization(state: str, code: str) -> bool:
    """Hand a redirect's ``code`` to the flow that started it.

    Returns ``False`` for a ``state`` nothing is waiting on — a replayed or forged
    callback, which must not be able to complete anything.
    """
    flow = _PENDING.pop(state, None)
    if flow is None or flow.result.done():
        return False
    flow.result.set_result((code, state))
    return True


def _state_from(authorize_url: str) -> str:
    from urllib.parse import parse_qs, urlsplit

    return (parse_qs(urlsplit(authorize_url).query).get("state") or [""])[0]


__all__ = [
    "CALLBACK_PATH",
    "CLIENT_NAME",
    "FLOW_TIMEOUT_S",
    "begin_authorization",
    "complete_authorization",
    "AuthorizationRequired",
    "OAuthState",
    "OwnerTokenStorage",
    "build_auth",
    "client_metadata",
    "forget",
    "oauth_redirect_uri",
    "oauth_state",
    "refusing_handlers",
]
