"""Curated MCP catalog: the shape of one installable entry.

The catalog is a *template* store, not a second config store. An entry knows the
connection an MCP service needs and, separately, which credentials the person
installing it has to supply and **where each one has to travel** — an env var for
one service, a request header for another, a URL query parameter for a third, a
command argument for a fourth. :func:`build_server_config` folds an entry plus
the supplied values into an
:class:`~deeptutor.services.mcp.config.MCPServerConfig`, the only server shape
the rest of DeepTutor understands.

Three invariants keep the data honest, all enforced in ``__post_init__`` so a
hand-edited catalog file cannot slip past them:

**A secret value never enters the produced config.** The config carries the
``${secret:<entry>/<field>}`` reference that
:mod:`deeptutor.services.mcp.secrets` resolves in memory at connect time. That
resolver matches a reference only as an *entire* value, which is why a field
whose target expects decoration (``Authorization: Bearer <token>``) declares a
:attr:`CredentialField.value_template` that is applied when the value is
**stored** (:meth:`CredentialField.render`), not when the config is written.

**A stdio entry is never self-service.** ``command`` is arbitrary execution on
the host as the application user, so per-user installs of stdio servers stay
permanently admin-only.

**A field's target has to fit the transport.** An ``env`` var on a remote server
would be silently dropped, and a ``header`` on a stdio one has nowhere to go.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal, NamedTuple, get_args
import urllib.parse

from deeptutor.services.mcp.config import MCPServerConfig
from deeptutor.services.mcp.secrets import secret_reference

Transport = Literal["stdio", "sse", "streamableHttp"]
CredentialTarget = Literal["env", "header", "url_param", "arg"]
CatalogTier = Literal["curated", "registry"]
CatalogTrust = Literal["verified", "unverified"]

#: Closed set, because the store's category filter is a fixed row of chips: a
#: free-form string here would let one entry invent a bucket nothing else lands
#: in, and the UI would show an empty tab.
CatalogCategory = Literal[
    "search",
    "docs",
    "code",
    "data",
    "browser",
    "science",
    "maps",
    "business",
    "ai",
    "utility",
]

CATALOG_CATEGORIES: tuple[str, ...] = get_args(CatalogCategory)
CATALOG_TIERS: tuple[str, ...] = get_args(CatalogTier)
CREDENTIAL_TARGETS: tuple[str, ...] = get_args(CredentialTarget)
TRANSPORTS: tuple[str, ...] = get_args(Transport)

#: An entry id is used verbatim as the installed server's name and as the
#: secrets-file name, so it is the intersection of what both accept, lowercased.
ENTRY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: One transport, four spellings in the wild: ours (``streamableHttp``), the
#: official registry's (``streamable-http``), the snake_case some clients emit,
#: and the bare ``http`` of the shared MCP config format. Every consumer goes
#: through :func:`normalize_transport` instead of comparing raw strings.
_TRANSPORT_ALIASES: dict[str, Transport] = {
    "stdio": "stdio",
    "sse": "sse",
    "streamablehttp": "streamableHttp",
    "streamable-http": "streamableHttp",
    "streamable_http": "streamableHttp",
    "http": "streamableHttp",
}

_REMOTE_TARGETS = frozenset({"header", "url_param"})
_STDIO_TARGETS = frozenset({"env", "arg"})


def normalize_transport(value: str) -> Transport:
    """Canonicalise a transport spelling; raise on anything unknown."""
    normalized = _TRANSPORT_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError(f"Unsupported MCP transport: {value!r}")
    return normalized


def localized_text(texts: dict[str, str], lang: str = "en") -> str:
    """Pick *lang* from an i18n map, degrading to base language then English."""
    for key in (lang, lang.split("-")[0], "en"):
        text = texts.get(key)
        if text:
            return text
    return next((text for text in texts.values() if text), "")


@dataclass(frozen=True, slots=True)
class CredentialField:
    """One value the installer must supply, and where it has to end up."""

    key: str
    label_i18n: dict[str, str]
    #: ``(kind, name)`` — the env var / header / query parameter / CLI flag.
    target: tuple[CredentialTarget, str]
    secret: bool = True
    required: bool = True
    placeholder: str = ""
    #: Applied on the way into the secret store, never into the config: the
    #: connect-time resolver matches ``${secret:...}`` only as a whole value, so
    #: a config holding ``"Bearer ${secret:...}"`` would ship that text
    #: verbatim to the server. Fields whose target needs a prefix put it here.
    value_template: str = "{value}"

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("Credential field key must not be empty")
        kind, name = self.target
        if kind not in CREDENTIAL_TARGETS:
            raise ValueError(f"Unknown credential target {kind!r} for field {self.key!r}")
        if not name.strip():
            raise ValueError(f"Credential target for field {self.key!r} needs a name")
        if "{value}" not in self.value_template:
            raise ValueError(f"value_template for field {self.key!r} must contain {{value}}")

    def render(self, raw: str) -> str:
        """The exact string the target expects for the supplied *raw* value."""
        return self.value_template.format(value=raw)

    def label(self, lang: str = "en") -> str:
        return localized_text(self.label_i18n, lang) or self.key


@dataclass(frozen=True, slots=True)
class McpCatalogEntry:
    """One installable service in the store."""

    id: str
    display_name: str
    description_i18n: dict[str, str]
    category: CatalogCategory
    tier: CatalogTier
    transport: Transport
    server_template: MCPServerConfig
    fields: tuple[CredentialField, ...] = ()
    homepage: str = ""
    docs_url: str = ""
    requires_i18n: dict[str, str] = field(default_factory=dict)
    #: Relative path the app serves itself, or empty for an initials avatar.
    #: Never a third-party CDN: the browser fetching one logo per installed
    #: service would hand that vendor every user's app list on every render.
    logo_url: str = ""
    trust: CatalogTrust = "verified"
    self_service: bool = True

    def __post_init__(self) -> None:
        if ENTRY_ID_RE.match(self.id) is None:
            raise ValueError(
                f"Invalid catalog entry id {self.id!r}: must match {ENTRY_ID_RE.pattern}"
            )
        if not self.display_name.strip():
            raise ValueError(f"Catalog entry {self.id!r} needs a display name")
        if not self.description_i18n.get("en", "").strip():
            raise ValueError(f"Catalog entry {self.id!r} needs an English description")
        if self.category not in CATALOG_CATEGORIES:
            raise ValueError(f"Catalog entry {self.id!r} has unknown category {self.category!r}")
        if self.tier not in CATALOG_TIERS:
            raise ValueError(f"Catalog entry {self.id!r} has unknown tier {self.tier!r}")
        if self.transport not in TRANSPORTS:
            raise ValueError(f"Catalog entry {self.id!r} has unknown transport {self.transport!r}")

        resolved = self.server_template.resolved_type()
        if resolved != self.transport:
            raise ValueError(
                f"Catalog entry {self.id!r} declares transport {self.transport!r} but its "
                f"server template resolves to {resolved!r}"
            )
        # The check above cannot fire for a JSON entry — the loader stamps
        # ``type`` from ``transport``, so ``resolved_type()`` echoes it back. The
        # shape is what actually distinguishes the two, and getting it wrong is
        # how a "remote" entry ends up carrying a command.
        if self.transport == "stdio":
            if not self.server_template.command or self.server_template.url:
                raise ValueError(
                    f"Catalog entry {self.id!r} is stdio and needs a command and no url"
                )
        elif not self.server_template.url or self.server_template.command:
            raise ValueError(f"Catalog entry {self.id!r} is remote and needs a url and no command")
        if self.transport == "stdio" and self.self_service:
            raise ValueError(
                f"Catalog entry {self.id!r} is stdio and cannot be self-service: a command is "
                "arbitrary host execution as the application user"
            )

        allowed = _STDIO_TARGETS if self.transport == "stdio" else _REMOTE_TARGETS
        keys: set[str] = set()
        for spec in self.fields:
            if spec.target[0] not in allowed:
                raise ValueError(
                    f"Catalog entry {self.id!r} ({self.transport}) cannot carry a "
                    f"{spec.target[0]!r} credential for field {spec.key!r}"
                )
            if spec.key in keys:
                raise ValueError(f"Catalog entry {self.id!r} repeats credential field {spec.key!r}")
            keys.add(spec.key)

    def description(self, lang: str = "en") -> str:
        return localized_text(self.description_i18n, lang)

    def requires(self, lang: str = "en") -> str:
        return localized_text(self.requires_i18n, lang)

    def secret_field_keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.fields if spec.secret)


class BuiltServer(NamedTuple):
    """A ready-to-persist config plus the credential values to store beside it.

    ``secret_values`` is what belongs in the owner's secrets tree, already
    decorated by each field's ``value_template`` — returning bare keys instead
    would leave the obvious call site (``store_secrets(..., user_input)``)
    storing an undecorated token, so a header declared as ``Bearer {value}``
    would reach the vendor without the scheme.
    """

    config: MCPServerConfig
    secret_values: dict[str, str]


def build_server_config(entry: McpCatalogEntry, values: dict[str, str]) -> BuiltServer:
    """Materialise *entry* into a server config, injecting *values* at their targets.

    Secret values are deliberately *not* injected into the config: each is
    replaced by its ``${secret:...}`` reference and handed back separately, so
    the config that gets persisted, displayed and diffed stays free of plaintext
    credentials.
    """
    cfg = MCPServerConfig.model_validate(entry.server_template.model_dump(mode="json"))
    # Provenance, so "already installed?" survives the installer renaming it.
    cfg.catalog_entry = entry.id
    to_store: dict[str, str] = {}
    for spec in entry.fields:
        raw = (values.get(spec.key) or "").strip()
        if not raw:
            if spec.required:
                raise ValueError(f"Missing required credential {spec.key!r} for {entry.id!r}")
            continue
        if spec.secret:
            injected = secret_reference(entry.id, spec.key)
            # Rendered here, not at the injection site: the config holds a bare
            # reference (the only form the resolver matches), so the decoration
            # has to live with the stored value.
            to_store[spec.key] = spec.render(raw)
        else:
            injected = spec.render(raw)

        kind, name = spec.target
        if kind == "env":
            cfg.env[name] = injected
        elif kind == "header":
            cfg.headers[name] = injected
        elif kind == "arg":
            cfg.args = _with_arg(list(cfg.args), name, injected)
        else:
            cfg.url = _with_url_param(cfg.url, name, injected)
    return BuiltServer(cfg, to_store)


def _with_arg(args: list[str], flag: str, value: str) -> list[str]:
    """Set ``flag value`` in *args*, dropping any prior spelling of the flag."""
    prefix = f"{flag}="
    out: list[str] = []
    skip_next = False
    for item in args:
        if skip_next:
            skip_next = False
            continue
        if item == flag:
            skip_next = True
            continue
        if item.startswith(prefix):
            continue
        out.append(item)
    out.extend([flag, value])
    return out


def _with_url_param(url: str, key: str, value: str) -> str:
    """Set *key* in *url*'s query, keeping a ``${secret:...}`` reference legible.

    Percent-encoding the reference would hide it from the connect-time resolver,
    which recognises only the literal form.
    """
    parsed = urllib.parse.urlsplit(url)
    query = [
        (name, item)
        for name, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if name != key
    ]
    query.append((key, value))
    encoded = urllib.parse.urlencode(query, safe="${}:/", quote_via=urllib.parse.quote)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, encoded, parsed.fragment)
    )


__all__ = [
    "CATALOG_CATEGORIES",
    "CATALOG_TIERS",
    "CREDENTIAL_TARGETS",
    "ENTRY_ID_RE",
    "TRANSPORTS",
    "BuiltServer",
    "CatalogCategory",
    "CatalogTier",
    "CatalogTrust",
    "CredentialField",
    "CredentialTarget",
    "McpCatalogEntry",
    "Transport",
    "build_server_config",
    "localized_text",
    "normalize_transport",
]
