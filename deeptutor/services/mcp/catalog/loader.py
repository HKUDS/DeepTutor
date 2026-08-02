"""Load, search and paginate the vendored MCP catalog.

The catalog ships as a JSON file inside this package and is parsed once into
frozen dataclasses. **Nothing on the request path touches the network.** That is
a deliberate rejection of the pattern this feature replaces, where opening the
store did a blocking upstream registry fetch: a store page that waits on someone
else's uptime is a store page that goes down with it.

Search, filtering and pagination live here rather than in the router so the API
layer stays a thin translation of query parameters, and so the CLI and any
future surface get the same semantics for free.

A malformed entry is skipped with a warning. One bad hand-edit costing the whole
store — every user's install list included — is a far worse failure than one
service quietly missing from the grid.
"""

from __future__ import annotations

from functools import lru_cache
import json
import logging
from pathlib import Path
from typing import Any, NamedTuple

from deeptutor.services.mcp.catalog.models import (
    CATALOG_CATEGORIES,
    CATALOG_TIERS,
    CredentialField,
    McpCatalogEntry,
    normalize_transport,
)
from deeptutor.services.mcp.config import MCPServerConfig

logger = logging.getLogger(__name__)

CATALOG_FILENAME = "curated.json"
CATALOG_PATH = Path(__file__).parent / "vendor" / CATALOG_FILENAME

DEFAULT_PAGE_SIZE = 24
MAX_PAGE_SIZE = 100

#: Curated entries first; within a tier, alphabetical. The order has to be
#: deterministic because the cursor is an offset into it.
_TIER_RANK = {tier: index for index, tier in enumerate(CATALOG_TIERS)}


class CatalogPage(NamedTuple):
    entries: tuple[McpCatalogEntry, ...]
    #: Empty when the last page has been served.
    next_cursor: str
    #: Matches before pagination, so the UI can show "N services".
    total: int


@lru_cache(maxsize=1)
def load_catalog() -> tuple[McpCatalogEntry, ...]:
    """Every valid vendored entry, in stable display order."""
    try:
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Unreadable MCP catalog at %s: %s", CATALOG_PATH, exc)
        return ()

    rows = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        logger.error("MCP catalog at %s has no entries list", CATALOG_PATH)
        return ()

    entries: list[McpCatalogEntry] = []
    seen: set[str] = set()
    for row in rows:
        try:
            entry = _parse_entry(row)
        except Exception as exc:
            entry_id = row.get("id") if isinstance(row, dict) else "?"
            logger.warning("Skipping invalid MCP catalog entry %r: %s", entry_id, exc)
            continue
        if entry.id in seen:
            logger.warning("Skipping duplicate MCP catalog entry %r", entry.id)
            continue
        seen.add(entry.id)
        entries.append(entry)

    entries.sort(
        key=lambda item: (_TIER_RANK.get(item.tier, 99), item.display_name.casefold(), item.id)
    )
    return tuple(entries)


def reset_catalog_cache() -> None:
    """Drop the parsed catalog; for tests that swap the vendored file."""
    load_catalog.cache_clear()


def get_entry(entry_id: str) -> McpCatalogEntry | None:
    return next((entry for entry in load_catalog() if entry.id == entry_id), None)


def category_counts(
    *,
    q: str = "",
    tier: str = "",
    self_service_only: bool = False,
) -> dict[str, int]:
    """Match count per category under the *same* filters as the listing.

    Every filter except ``category`` itself has to apply, or a chip advertises a
    number the grid then contradicts: with a tier filter active a chip reading
    12 can open onto 2. ``self_service_only`` matters for the same reason — a
    category whose entries are all stdio (admin-only) is non-empty in the data
    and empty in the per-user grid.
    """
    needle = q.strip().casefold()
    counts = dict.fromkeys(CATALOG_CATEGORIES, 0)
    for entry in load_catalog():
        if self_service_only and not entry.self_service:
            continue
        if tier and entry.tier != tier:
            continue
        if needle and not _matches(entry, needle):
            continue
        counts[entry.category] += 1
    return counts


def search_catalog(
    *,
    q: str = "",
    category: str = "",
    tier: str = "",
    cursor: str = "",
    limit: int = DEFAULT_PAGE_SIZE,
    self_service_only: bool = False,
) -> CatalogPage:
    """Filter the catalog and return one page of it.

    *self_service_only* is what a per-user store passes: stdio entries exist in
    the data for the deployment admin and must never reach a student's grid.
    """
    needle = q.strip().casefold()
    matches = [
        entry
        for entry in load_catalog()
        if (not category or entry.category == category)
        and (not tier or entry.tier == tier)
        and (not self_service_only or entry.self_service)
        and (not needle or _matches(entry, needle))
    ]

    size = max(1, min(limit, MAX_PAGE_SIZE))
    start = _decode_cursor(cursor)
    page = matches[start : start + size]
    end = start + len(page)
    return CatalogPage(tuple(page), str(end) if end < len(matches) else "", len(matches))


def _matches(entry: McpCatalogEntry, needle: str) -> bool:
    haystack = " ".join(
        [
            entry.id,
            entry.display_name,
            entry.category,
            *entry.description_i18n.values(),
            *entry.requires_i18n.values(),
        ]
    )
    return needle in haystack.casefold()


def _decode_cursor(cursor: str) -> int:
    """An offset into the ordered match list.

    An offset is honest for a file that ships with the release: the list cannot
    shift between two requests of the same deployment. Junk decodes to the first
    page rather than erroring, because a stale cursor in a bookmarked URL should
    show the store, not a 400.
    """
    if not cursor:
        return 0
    try:
        return max(int(cursor), 0)
    except ValueError:
        logger.debug("Ignoring unparsable MCP catalog cursor %r", cursor)
        return 0


def _parse_entry(row: Any) -> McpCatalogEntry:
    if not isinstance(row, dict):
        raise TypeError("entry must be an object")
    transport = normalize_transport(str(row["transport"]))
    server = row.get("server")
    if not isinstance(server, dict):
        raise TypeError("entry needs a server template object")
    # The declared transport is the single source of truth: injecting it here
    # keeps the template from having to repeat itself, and from disagreeing.
    template = MCPServerConfig.model_validate({**server, "type": transport})
    return McpCatalogEntry(
        id=str(row["id"]),
        display_name=str(row["display_name"]),
        description_i18n=_i18n(row.get("description")),
        category=row["category"],
        tier=row.get("tier", "curated"),
        transport=transport,
        server_template=template,
        fields=tuple(_parse_field(item) for item in row.get("fields", ())),
        homepage=str(row.get("homepage", "")),
        docs_url=str(row.get("docs_url", "")),
        requires_i18n=_i18n(row.get("requires")),
        logo_url=str(row.get("logo_url", "")),
        trust=row.get("trust", "verified"),
        self_service=bool(row.get("self_service", transport != "stdio")),
    )


def _parse_field(row: Any) -> CredentialField:
    if not isinstance(row, dict):
        raise TypeError("credential field must be an object")
    target = row["target"]
    if not isinstance(target, (list, tuple)) or len(target) != 2:
        raise TypeError("credential target must be [kind, name]")
    return CredentialField(
        key=str(row["key"]),
        label_i18n=_i18n(row.get("label")),
        target=(target[0], str(target[1])),
        secret=bool(row.get("secret", True)),
        required=bool(row.get("required", True)),
        placeholder=str(row.get("placeholder", "")),
        value_template=str(row.get("value_template", "{value}")),
    )


def _i18n(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(lang): str(text) for lang, text in value.items() if str(text).strip()}


__all__ = [
    "CATALOG_PATH",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "CatalogPage",
    "category_counts",
    "get_entry",
    "load_catalog",
    "reset_catalog_cache",
    "search_catalog",
]
