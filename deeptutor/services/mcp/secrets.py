"""Credentials for a user's own MCP servers.

A remote MCP server is reached with an API key that belongs to the person who
configured it, and that key has to travel somewhere specific — an env var for
one service, a request header for another, a URL query parameter or a command
argument for a third. Two consequences shape this module:

* **The value never enters the server config.** The config records a reference
  (``${secret:<server>/<field>}``) and this module resolves it in memory at
  connect time. A config file is the wrong place for a token: it is read for
  display, returned by APIs, copied into logs and diffs, and — for a stdio
  server — would land in the process's own argv, visible in ``ps``.
* **Values live only under the owner's ``data/system`` secrets directory**, the
  one branch of the data tree the exec sandbox never mounts. Anything a user's
  sandboxed shell can read is, in a multi-account deployment, readable by every
  other account.

Reads and writes are addressed by *owner id*, not by the current request scope,
because a connection task resolves its credentials long after the turn that
opened it.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import stat
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

#: ``${secret:<server>/<field>}`` — the only form a config may carry.
SECRET_REFERENCE_RE = re.compile(r"^\$\{secret:(?P<server>[^/}]+)/(?P<field>[^}]+)\}$")

_SECRETS_SUBDIR = ("private", "mcp")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def secret_reference(server: str, field: str) -> str:
    """The reference a config stores in place of a credential value."""
    return f"${{secret:{server}/{field}}}"


def _secrets_dir(owner_id: str) -> Path:
    from deeptutor.multi_user.paths import owner_secrets_dir

    path = owner_secrets_dir(owner_id)
    for part in _SECRETS_SUBDIR:
        path = path / part
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)
    return path


def _secrets_file(owner_id: str, server: str) -> Path:
    # One file per server so removing a server removes its credentials with it,
    # rather than leaving orphans in a shared blob.
    if not _SAFE_NAME_RE.match(server):
        raise ValueError(f"Unsafe MCP server name for a secrets file: {server!r}")
    return _secrets_dir(owner_id) / f"{server}.json"


def store_secrets(owner_id: str, server: str, values: dict[str, str]) -> None:
    """Merge *values* into this server's stored credentials.

    Merged rather than replaced so a partial edit (rotating one key of three)
    does not silently clear the others. An empty string deletes a field, which
    is how the UI expresses "remove this credential".
    """
    path = _secrets_file(owner_id, server)
    current = _read_all(path)
    for key, value in values.items():
        if value == "":
            current.pop(key, None)
        else:
            current[key] = str(value)
    if not current:
        path.unlink(missing_ok=True)
        return
    _write_all(path, current)


def configured_fields(owner_id: str, server: str) -> set[str]:
    """Field names that have a stored value. Never returns the values."""
    return set(_read_all(_secrets_file(owner_id, server)))


def delete_secrets(owner_id: str, server: str) -> None:
    _secrets_file(owner_id, server).unlink(missing_ok=True)


def resolve_references(owner_id: str, payload: Any) -> Any:
    """Return *payload* with every secret reference replaced by its value.

    Walks nested dicts/lists so it covers ``env``, ``headers`` and ``args``,
    where a credential *is* the whole value. A reference embedded in a longer
    string is deliberately left alone — a partial match has no defensible
    boundary — so the URL case has its own entry point,
    :func:`resolve_url_references`.

    A reference with no stored value resolves to an empty string: the server then
    fails its own authentication with a clear message, which is a better failure
    than sending the literal ``${secret:...}`` upstream.
    """
    if isinstance(payload, str):
        match = SECRET_REFERENCE_RE.match(payload)
        if match is None:
            return payload
        stored = _read_all(_secrets_file(owner_id, match.group("server")))
        value = stored.get(match.group("field"))
        if value is None:
            logger.warning(
                "MCP secret %s/%s is referenced but not stored for owner %s",
                match.group("server"),
                match.group("field"),
                owner_id,
            )
            return ""
        return value
    if isinstance(payload, dict):
        return {key: resolve_references(owner_id, item) for key, item in payload.items()}
    if isinstance(payload, list):
        return [resolve_references(owner_id, item) for item in payload]
    return payload


def resolve_url_references(owner_id: str, url: str) -> str:
    """Resolve secret references that sit in a URL's query values.

    Several hosted MCP services authenticate with a query parameter rather than a
    header, so the stored URL looks like
    ``https://host/mcp?apiKey=${secret:svc/api_key}``. That whole string is not a
    reference, and :func:`resolve_references` deliberately refuses to substitute
    *inside* arbitrary text — a rule worth keeping, because a partial match has no
    obvious boundary and would make "is this value a credential?" unanswerable.

    A URL is not arbitrary text, though: split it and each query value *is* a
    bare reference, so it resolves under the same whole-value rule. Values are
    re-encoded on the way out, which is also what turns a real token into a
    correctly escaped query parameter.
    """
    if "${secret:" not in url:
        return url
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    resolved = [(key, resolve_references(owner_id, value)) for key, value in pairs]
    if resolved == pairs:
        return url
    return urlunsplit(parts._replace(query=urlencode(resolved)))


def _read_all(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable MCP secrets file %s; treating as empty", path)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def _write_all(path: Path, values: dict[str, str]) -> None:
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(values, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


__all__ = [
    "SECRET_REFERENCE_RE",
    "configured_fields",
    "delete_secrets",
    "resolve_references",
    "resolve_url_references",
    "secret_reference",
    "store_secrets",
]
