"""Assemble installed modules without changing their authentication policies."""

from fastapi import Depends, FastAPI

from deeptutor.api.router_loader import RouterLoader
from deeptutor.modules.catalog import manifests, module_enabled


def mount_module_routes(app: FastAPI, loader: RouterLoader) -> None:
    from deeptutor.api.routers.auth import require_admin, require_auth, require_learning_surface

    policies = {
        "public": [],
        "authenticated": [Depends(require_auth)],
        "learning": [Depends(require_learning_surface)],
        "admin": [Depends(require_admin)],
    }
    routes = [
        route
        for name, module in manifests().items()
        if module_enabled(name)
        for route in module["routes"]
    ]
    unavailable = tuple(
        prefix
        for name, row in manifests().items()
        if not module_enabled(name)
        for prefix in row.get("http_paths", [])
    )
    for route in sorted(routes, key=lambda row: row["order"]):
        loader.include(
            route["reference"],
            **route["options"],
            exclude_paths=unavailable,
            dependencies=policies[route["auth"]],
        )
    loader.include(
        "deeptutor.api.routers.modules:router",
        prefix="/api/modules",
        tags=["modules"],
        dependencies=[Depends(require_auth)],
    )
