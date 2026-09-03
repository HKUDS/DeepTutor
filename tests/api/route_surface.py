from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RegisteredRoute:
    path: str
    original_route: Any


def _with_prefix(prefix: str, path: str) -> str:
    if not prefix:
        return path
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def _iter_registered_routes(
    routes: Iterable[Any],
    inherited_prefix: str = "",
) -> Iterator[RegisteredRoute]:
    for route in routes:
        effective_contexts = getattr(route, "effective_route_contexts", None)
        if callable(effective_contexts):
            include_context = getattr(route, "include_context", None)
            prefix = getattr(include_context, "prefix", "") or inherited_prefix
            for context in effective_contexts():
                path = context.path or context.path_format
                if not path:
                    path = _with_prefix(
                        prefix,
                        context.original_route.path,
                    )
                yield RegisteredRoute(
                    path=path,
                    original_route=context.original_route,
                )
            continue

        nested = getattr(route, "routes", None)
        if nested is not None:
            prefix = _with_prefix(
                inherited_prefix,
                getattr(route, "path", ""),
            )
            yield from _iter_registered_routes(nested, prefix)
        else:
            yield RegisteredRoute(
                path=_with_prefix(
                    inherited_prefix,
                    route.path or getattr(route, "path_format", ""),
                ),
                original_route=route,
            )


def iter_registered_routes(routes: Iterable[Any]) -> Iterator[RegisteredRoute]:
    """Yield effective FastAPI leaf routes across router aggregation changes."""
    yield from _iter_registered_routes(routes)
