"""CLI apps: command-line tools an administrator installs and the chat agent calls.

Layering, innermost first — each layer imports only from the ones above it:

``models``    the shape of a catalog entry, and the install-command parser
``catalog``   the vendored snapshot, searchable
``paths``     where installs live on disk, and what the sandbox may see
``state``     which apps are installed (deployment) and enabled (per account)
``installer`` performing and removing an install — administrator only
``runner``    executing one installed app through the sandbox
``provider``  presenting installed apps as deferred tools to a chat turn

Only the four leaves are re-exported here. ``installer``, ``runner`` and
``provider`` are imported directly by their (few) callers: they pull in the
sandbox service and the tool registry, and re-exporting them would make
``import deeptutor.services.cli_apps`` drag both into every consumer — including
the API layer that only wants to list a catalog.
"""

from __future__ import annotations

from deeptutor.services.cli_apps.catalog import (
    CatalogPage,
    catalog_pin,
    categories,
    category_counts,
    get_entry,
    load_catalog,
    search_catalog,
)
from deeptutor.services.cli_apps.models import (
    AppRuntime,
    AppTrust,
    CliAppEntry,
    InstallKind,
    InstallPlan,
)

__all__ = [
    "AppRuntime",
    "AppTrust",
    "CatalogPage",
    "CliAppEntry",
    "InstallKind",
    "InstallPlan",
    "catalog_pin",
    "categories",
    "category_counts",
    "get_entry",
    "load_catalog",
    "search_catalog",
]
