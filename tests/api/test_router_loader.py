"""Deferred schemas preserve routing, dependency admission and OpenAPI."""

import json
import sys
from types import ModuleType

from fastapi import APIRouter, Depends, FastAPI, HTTPException, WebSocket
from fastapi.testclient import TestClient
import pytest

from deeptutor.api import router_loader as module


@pytest.fixture
def fixture_router(monkeypatch, tmp_path):
    fixture = ModuleType("_deferred_router_fixture")
    router = APIRouter()

    @router.get("/items/{item_id}", name="fixture_item")
    async def item(item_id: int, q: str = ""):
        return {"id": item_id, "q": q}

    @router.websocket("/socket")
    async def socket(ws: WebSocket):
        await ws.accept()
        await ws.send_json({"ok": True})
        await ws.close()

    fixture.router = router
    monkeypatch.setitem(sys.modules, fixture.__name__, fixture)
    reference = fixture.__name__ + ":router"
    patterns = [
        {"kind": "http", "path": "/items/{item_id}", "name": "fixture_item", "methods": ["GET"]},
        {"kind": "websocket", "path": "/socket", "name": "socket", "methods": []},
    ]
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"fingerprint": "fixture", "routers": {reference: patterns}}))
    monkeypatch.setattr(module, "INDEX_PATH", path)
    monkeypatch.setattr(module, "source_fingerprint", lambda: "fixture")
    return reference, path


def test_lazy_routes_keep_validation_methods_redirects_url_generation_and_websockets(
    fixture_router,
):
    ref, _ = fixture_router
    app = FastAPI()
    loader = module.RouterLoader(app, lazy=True)
    loader.include(ref, prefix="/api", tags=["fixture"])
    deferred = app.routes[-1]
    assert deferred.loaded is None
    assert str(app.url_path_for("fixture_item", item_id=7)) == "/api/items/7"
    with TestClient(app) as client:
        assert client.get("/missing").status_code == 404
        assert deferred.loaded is None
        assert client.post("/api/items/7").status_code == 405
        assert client.head("/api/items/7").status_code == 405
        loaded = deferred.loaded
        assert client.get("/api/items/7?q=value").json() == {"id": 7, "q": "value"}
        assert client.get("/api/items/bad").status_code == 422
        assert client.get("/api/items/7/", follow_redirects=False).status_code == 307
        with client.websocket_connect("/api/socket") as ws:
            assert ws.receive_json() == {"ok": True}
        assert deferred.loaded is loaded


def test_lazy_route_authentication_is_original_dependency(fixture_router):
    ref, _ = fixture_router
    app = FastAPI()

    async def deny():
        raise HTTPException(403, "fixture denied")

    loader = module.RouterLoader(app, lazy=True)
    loader.include(ref, prefix="/api", dependencies=[Depends(deny)])
    with TestClient(app) as client:
        assert client.get("/api/items/7").status_code == 403
    app.dependency_overrides[deny] = lambda: None
    with TestClient(app) as client:
        assert client.get("/api/items/7").status_code == 200


def test_lazy_and_eager_openapi_identical_and_stale_index_loads_eagerly(fixture_router):
    ref, path = fixture_router
    lazy, eager = FastAPI(), FastAPI()
    module.RouterLoader(lazy, lazy=True).include(ref, prefix="/api", tags=["fixture"])
    module.RouterLoader(eager).include(ref, prefix="/api", tags=["fixture"])
    assert lazy.openapi() == eager.openapi()
    assert not any(isinstance(r, module.DeferredRouter) for r in lazy.routes)
    path.write_text('{"fingerprint":"stale","routers":{}}')
    fallback = FastAPI()
    module.RouterLoader(fallback, lazy=True).include(ref, prefix="/api", tags=["fixture"])
    assert fallback.openapi() == eager.openapi()


def test_repository_index_matches_router_sources():
    index = json.loads(module.INDEX_PATH.read_text())
    assert index["fingerprint"] == module.source_fingerprint(), "Run scripts/build_router_index.py"
    from deeptutor.api.main import _router_loader

    for reference, router in _router_loader.records.items():
        if reference not in index["routers"]:
            continue
        expected = [
            (r.path, r.name, sorted(getattr(r, "methods", None) or [])) for r in router.routes
        ]
        actual = [(r["path"], r["name"], r["methods"]) for r in index["routers"][reference]]
        assert expected == actual, reference
