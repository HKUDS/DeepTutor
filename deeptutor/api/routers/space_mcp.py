"""
Per-user MCP API
================

The servers an individual configures for themselves, mounted at
``/api/v1/space/mcp``. Auth-gated, **not** admin-gated: this is the whole point
of the surface — a learner adds the hosted services they use without an
administrator in the loop.

What keeps that safe is narrow rather than trusting:

* **remote transports only** — a ``stdio`` server is a command run on the host
  as the app user, so it stays in the admin registry
  (``/api/v1/settings/mcp``) permanently;
* **credentials are stored apart from the config** and never returned; a field
  reports only whether it is configured;
* **every write is scoped to the caller's own file** — the owner is resolved
  server-side and is never accepted from the request.

Deployment servers stay visible here read-only, so "which tools do I have?" has
one answer instead of two.
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError

from deeptutor.core.i18n import t
from deeptutor.multi_user.paths import current_owner_id
from deeptutor.services.mcp import MCPServerConfig, get_mcp_manager, load_mcp_config, oauth
from deeptutor.services.mcp.catalog import (
    build_server_config,
    category_counts,
    get_entry,
    search_catalog,
)
from deeptutor.services.mcp.manager import (
    SHARED_OWNER,
    describe_connect_failure,
    probe_server,
)
from deeptutor.services.mcp.secrets import configured_fields, delete_secrets, store_secrets
from deeptutor.services.mcp.user_config import (
    MAX_SERVERS_PER_OWNER,
    UserMcpError,
    assert_name_available,
    delete_user_server,
    load_user_mcp_config,
    save_user_server,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: Ceiling on warming connections while rendering the servers list. Long enough
#: for a healthy hosted server, short enough that a dead one does not hold the
#: page open.
_STATUS_WARM_TIMEOUT_S = 5.0


class ServerPayload(BaseModel):
    """A server definition plus the credential values to store beside it."""

    config: MCPServerConfig
    #: Field name → value. Values are written to the owner's secrets store and
    #: never echoed back; an empty string clears a stored field.
    secrets: dict[str, str] = Field(default_factory=dict)


class InstallPayload(BaseModel):
    """Install a catalog entry, optionally under a different local name."""

    name: str = ""
    secrets: dict[str, str] = Field(default_factory=dict)


def _shared_names() -> set[str]:
    return set(load_mcp_config().servers)


def _refuse(exc: UserMcpError) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})


@router.get("/servers")
async def list_servers() -> dict[str, Any]:
    """This surface's servers, in the same shape the admin registry returns.

    ``servers`` + ``status`` deliberately mirror ``/settings/mcp`` so the two
    surfaces share one set of frontend components instead of forking over a
    response shape. Everything specific to this surface is additive.
    """
    owner = current_owner_id()
    config, rejected = load_user_mcp_config(owner)
    manager = get_mcp_manager()
    # Warm both scopes before reporting status. Nothing else on this route would
    # connect them — ``ensure_scope`` otherwise runs only at turn time — so the
    # page would sit on "connecting / 0 tools" until the user happened to send a
    # message. Bounded and best-effort: a slow third-party host costs its own
    # row's status, not the page.
    for warm in (manager.ensure_started(), manager.ensure_scope(owner)):
        try:
            await asyncio.wait_for(warm, timeout=_STATUS_WARM_TIMEOUT_S)
        except Exception:
            logger.debug("MCP status warm-up did not finish for owner %s", owner, exc_info=True)
    return {
        "servers": {name: cfg.model_dump(mode="json") for name, cfg in config.servers.items()},
        "status": manager.status(owner),
        # Which credentials exist per server, never what they are.
        "configured_secrets": {
            name: sorted(configured_fields(owner, name)) for name in config.servers
        },
        # Which OAuth-backed servers this account has authorized. Presence only —
        # a token never leaves the backend.
        "oauth": {
            name: {"required": True, "authorized": oauth.oauth_state(owner, name).authorized}
            for name, cfg in config.servers.items()
            if cfg.auth == "oauth"
        },
        "rejected": [{"name": row.name, "reason": row.reason} for row in rejected],
        "deployment": {
            # Read-only context: an account cannot edit these but should be able
            # to see which tools it already has through them.
            "servers": sorted(_shared_names()),
            "status": manager.status(SHARED_OWNER),
        },
        "limits": {"max_servers": MAX_SERVERS_PER_OWNER},
    }


@router.put("/servers/{name}")
async def upsert_server(name: str, payload: ServerPayload) -> dict[str, Any]:
    owner = current_owner_id()
    try:
        assert_name_available(name, shared_names=_shared_names())
        cfg, secrets = _extract_credentials(owner, name, payload)
        # Off the loop: the write validates the URL, which resolves DNS, and a
        # dead resolver would otherwise stall every request in the process.
        await asyncio.to_thread(save_user_server, owner, name, cfg)
    except UserMcpError as exc:
        raise _refuse(exc) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if secrets:
        store_secrets(owner, name, secrets)
    await get_mcp_manager().reload_scope(owner)
    return await list_servers()


@router.delete("/servers/{name}")
async def remove_server(name: str) -> dict[str, Any]:
    owner = current_owner_id()
    delete_user_server(owner, name)
    delete_secrets(owner, name)
    # An OAuth grant outlives the config row unless it is dropped with it; a
    # refresh token for a server nobody can see is a credential with no owner.
    oauth.forget(owner, name)
    await get_mcp_manager().reload_scope(owner)
    return await list_servers()


@router.post("/servers/{name}/authorize")
async def authorize_server(name: str, request: Request) -> dict[str, Any]:
    """Begin an OAuth consent for one of the caller's servers.

    Returns the URL to send the person to. This is the **only** place a flow may
    start: a background reconnect has nobody in front of it, so it reports
    ``needs_auth`` and waits for someone to click.
    """
    owner = current_owner_id()
    config, _ = load_user_mcp_config(owner)
    cfg = config.servers.get(name)
    if cfg is None:
        raise HTTPException(status_code=404, detail=t("mcp.server_missing", name=name))
    if cfg.auth != "oauth":
        raise HTTPException(
            status_code=400,
            detail={"code": "mcp.not_oauth", "message": t("mcp.not_oauth")},
        )
    try:
        url = await oauth.begin_authorization(
            server_url=cfg.url,
            server_name=name,
            owner_id=owner,
            # The origin the person is actually browsing, so the redirect comes
            # back somewhere their browser can reach without any configuration.
            redirect_uri=oauth.oauth_redirect_uri(_request_origin(request)),
        )
    except Exception as exc:
        logger.warning("could not start MCP OAuth for %s/%s", owner, name, exc_info=True)
        raise HTTPException(
            status_code=400,
            detail={
                "code": "mcp.oauth_start_failed",
                "message": describe_connect_failure(exc),
            },
        ) from exc
    return {"authorize_url": url}


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = "", state: str = "", error: str = "", error_description: str = ""
) -> Response:
    """Where the authorization server sends the browser back.

    Deliberately **not** returning JSON: a person is looking at this, having just
    clicked Approve on somebody else's site. It answers with a small page that
    says what happened and closes itself.

    An unknown ``state`` completes nothing — see ``complete_authorization``.
    """
    if error:
        return _callback_page(False, error_description or error)
    if not code or not state:
        return _callback_page(False, t("mcp.oauth_callback_incomplete"))
    if not oauth.complete_authorization(state, code):
        return _callback_page(False, t("mcp.oauth_callback_unknown"))
    return _callback_page(True, "")


def _request_origin(request: Request) -> str:
    """The origin this request arrived on, honouring a reverse proxy's headers."""
    headers = request.headers
    proto = headers.get("x-forwarded-proto", "").split(",")[0].strip() or request.url.scheme
    host = headers.get("x-forwarded-host", "").split(",")[0].strip() or headers.get("host", "")
    return f"{proto}://{host}" if host else ""


def _callback_page(ok: bool, message: str) -> Response:
    """A minimal self-closing page. No app shell — this tab is disposable."""
    title = t("mcp.oauth_done") if ok else t("mcp.oauth_failed")
    detail = "" if ok else f"<p class='d'>{html.escape(message)}</p>"
    body = f"""<!doctype html><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
 body{{font:15px/1.6 system-ui,sans-serif;margin:0;display:grid;place-items:center;
 min-height:100vh;background:#fafafa;color:#1c1c1c}}
 .c{{text-align:center;padding:28px 32px}}
 .d{{color:#8a6d3b;font-size:13px;max-width:34rem;word-break:break-word}}
 @media(prefers-color-scheme:dark){{body{{background:#111;color:#e8e8e8}}}}
</style>
<div class="c"><p>{html.escape(title)}</p>{detail}
<script>setTimeout(function(){{window.close()}},{1200 if ok else 6000})</script></div>"""
    return Response(content=body, media_type="text/html", status_code=200 if ok else 400)


@router.post("/servers/{name}/test")
async def test_server(name: str, payload: ServerPayload) -> dict[str, Any]:
    """Probe a definition before saving it.

    Runs under the caller's own owner id so the probe obeys the same address
    policy and redirect rule the real connection will — a Test more permissive
    than the connection it previews is worse than no Test at all.

    Deliberately side-effect free: nothing is written, so the incoming config is
    probed as given (any literal credential in it is used in memory only). That
    also means a caller may probe under a scratch name the store would refuse,
    which is how the UI tests a draft before it has one.
    """
    _ = name  # part of the path for symmetry with PUT; the probe is stateless
    owner = current_owner_id()
    resolved = _resolve_for_probe(owner, payload.config)
    return await probe_server(resolved, owner=owner)


def _resolve_for_probe(owner: str, config: MCPServerConfig) -> MCPServerConfig:
    """Fill in stored credentials the draft did not re-enter.

    An edit form shows a saved credential as "configured" rather than echoing
    it, so the draft it submits still carries the reference. Testing that draft
    has to resolve it — otherwise re-testing an unchanged server authenticates
    with an empty string and reports a failure that is not real.
    """
    from deeptutor.services.mcp.manager import MCPConnectionManager

    return MCPConnectionManager._materialize(config, owner)


@router.get("/catalog")
async def get_catalog(
    q: str = "",
    category: str = "",
    tier: str = "",
    cursor: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    owner = current_owner_id()
    installed = load_user_mcp_config(owner)[0].servers
    # ``self_service_only`` on both calls: stdio entries are catalogued for the
    # deployment admin, and a category chip whose contents are all stdio would
    # open to an empty grid here.
    page = search_catalog(
        q=q,
        category=category,
        tier=tier,
        cursor=cursor,
        limit=limit,
        self_service_only=True,
    )
    return {
        "entries": [_catalog_row(entry, installed) for entry in page.entries],
        "next_cursor": page.next_cursor,
        "total": page.total,
        # Counted under the same q/tier the listing used, so a chip's number
        # cannot contradict what clicking it shows. ``category`` is excluded on
        # purpose — that is what the chips choose between.
        "categories": category_counts(q=q, tier=tier, self_service_only=True),
    }


@router.post("/catalog/{entry_id}/install")
async def install_catalog_entry(entry_id: str, payload: InstallPayload) -> dict[str, Any]:
    owner = current_owner_id()
    entry = get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=t("mcp.catalog_entry_missing", id=entry_id))
    if not entry.self_service:
        # stdio entries are catalogued for administrators; a user installing one
        # would be asking the host to run a command for them.
        raise HTTPException(
            status_code=403,
            detail={"code": "mcp.entry_admin_only", "message": t("mcp.entry_admin_only")},
        )
    name = payload.name or entry.id
    try:
        built = build_server_config(entry, payload.secrets)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "mcp.missing_credential", "message": str(exc)}
        ) from exc
    try:
        assert_name_available(name, shared_names=_shared_names())
        # Off the loop: the write validates the URL, which resolves DNS, and a
        # dead resolver would otherwise stall every request in the process.
        await asyncio.to_thread(save_user_server, owner, name, built.config)
    except UserMcpError as exc:
        raise _refuse(exc) from exc
    if built.secret_values:
        # Already rendered by the catalog (a header declared ``Bearer {value}``
        # is stored decorated, because the config side holds only a bare
        # reference).
        store_secrets(owner, name, built.secret_values)
    await get_mcp_manager().reload_scope(owner)
    return await list_servers()


def _catalog_row(entry: Any, installed: dict[str, MCPServerConfig]) -> dict[str, Any]:
    installed_as = _installed_names(entry.id, installed)
    return {
        "id": entry.id,
        "display_name": entry.display_name,
        "description_i18n": entry.description_i18n,
        "category": entry.category,
        "tier": entry.tier,
        "transport": entry.transport,
        "homepage": entry.homepage,
        "docs_url": entry.docs_url,
        "requires_i18n": entry.requires_i18n,
        "logo_url": entry.logo_url,
        "trust": entry.trust,
        "self_service": entry.self_service,
        "installed": bool(installed_as),
        # The local names this entry is installed under. The installer chooses
        # the name, so this is what a client needs to offer "test" or "remove"
        # for an entry it did not install under the default name.
        "installed_as": installed_as,
        "fields": [
            {
                "key": field.key,
                "label_i18n": field.label_i18n,
                "secret": field.secret,
                "required": field.required,
                "placeholder": field.placeholder,
            }
            for field in entry.fields
        ],
    }


def _installed_names(entry_id: str, installed: dict[str, MCPServerConfig]) -> list[str]:
    """Local names *entry_id* is installed under, by recorded provenance.

    A server installed before ``catalog_entry`` existed carries no provenance, so
    a name equal to the entry id counts too — that was the only name the store
    could have written it under.
    """
    return sorted(
        name
        for name, cfg in installed.items()
        if cfg.catalog_entry == entry_id or (not cfg.catalog_entry and name == entry_id)
    )


def _extract_credentials(
    owner: str, name: str, payload: ServerPayload
) -> tuple[MCPServerConfig, dict[str, str]]:
    """Move every credential out of the config, returning both halves.

    Deliberately **not** driven by what the client labelled as secret. A form
    that lets someone type ``Authorization: Bearer sk-live-…`` into a generic
    header row has no notion of which row is sensitive, so trusting the label
    would mean the plaintext lands on disk and comes straight back out of ``GET
    /servers`` — exactly what the rest of this surface promises it never does.

    So the rule is positional instead: on a self-configured server, a header or
    env value **is** the credential. Treating a harmless ``Accept`` header as
    sensitive costs only that its value is shown as "configured" rather than
    echoed; the other direction costs a leaked API key.

    Values already in reference form are left alone, so re-saving a server the
    user did not re-enter credentials for does not overwrite them with the
    placeholder they were shown.
    """
    from deeptutor.services.mcp.secrets import SECRET_REFERENCE_RE, secret_reference

    data = payload.config.model_dump(mode="json")
    secrets: dict[str, str] = dict(payload.secrets)

    for section in ("headers", "env"):
        values = data.get(section)
        if not isinstance(values, dict):
            continue
        for key, value in list(values.items()):
            if not isinstance(value, str) or not value:
                continue
            if SECRET_REFERENCE_RE.match(value):
                continue
            field = f"{section[:-1] if section == 'headers' else section}.{key}"
            secrets[field] = value
            values[key] = secret_reference(name, field)

    # A value the client *did* label keeps working: swap any remaining literal
    # occurrence of it (a url query parameter, an argument) for its reference.
    literals = {value: key for key, value in payload.secrets.items() if value}
    if literals:

        def _swap(value: Any) -> Any:
            if isinstance(value, str):
                key = literals.get(value)
                return secret_reference(name, key) if key else value
            if isinstance(value, dict):
                return {inner: _swap(item) for inner, item in value.items()}
            if isinstance(value, list):
                return [_swap(item) for item in value]
            return value

        data = _swap(data)

    return MCPServerConfig.model_validate(data), secrets


__all__ = ["router"]
