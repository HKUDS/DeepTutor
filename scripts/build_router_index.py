"""Regenerate the lazy API routing index after changing router declarations.

Run with the project's Python environment: python scripts/build_router_index.py
The index is an optimization only: a stale fingerprint falls back to eager load.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DEEPTUTOR_CHAT_ENGINE"] = "python"

from starlette.routing import WebSocketRoute  # noqa: E402

from deeptutor.api.main import _router_loader  # noqa: E402
from deeptutor.api.router_loader import INDEX_PATH, source_fingerprint  # noqa: E402

routers = {}
for reference, router in _router_loader.records.items():
    # Router-level lifecycle callbacks must be installed eagerly by FastAPI.
    if (
        router.on_startup
        or router.on_shutdown
        or type(router.lifespan_context).__name__ != "_DefaultLifespan"
    ):
        continue
    patterns = []
    for route in router.routes:
        if not hasattr(route, "path") or not hasattr(route, "name"):
            raise ValueError(f"Unsupported nested route: {reference}")
        patterns.append(
            {
                "path": route.path,
                "name": route.name,
                "kind": "websocket" if isinstance(route, WebSocketRoute) else "http",
                "methods": sorted(getattr(route, "methods", None) or []),
            }
        )
    routers[reference] = patterns
INDEX_PATH.write_text(
    json.dumps({"fingerprint": source_fingerprint(), "routers": routers}, indent=2) + "\n"
)
print(f"Indexed {len(routers)} routers; {sum(map(len, routers.values()))} routes")
