"""Read the vendored CLI app catalog, and search it.

The snapshot ships in the package (``vendor/catalog.json``) rather than being
fetched: a store that reaches out to a third-party registry at request time turns
every page render into a dependency on somebody else's uptime, and makes "what
can this deployment install?" unanswerable offline.

Parsed once per process. A malformed row is dropped with a warning rather than
taking the whole catalog down — a snapshot re-sync should never be able to make
the store unreachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.services.cli_apps.models import (
    AppOrigin,
    CliAppEntry,
    InstallKind,
    plan_install,
)

logger = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).parent / "vendor" / "catalog.json"

#: Cursor pagination page size ceiling, so one request cannot ask for everything.
MAX_PAGE_SIZE = 60


@dataclass(frozen=True, slots=True)
class CatalogPage:
    entries: tuple[CliAppEntry, ...]
    #: Empty once the last page has been served.
    next_cursor: str
    #: Matches before pagination.
    total: int


@lru_cache(maxsize=1)
def load_catalog() -> tuple[CliAppEntry, ...]:
    """Every app in the snapshot, id-sorted."""
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("CLI app catalog is unreadable at %s", CATALOG_PATH)
        return ()

    pin = str((payload.get("meta") or {}).get("commit") or "")
    if not pin:
        logger.error("CLI app catalog has no pinned commit; refusing to offer installs")
        return ()

    entries: list[CliAppEntry] = []
    for row in payload.get("apps") or []:
        entry = _parse(row, harness_pin=pin)
        if entry is not None:
            entries.append(entry)
    return tuple(sorted(entries, key=lambda item: item.id))


@lru_cache(maxsize=1)
def catalog_pin() -> str:
    """The CLI-Anything commit first-party harness installs are pinned to."""
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str((payload.get("meta") or {}).get("commit") or "")


def get_entry(app_id: str) -> CliAppEntry | None:
    return _by_id().get(app_id)


def categories() -> tuple[str, ...]:
    """Categories present in the snapshot, in display order."""
    return tuple(sorted({entry.category for entry in load_catalog() if entry.category}))


def category_counts(*, q: str = "", installable_only: bool = False) -> dict[str, int]:
    """Category → match count under the *same* filters a listing would apply.

    Counted under the caller's query so a chip's number cannot contradict what
    clicking it shows. ``category`` is excluded on purpose — that is what the
    chips choose between.
    """
    counts: dict[str, int] = {}
    for entry in _match(q=q, category="", installable_only=installable_only):
        if entry.category:
            counts[entry.category] = counts.get(entry.category, 0) + 1
    return dict(sorted(counts.items()))


def search_catalog(
    *,
    q: str = "",
    category: str = "",
    installable_only: bool = False,
    cursor: str = "",
    limit: int = 24,
) -> CatalogPage:
    """One page of matches. ``cursor`` is an opaque offset produced by this call."""
    matches = _match(q=q, category=category, installable_only=installable_only)
    size = max(1, min(int(limit or 24), MAX_PAGE_SIZE))
    start = _offset(cursor)
    window = matches[start : start + size]
    end = start + len(window)
    return CatalogPage(
        entries=tuple(window),
        next_cursor=str(end) if end < len(matches) else "",
        total=len(matches),
    )


def _match(*, q: str, category: str, installable_only: bool) -> list[CliAppEntry]:
    needle = q.strip().lower()
    out: list[CliAppEntry] = []
    for entry in load_catalog():
        if category and entry.category != category:
            continue
        if installable_only and not entry.install.installable:
            continue
        if needle and needle not in _haystack(entry):
            continue
        out.append(entry)
    return out


def _haystack(entry: CliAppEntry) -> str:
    return " ".join((entry.id, entry.display_name, entry.description, entry.category)).lower()


def _offset(cursor: str) -> int:
    """Decode a cursor, treating anything unparseable as the first page."""
    try:
        value = int(cursor)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


@lru_cache(maxsize=1)
def _by_id() -> dict[str, CliAppEntry]:
    return {entry.id: entry for entry in load_catalog()}


def _parse(row: Any, *, harness_pin: str) -> CliAppEntry | None:
    if not isinstance(row, dict):
        return None
    app_id = str(row.get("name") or "").strip()
    try:
        origin: AppOrigin = "public" if row.get("origin") == "public" else "harness"
        plan = plan_install(
            app_id=app_id,
            install_cmd=str(row.get("install_cmd") or ""),
            package_manager=str(row.get("package_manager") or ""),
            harness_pin=harness_pin,
        )
        return CliAppEntry(
            id=app_id,
            display_name=str(row.get("display_name") or app_id),
            description=str(row.get("description") or ""),
            category=str(row.get("category") or "other"),
            origin=origin,
            entry_point=str(row.get("entry_point") or ""),
            install=plan,
            version=str(row.get("version") or ""),
            requires=str(row.get("requires") or ""),
            homepage=str(row.get("homepage") or ""),
            source_url=str(row.get("source_url") or ""),
            doc_ref=str(row.get("skill_md") or ""),
            install_notes=str(row.get("install_notes") or ""),
        )
    except ValueError as exc:
        # A row we cannot model is dropped, not fatal: one bad entry in a
        # re-synced snapshot must not take the whole store offline.
        logger.warning("dropping CLI app catalog row %r: %s", app_id, exc)
        return None


def installable_kinds() -> tuple[InstallKind, ...]:
    """The install kinds this build knows how to perform."""
    return (
        InstallKind.PINNED_HARNESS,
        InstallKind.PIP_GIT,
        InstallKind.PIP,
        InstallKind.NPM,
    )


__all__ = [
    "CATALOG_PATH",
    "MAX_PAGE_SIZE",
    "CatalogPage",
    "catalog_pin",
    "categories",
    "category_counts",
    "get_entry",
    "installable_kinds",
    "load_catalog",
    "search_catalog",
]
