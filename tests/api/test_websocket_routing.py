"""WebSocket routes must not inherit HTTP-only application dependencies."""

from fastapi.routing import APIWebSocketRoute

from deeptutor.api.main import app
from deeptutor.api.routers.auth import require_learning_surface
from tests.api.route_surface import iter_registered_routes


def test_websocket_routes_share_one_canonical_namespace() -> None:
    expected_paths = {
        "/ws",
        "/ws/books",
        "/ws/questions/mimic",
        "/ws/questions/generate",
        "/ws/questions/judge",
        "/ws/knowledge-bases/{kb_name}/progress",
        "/ws/mastery-paths",
        "/ws/partners/{partner_id}",
        "/ws/partner-groups/{group_id}",
    }
    websocket_routes = {
        route.path: route
        for route in iter_registered_routes(app.routes)
        if isinstance(route.original_route, APIWebSocketRoute)
    }

    assert set(websocket_routes) == expected_paths
    for route in websocket_routes.values():
        assert all(
            dependency.call is not require_learning_surface
            for dependency in route.original_route.dependant.dependencies
        )
