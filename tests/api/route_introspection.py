"""Compatibility helpers for assertions over FastAPI's registered routes."""

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.routing import APIWebSocketRoute


def iter_effective_route_paths(app: FastAPI) -> Iterator[str]:
    """Yield registered paths across flat and nested FastAPI releases."""
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            yield path
            continue

        effective_contexts = getattr(route, "effective_route_contexts", None)
        if not callable(effective_contexts):
            continue
        for context in effective_contexts():
            compiled_route = getattr(context, "starlette_route", None)
            effective_path = getattr(compiled_route, "path", None) or getattr(context, "path", None)
            if isinstance(effective_path, str):
                yield effective_path


def iter_effective_websocket_routes(app: FastAPI) -> Iterator[APIWebSocketRoute]:
    """Yield compiled WebSocket routes across flat and nested FastAPI releases.

    FastAPI 0.141 stopped flattening included routers into ``app.routes``.
    Included-router entries expose their compiled routes through
    ``effective_route_contexts()``; older releases expose the routes directly.
    """
    for route in app.routes:
        if isinstance(route, APIWebSocketRoute):
            yield route
            continue

        effective_contexts = getattr(route, "effective_route_contexts", None)
        if not callable(effective_contexts):
            continue
        for context in effective_contexts():
            compiled_route = getattr(context, "starlette_route", None)
            if isinstance(compiled_route, APIWebSocketRoute):
                yield compiled_route
