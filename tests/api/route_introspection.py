"""Helpers for inspecting FastAPI routes across nested include_router mounts.

Recent FastAPI/Starlette versions wrap ``include_router`` mounts as
``_IncludedRouter`` entries without a top-level ``.path``. Tests that assert on
the public URL surface must recurse into ``original_router.routes`` and apply
the include prefix.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Mount, Route, WebSocketRoute

_LEAF_ROUTE_TYPES = (APIRoute, APIWebSocketRoute, Route, WebSocketRoute)


def _join_path(prefix: str, path: str) -> str:
    if not prefix:
        return path
    if not path:
        return prefix or "/"
    if prefix.endswith("/") and path.startswith("/"):
        return prefix[:-1] + path
    if not prefix.endswith("/") and not path.startswith("/"):
        return prefix + "/" + path
    return prefix + path


def iter_app_routes(
    routes: Iterable[Any],
    *,
    prefix: str = "",
) -> Iterator[tuple[str, Any]]:
    """Yield ``(absolute_path, route)`` for leaf routes under ``routes``."""
    for route in routes:
        if isinstance(route, _LEAF_ROUTE_TYPES):
            yield _join_path(prefix, route.path), route
            continue

        if type(route).__name__ == "_IncludedRouter":
            include_context = getattr(route, "include_context", None)
            nested_prefix = _join_path(
                prefix,
                getattr(include_context, "prefix", None) or "",
            )
            original_router = getattr(route, "original_router", None)
            nested_routes = getattr(original_router, "routes", None)
            if nested_routes is not None:
                yield from iter_app_routes(nested_routes, prefix=nested_prefix)
            continue

        if isinstance(route, Mount):
            nested_routes = getattr(route, "routes", None)
            nested_prefix = _join_path(prefix, route.path)
            if nested_routes is not None:
                yield from iter_app_routes(nested_routes, prefix=nested_prefix)
            else:
                yield nested_prefix, route
            continue

        nested_routes = getattr(route, "routes", None)
        path = getattr(route, "path", None)
        if nested_routes is not None:
            yield from iter_app_routes(
                nested_routes,
                prefix=_join_path(prefix, path or ""),
            )
        elif path is not None:
            yield _join_path(prefix, path), route


def app_route_paths(app: Any) -> set[str]:
    return {path for path, _route in iter_app_routes(app.routes)}


def app_websocket_routes(app: Any) -> dict[str, Any]:
    return {
        path: route
        for path, route in iter_app_routes(app.routes)
        if isinstance(route, (APIWebSocketRoute, WebSocketRoute))
    }
