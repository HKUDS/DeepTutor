"""云端同步路由的契约测试。

服务端这一侧只有一份契约来源：Android 端的 ``SyncTransport.kt`` /
``SyncEngine.kt`` / ``SyncPorts.kt``。这里把契约钉住，让两端漂移时先在这里炸：

* 5 个端点的正常路径与响应字段（端侧 ``ignoreUnknownKeys = false``，多一个字段就解码失败）；
* 鉴权边界：没登录就进不来；
* 白名单与方向：不在白名单的域、云权威域的端侧上行，都被拒绝；
* 敏感键：整条拒绝，且不落库、不回显；
* 幂等：同一个 ``client_op_id`` 重发不会重复应用；
* 冲突：双向域版本不一致时返回 ``conflict``，不静默覆盖；
* 游标：重放同一个游标结果稳定。

路由挂在一台裸 FastAPI 上，不启动整个应用——这里要验的是同步通道本身。
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import sync
from deeptutor.api.routers.auth import require_auth
from deeptutor.services.path_service import PathService

#: 端侧 ``SyncDomains.ALL``：白名单就是这六个。
WHITELIST = {"knowledge_base", "learning", "sessions", "settings", "persona", "agent"}


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把运行时目录指到临时目录：同步库不能写进开发者真实的家目录。"""
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    yield tmp_path
    PathService.reset_instance()


@pytest.fixture
def client(home: Path) -> TestClient:
    """已登录的同步客户端。

    会话鉴权本身有专门的测试；这里只把它挪开，让同步通道本身被测到。
    """
    app = FastAPI()
    app.include_router(
        sync.router,
        prefix="/api/sync",
        tags=["sync"],
        dependencies=[Depends(require_auth)],
    )
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


@pytest.fixture
def auth_client(home: Path) -> TestClient:
    """不豁免鉴权的客户端：用来测未登录被拒。"""
    app = FastAPI()
    app.include_router(
        sync.router,
        prefix="/api/sync",
        tags=["sync"],
        dependencies=[Depends(require_auth)],
    )
    return TestClient(app)


def _push_item(
    op_id: str,
    domain: str,
    entity_id: str,
    payload: dict[str, Any],
    *,
    revision: int = 1,
    kind: str = "upsert",
) -> dict[str, Any]:
    return {
        "client_op_id": op_id,
        "domain": domain,
        "entity_id": entity_id,
        "kind": kind,
        "payload": payload,
        "revision": revision,
        "created_at": 0,
    }


def _push(client: TestClient, item: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/sync/push", json={"items": [item]})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    return results[0]


# ---------------------------------------------------------------------------
# 正常路径
# ---------------------------------------------------------------------------


def test_manifest_lists_every_whitelisted_domain(client: TestClient) -> None:
    body = client.get("/api/sync/manifest").json()

    assert set(body["domains"]) == WHITELIST
    for entry in body["domains"].values():
        assert entry["available"] is True
        assert entry["revision"] >= 0


def test_push_then_pull_round_trip(client: TestClient) -> None:
    """上行一条设定，下行能原样拿到。"""
    result = _push(client, _push_item("op-1", "settings", "theme", {"value": "dark"}))
    assert result["status"] == "applied"
    assert result["client_op_id"] == "op-1"

    page = client.get("/api/sync/changes", params={"domain": "settings"}).json()

    assert page["revision"] >= 1
    assert len(page["items"]) == 1
    item = page["items"][0]
    assert item["entity_id"] == "theme"
    assert item["kind"] == "upsert"
    assert item["payload"] == {"value": "dark"}
    assert item["revision"] >= 1
    assert page["next_cursor"] is None


def test_end_authoritative_domain_accepts_device_changes(client: TestClient) -> None:
    """会话与学习进度是端权威：云端只是镜像，端侧上行照样接受。"""
    for domain, entity in (("sessions", "session-1"), ("learning", "path-1")):
        result = _push(client, _push_item(f"op-{domain}", domain, entity, {"title": "x"}))
        assert result["status"] == "applied"

    for domain in ("sessions", "learning"):
        page = client.get("/api/sync/changes", params={"domain": domain}).json()
        assert [item["entity_id"] for item in page["items"]] != []


def test_delete_is_published_as_a_delete(client: TestClient) -> None:
    _push(client, _push_item("op-1", "settings", "theme", {"value": "dark"}))
    result = _push(
        client,
        _push_item("op-2", "settings", "theme", {}, revision=2, kind="delete"),
    )

    assert result["status"] == "applied"
    page = client.get("/api/sync/changes", params={"domain": "settings"}).json()
    assert page["items"][-1]["kind"] == "delete"


def test_blob_upload_and_download_round_trip(client: TestClient) -> None:
    content = b"hello sync blob"
    digest = hashlib.sha256(content).hexdigest()

    uploaded = client.post(
        "/api/sync/blob",
        json={
            "domain": "knowledge_base",
            "id": "kb:doc.pdf",
            "offset": 0,
            "total": len(content),
            "sha256": digest,
            "data": base64.b64encode(content).decode("ascii"),
            "final": True,
        },
    ).json()
    assert uploaded == {"received": len(content), "completed": True}

    chunk = client.get(
        "/api/sync/blob",
        params={
            "domain": "knowledge_base",
            "id": "kb:doc.pdf",
            "offset": 0,
            "length": 1024,
        },
    ).json()
    assert chunk["offset"] == 0
    assert chunk["total"] == len(content)
    assert chunk["sha256"] == digest
    assert base64.b64decode(chunk["data"]) == content


def test_blob_chunked_upload_is_reassembled(client: TestClient) -> None:
    content = b"0123456789" * 100
    digest = hashlib.sha256(content).hexdigest()
    split = 512

    first = client.post(
        "/api/sync/blob",
        json={
            "domain": "knowledge_base",
            "id": "kb:big.bin",
            "offset": 0,
            "total": len(content),
            "sha256": digest,
            "data": base64.b64encode(content[:split]).decode("ascii"),
            "final": False,
        },
    ).json()
    assert first == {"received": split, "completed": False}

    second = client.post(
        "/api/sync/blob",
        json={
            "domain": "knowledge_base",
            "id": "kb:big.bin",
            "offset": split,
            "total": len(content),
            "sha256": digest,
            "data": base64.b64encode(content[split:]).decode("ascii"),
            "final": True,
        },
    ).json()
    assert second == {"received": len(content), "completed": True}

    chunk = client.get(
        "/api/sync/blob",
        params={
            "domain": "knowledge_base",
            "id": "kb:big.bin",
            "offset": 0,
            "length": len(content),
        },
    ).json()
    assert base64.b64decode(chunk["data"]) == content
    assert chunk["sha256"] == digest


def test_responses_carry_only_contract_fields(client: TestClient) -> None:
    """端侧 ``ignoreUnknownKeys = false``：多一个字段就是解码失败。"""
    manifest = client.get("/api/sync/manifest").json()
    assert set(manifest) == {"domains"}
    assert set(manifest["domains"]["settings"]) == {"revision", "available"}

    _push(client, _push_item("op-1", "settings", "theme", {"value": "dark"}))
    page = client.get("/api/sync/changes", params={"domain": "settings"}).json()
    assert set(page) == {"revision", "items", "next_cursor"}
    assert set(page["items"][0]) == {"entity_id", "kind", "payload", "revision"}

    pushed = client.post(
        "/api/sync/push",
        json={"items": [_push_item("op-2", "settings", "theme", {"value": "light"})]},
    ).json()
    assert set(pushed) == {"results"}
    assert set(pushed["results"][0]) == {
        "client_op_id",
        "status",
        "conflict_payload",
        "reason",
    }


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------


def test_unauthenticated_requests_are_rejected(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.api.routers.auth.AUTH_ENABLED", True)

    assert auth_client.get("/api/sync/manifest").status_code == 401
    assert auth_client.get("/api/sync/changes", params={"domain": "settings"}).status_code == 401
    assert (
        auth_client.post(
            "/api/sync/push",
            json={"items": [_push_item("op-1", "settings", "theme", {"value": "dark"})]},
        ).status_code
        == 401
    )
    assert (
        auth_client.get("/api/sync/blob", params={"domain": "settings", "id": "x"}).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/api/sync/blob",
            json={
                "domain": "settings",
                "id": "x",
                "offset": 0,
                "total": 1,
                "sha256": "",
                "data": "",
                "final": True,
            },
        ).status_code
        == 401
    )


def test_invalid_token_is_rejected(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.api.routers.auth.AUTH_ENABLED", True)

    response = auth_client.get(
        "/api/sync/manifest", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 白名单与方向
# ---------------------------------------------------------------------------


def test_non_whitelisted_domain_is_rejected(client: TestClient) -> None:
    result = _push(client, _push_item("op-1", "wallet", "balance", {"value": "1"}))

    assert result["status"] == "rejected"
    assert result["reason"]
    assert client.get("/api/sync/changes", params={"domain": "wallet"}).status_code == 400


def test_knowledge_base_push_is_rejected(client: TestClient) -> None:
    """知识库是云权威域：端侧上行不接受，也不进云端副本。"""
    result = _push(
        client,
        _push_item("op-1", "knowledge_base", "kb:doc.pdf", {"content_text": "x"}),
    )

    assert result["status"] == "rejected"
    page = client.get("/api/sync/changes", params={"domain": "knowledge_base"}).json()
    assert page["items"] == []


def test_unknown_change_kind_is_rejected(client: TestClient) -> None:
    result = _push(
        client,
        _push_item("op-1", "settings", "theme", {"value": "dark"}, kind="patch"),
    )

    assert result["status"] == "rejected"


def test_knowledge_base_is_published_from_the_cloud(home: Path, client: TestClient) -> None:
    """云权威域的内容只有云端一个来源：服务器自己的知识库要能下发。"""
    kb_root = home / "data" / "knowledge_bases"
    kb_dir = kb_root / "demo"
    (kb_dir / "raw").mkdir(parents=True)
    (kb_dir / "raw" / "note.txt").write_text("云端知识库正文", encoding="utf-8")
    (kb_root / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "demo": {
                        "path": "demo",
                        "type": "local",
                        "rag_provider": "llamaindex",
                        "status": "ready",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    page = client.get("/api/sync/changes", params={"domain": "knowledge_base"}).json()

    assert [item["entity_id"] for item in page["items"]] == ["demo:note.txt"]
    payload = page["items"][0]["payload"]
    assert payload["kb_name"] == "demo"
    assert payload["content_text"] == "云端知识库正文"

    # 原文也能作为大文件拉下来。
    chunk = client.get(
        "/api/sync/blob",
        params={
            "domain": "knowledge_base",
            "id": "demo:note.txt",
            "offset": 0,
            "length": 1024,
        },
    ).json()
    assert base64.b64decode(chunk["data"]).decode("utf-8") == "云端知识库正文"


# ---------------------------------------------------------------------------
# 敏感键
# ---------------------------------------------------------------------------


def test_sensitive_key_payload_is_rejected_and_never_stored(client: TestClient, home: Path) -> None:
    secret = "sk-should-never-touch-disk"
    response = client.post(
        "/api/sync/push",
        json={
            "items": [
                _push_item(
                    "op-1",
                    "settings",
                    "provider",
                    {"value": "x", "api_key": secret},
                )
            ]
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "rejected"
    assert result["reason"]
    # 不回显载荷。
    assert secret not in response.text

    # 不落库：变更日志里没有这一条。
    page = client.get("/api/sync/changes", params={"domain": "settings"}).json()
    assert page["items"] == []

    # 也不写进同步库的任何文件（含 WAL）。
    sync_dir = home / "data" / "user" / "sync"
    for path in sync_dir.glob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()


def test_sensitive_key_nested_in_list_is_rejected(client: TestClient) -> None:
    result = _push(
        client,
        _push_item(
            "op-1",
            "settings",
            "provider",
            {"value": "x", "profiles": [{"access_token": "abc"}]},
        ),
    )

    assert result["status"] == "rejected"


# ---------------------------------------------------------------------------
# 幂等
# ---------------------------------------------------------------------------


def test_replayed_op_id_returns_the_same_result_without_applying_twice(
    client: TestClient,
) -> None:
    item = _push_item("op-1", "settings", "theme", {"value": "dark"})

    first = _push(client, item)
    second = _push(client, item)

    assert first["status"] == "applied"
    assert second == first

    page = client.get("/api/sync/changes", params={"domain": "settings"}).json()
    assert len(page["items"]) == 1


def test_replayed_rejection_is_stable(client: TestClient) -> None:
    item = _push_item("op-1", "knowledge_base", "kb:doc.pdf", {"content_text": "x"})

    first = _push(client, item)
    second = _push(client, item)

    assert first["status"] == "rejected"
    assert second == first


# ---------------------------------------------------------------------------
# 冲突
# ---------------------------------------------------------------------------


def test_bidirectional_domain_conflict_returns_conflict_without_overwriting(
    client: TestClient,
) -> None:
    """双向域：云端与端侧版本不一致时留冲突，不静默覆盖云端副本。"""
    first = _push(client, _push_item("op-1", "settings", "theme", {"value": "dark"}))
    assert first["status"] == "applied"

    # 另一台设备基于同一个端侧版本改了内容：云端副本已经走到这次修改之前。
    second = _push(client, _push_item("op-2", "settings", "theme", {"value": "light"}))

    assert second["status"] == "conflict"
    assert second["conflict_payload"] == {"value": "dark"}
    assert second["reason"]

    # 云端副本没有被覆盖，变更日志里也只有那一条。
    page = client.get("/api/sync/changes", params={"domain": "settings"}).json()
    assert len(page["items"]) == 1
    assert page["items"][0]["payload"] == {"value": "dark"}


def test_bidirectional_domain_accepts_a_newer_device_revision(client: TestClient) -> None:
    _push(client, _push_item("op-1", "settings", "theme", {"value": "dark"}, revision=1))
    result = _push(client, _push_item("op-2", "settings", "theme", {"value": "light"}, revision=2))

    assert result["status"] == "applied"
    page = client.get("/api/sync/changes", params={"domain": "settings"}).json()
    assert page["items"][-1]["payload"] == {"value": "light"}


def test_persona_conflict_is_also_archived(client: TestClient) -> None:
    _push(client, _push_item("op-1", "persona", "coach", {"content": "a"}))
    result = _push(client, _push_item("op-2", "persona", "coach", {"content": "b"}))

    assert result["status"] == "conflict"
    assert result["conflict_payload"] == {"content": "a"}


# ---------------------------------------------------------------------------
# 游标
# ---------------------------------------------------------------------------


def test_cursor_pages_are_stable(client: TestClient) -> None:
    for index in range(5):
        _push(client, _push_item(f"op-{index}", "settings", f"key-{index}", {"value": index}))

    first = client.get("/api/sync/changes", params={"domain": "settings", "limit": 2}).json()
    assert [item["entity_id"] for item in first["items"]] == ["key-0", "key-1"]
    assert first["next_cursor"]

    # 重放同一个游标：同一页，同样的结果。
    replay = client.get("/api/sync/changes", params={"domain": "settings", "limit": 2}).json()
    assert replay == first

    second = client.get(
        "/api/sync/changes",
        params={"domain": "settings", "since": first["next_cursor"], "limit": 2},
    ).json()
    assert [item["entity_id"] for item in second["items"]] == ["key-2", "key-3"]
    assert second["next_cursor"] != first["next_cursor"]

    third = client.get(
        "/api/sync/changes",
        params={"domain": "settings", "since": second["next_cursor"], "limit": 2},
    ).json()
    assert [item["entity_id"] for item in third["items"]] == ["key-4"]
    assert third["next_cursor"] is None

    # 同一游标再翻一次，结果不变。
    third_again = client.get(
        "/api/sync/changes",
        params={"domain": "settings", "since": second["next_cursor"], "limit": 2},
    ).json()
    assert third_again == third


def test_invalid_cursor_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/sync/changes", params={"domain": "settings", "since": "not-a-cursor"}
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 挂载
# ---------------------------------------------------------------------------


def test_sync_router_is_mounted_with_auth_in_main() -> None:
    """main.py 里这一行挂载是契约的一部分：路径、方法与鉴权门都要在。

    这里刻意不重定向 ``DEEPTUTOR_HOME``：``deeptutor.api.main`` 在导入时就要读
    项目根下的 ``data/user/settings``，重定向会让它找不到配置文件。
    """
    from deeptutor.api.main import app
    from deeptutor.api.routers.auth import require_auth

    endpoints: dict[str, set[str]] = {}
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if not callable(contexts):
            continue
        for context in contexts():
            path = getattr(context, "path", None)
            if not isinstance(path, str) or not path.startswith("/api/sync"):
                continue
            methods = getattr(context, "methods", None) or set()
            endpoints.setdefault(path, set()).update(methods)
            calls = [dependency.call for dependency in context.dependant.dependencies]
            assert require_auth in calls, f"{path} 没有挂 require_auth"

    assert endpoints == {
        "/api/sync/manifest": {"GET"},
        "/api/sync/changes": {"GET"},
        "/api/sync/push": {"POST"},
        "/api/sync/blob": {"GET", "POST"},
    }
