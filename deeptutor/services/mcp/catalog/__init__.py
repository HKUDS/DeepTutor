"""The curated MCP catalog: one-click installable MCP services.

:mod:`models` is the entry shape and the template-to-config projection;
:mod:`loader` reads the JSON that ships in ``vendor/`` and serves search,
filtering and pagination over it. Everything is pure and offline — a caller
turns an entry plus credential values into an ``MCPServerConfig`` and never
learns where the catalog came from.
"""

from deeptutor.services.mcp.catalog.loader import (
    CatalogPage,
    category_counts,
    get_entry,
    load_catalog,
    reset_catalog_cache,
    search_catalog,
)
from deeptutor.services.mcp.catalog.models import (
    CATALOG_CATEGORIES,
    CATALOG_TIERS,
    BuiltServer,
    CredentialField,
    McpCatalogEntry,
    build_server_config,
    localized_text,
    normalize_transport,
)

__all__ = [
    "CATALOG_CATEGORIES",
    "CATALOG_TIERS",
    "BuiltServer",
    "CatalogPage",
    "CredentialField",
    "McpCatalogEntry",
    "build_server_config",
    "category_counts",
    "get_entry",
    "load_catalog",
    "localized_text",
    "normalize_transport",
    "reset_catalog_cache",
    "search_catalog",
]
