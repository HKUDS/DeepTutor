"""A user's own MCP servers.

The deployment's servers live in one admin-owned ``mcp.json``
(:mod:`deeptutor.services.mcp.config`). This module is the parallel store for
servers an individual configures for themselves, and it differs in three ways
that are all load-bearing:

**Location.** ``data/system/user-mcp/<owner>.json`` — inside the one branch of
the data tree the exec sandbox never mounts. A per-user config kept under
``data/users/`` would be writable from every other account's sandboxed shell,
and since this file *names* the credentials to inject, an attacker who can write
it can have the server resolve the victim's key and send it anywhere. Keeping
the file out of the sandbox is what makes the reference-based secret handling in
:mod:`deeptutor.services.mcp.secrets` mean anything.

**Remote transports only.** A ``stdio`` server is a command executed on the host
as the application user; no permission flag makes that safe to hand a student on
a shared deployment. Entries that ask for it are rejected on read and reported,
so a config edited by hand cannot smuggle one in either.

**Bounded.** A per-owner server cap and a scope cap in the connection manager,
because 500 accounts × N servers is one process's worth of live sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import stat

from deeptutor.services.mcp.config import MCPConfig, MCPServerConfig
from deeptutor.services.mcp.network import validate_mcp_url

logger = logging.getLogger(__name__)

USER_MCP_DIRNAME = "user-mcp"

#: Per-owner ceiling. Deliberately low: these are hosted services a person
#: actually uses, and every one of them is a live session in the app process.
MAX_SERVERS_PER_OWNER = 8

#: Tool names are namespaced ``mcp_<server>_<tool>`` / ``cli_<app>``, so a
#: server named after a namespace prefix could forge another provider's tool
#: name in the model's view.
_RESERVED_NAME_PREFIXES = ("mcp_", "cli_")

_SERVER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class UserMcpError(ValueError):
    """A user-supplied server definition that must be refused with a reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RejectedServer:
    """A stored entry that will not be connected, and why."""

    name: str
    reason: str


def user_mcp_path(owner_id: str) -> Path:
    from deeptutor.multi_user.paths import SYSTEM_ROOT

    root = SYSTEM_ROOT / USER_MCP_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, stat.S_IRWXU)
    safe = owner_id if _SERVER_NAME_RE.match(owner_id) else "_invalid"
    return root / f"{safe}.json"


def load_user_mcp_config(owner_id: str) -> tuple[MCPConfig, list[RejectedServer]]:
    """Read *owner_id*'s servers, dropping any that must not be connected.

    Returns the connectable config plus one :class:`RejectedServer` per entry
    that was dropped, so the UI can explain the omission instead of silently
    showing fewer servers than the file contains.
    """
    path = user_mcp_path(owner_id)
    if not path.exists():
        return MCPConfig(), []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable per-user MCP config %s; treating as empty", path)
        return MCPConfig(), []
    try:
        stored = MCPConfig.model_validate(raw)
    except Exception:
        logger.warning("Invalid per-user MCP config %s; treating as empty", path)
        return MCPConfig(), []

    servers: dict[str, MCPServerConfig] = {}
    rejected: list[RejectedServer] = []
    for name, cfg in stored.servers.items():
        try:
            _assert_self_service_allowed(name, cfg)
        except UserMcpError as exc:
            rejected.append(RejectedServer(name=name, reason=str(exc)))
            continue
        if len(servers) >= MAX_SERVERS_PER_OWNER:
            rejected.append(
                RejectedServer(
                    name=name,
                    reason=f"Over the limit of {MAX_SERVERS_PER_OWNER} servers per account",
                )
            )
            continue
        servers[name] = cfg
    return MCPConfig(servers=servers), rejected


def save_user_server(owner_id: str, name: str, cfg: MCPServerConfig) -> MCPConfig:
    """Upsert one server. Read-modify-write, so a save cannot drop the others.

    Whole-map writes are how a second concurrent edit loses the first, and how
    fields the editor does not model (a hand-written tool blocklist) get wiped.
    """
    _assert_self_service_allowed(name, cfg, validate_url=True)
    stored = _read_raw(owner_id)
    if name not in stored.servers and len(stored.servers) >= MAX_SERVERS_PER_OWNER:
        raise UserMcpError(
            "mcp.too_many_servers",
            f"At most {MAX_SERVERS_PER_OWNER} MCP servers per account",
        )
    servers = dict(stored.servers)
    servers[name] = cfg
    updated = MCPConfig(servers=servers)
    _write_raw(owner_id, updated)
    return updated


def delete_user_server(owner_id: str, name: str) -> MCPConfig:
    stored = _read_raw(owner_id)
    servers = {key: value for key, value in stored.servers.items() if key != name}
    updated = MCPConfig(servers=servers)
    _write_raw(owner_id, updated)
    return updated


def assert_name_available(name: str, *, shared_names: set[str]) -> None:
    """Refuse a name that collides with a deployment server, rather than resolving it.

    Two tenants must never resolve one tool name. The process registry is a
    last-writer-wins dict, so silently renaming or shadowing would mean one
    account's call reaching another's server — a refusal at write time is the
    only outcome that stays comprehensible.
    """
    if name in shared_names:
        raise UserMcpError(
            "mcp.name_reserved",
            f"{name!r} is already the name of a deployment server",
        )


def _assert_self_service_allowed(
    name: str,
    cfg: MCPServerConfig,
    *,
    validate_url: bool = False,
) -> None:
    if not _SERVER_NAME_RE.match(name):
        raise UserMcpError("mcp.invalid_name", f"Invalid server name {name!r}")
    if name.startswith(_RESERVED_NAME_PREFIXES):
        raise UserMcpError(
            "mcp.name_reserved",
            f"{name!r} starts with a reserved tool-name prefix",
        )
    transport = cfg.resolved_type()
    if transport == "stdio" or cfg.command:
        raise UserMcpError(
            "mcp.stdio_not_allowed",
            "A server you configure yourself must be a remote URL: a stdio "
            "server runs a command on the host and stays administrator-only.",
        )
    if transport not in ("sse", "streamableHttp"):
        raise UserMcpError("mcp.no_transport", "Provide an http(s) URL for the server")
    if validate_url:
        ok, error = validate_mcp_url(cfg.url, strict=True)
        if not ok:
            raise UserMcpError("mcp.blocked_url", error)


def _read_raw(owner_id: str) -> MCPConfig:
    """The file as stored, *without* the connectability filtering.

    Writes must preserve entries this deployment refuses to connect (a stdio
    entry left over from a hand edit), or saving one server would silently
    delete another.
    """
    path = user_mcp_path(owner_id)
    if not path.exists():
        return MCPConfig()
    try:
        return MCPConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return MCPConfig()


def _write_raw(owner_id: str, config: MCPConfig) -> None:
    path = user_mcp_path(owner_id)
    payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


__all__ = [
    "MAX_SERVERS_PER_OWNER",
    "USER_MCP_DIRNAME",
    "RejectedServer",
    "UserMcpError",
    "assert_name_available",
    "delete_user_server",
    "load_user_mcp_config",
    "save_user_server",
    "user_mcp_path",
]
