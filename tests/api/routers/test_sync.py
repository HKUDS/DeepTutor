"""云端同步路由的契约测试。

服务端这一侧只有一份契约来源：Android 端的 ``SyncTransport.kt`` /
``SyncEngine.kt`` / ``SyncPorts.kt``。这里把契约钉住，让两端漂移时先在这里炸：

* 5 个端点的正常路径与响应字段（端侧 ``ignoreUnknownKeys = false``，多一个字段就解码失败）；
* 鉴权边界：没登录就进不来；
* 白名单与方向：不在白名单的域、云权威域的端侧上行，都被拒绝；
* 敏感键：整条拒绝，且不落库、不回显；
* 幂等：同一个 ``client_op_id`` 重发不会重复应用；
* 冲突：双向域版本不一致时返回 ``conflict``，不静默覆盖；
* 游标：重放同一个游标结果稳定；
* 云端发布源：设定 / 画像 / agent 的实体 id 与载荷字段逐字对齐端侧映射，
  设定里的凭据键在发布前被剥掉，重复发布不让版本号无限增长。

路由挂在一台裸 FastAPI 上，不启动整个应用——这里要验的是同步通道本身。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import sync
from deeptutor.api.routers.auth import require_auth
from deeptutor.services.path_service import PathService

#: 端侧 ``SyncDomains.ALL``：白名单就是这七个。
WHITELIST = {
    "knowledge_base",
    "learning",
    "sessions",
    "settings",
    "persona",
    "agent",
    "memory",
}


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
# 云端发布源的夹具
# ---------------------------------------------------------------------------


def _settings_dir(home: Path) -> Path:
    """运行时设定目录：``data/user/settings``。"""
    return home / "data" / "user" / "settings"


def _personas_dir(home: Path) -> Path:
    """运行时画像目录：``data/user/workspace/personas``。"""
    return home / "data" / "user" / "workspace" / "personas"


def _write_setting(home: Path, name: str, payload: Any = None, *, raw: str | None = None) -> Path:
    """写一份设定文档。``raw`` 直接写原文，用来造解析失败的场景。"""
    path = _settings_dir(home) / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw if raw is not None else json.dumps(payload, ensure_ascii=False), "utf-8")
    return path


def _write_persona(home: Path, name: str, body: str = "你是一位严格的教练。\n") -> Path:
    """写一个画像：``workspace/personas/<name>/PERSONA.md``。"""
    path = _personas_dir(home) / name / "PERSONA.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {name} 的说明\n---\n\n{body}", "utf-8")
    return path


def _write_agents(home: Path, text: str) -> Path:
    """写一份 agent 配置：``data/user/settings/agents.yaml``。"""
    path = _settings_dir(home) / "agents.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    return path


def _changes(client: TestClient, domain: str) -> dict[str, Any]:
    return client.get("/api/sync/changes", params={"domain": domain}).json()


def _by_entity(page: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["entity_id"]: item for item in page["items"]}


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
        "revision",
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
    # 端侧 ``kb_documents`` 的四列：原文走 blob 分块接口，不在载荷里。
    assert set(payload) == {"kb_name", "title", "source_type", "content_text"}
    assert payload["kb_name"] == "demo"
    assert payload["title"] == "note"
    assert payload["source_type"] == "file"
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
# 云端发布源：设定 / 画像 / agent
# ---------------------------------------------------------------------------


def test_settings_are_published_with_the_setting_key_and_value(
    home: Path, client: TestClient
) -> None:
    """设定域：实体 id 是设定键，载荷是 ``{"value": <JSON 值>}``。"""
    _write_setting(home, "interface", {"theme": "snow", "language": "en"})

    items = _by_entity(_changes(client, "settings"))

    assert "interface" in items
    payload = items["interface"]["payload"]
    assert set(payload) == {"value"}
    assert payload["value"] == {"theme": "snow", "language": "en"}
    assert items["interface"]["kind"] == "upsert"


def test_persona_is_published_with_description_and_content(home: Path, client: TestClient) -> None:
    """画像域：实体 id 是画像名，载荷是 ``{"description", "content"}``。"""
    _write_persona(home, "coach", "只讲结论。\n")

    items = _by_entity(_changes(client, "persona"))

    assert "coach" in items
    payload = items["coach"]["payload"]
    assert set(payload) == {"description", "content"}
    assert payload["description"] == "coach 的说明"
    assert "只讲结论。" in payload["content"]


def test_agent_config_is_published_with_name_and_config(home: Path, client: TestClient) -> None:
    """agent 域：实体 id 是 agent 名，载荷是 ``{"name", "config"}``。

    源是 ``agents.yaml``（用户自己的 agent 配置），不是界面那份静态元数据。
    """
    _write_agents(
        home,
        "capabilities:\n  solve:\n    temperature: 0.3\n    max_tokens: 8192\n",
    )

    items = _by_entity(_changes(client, "agent"))

    assert "solve" in items
    payload = items["solve"]["payload"]
    assert set(payload) == {"name", "config"}
    assert payload["name"] == "solve"
    assert payload["config"]["temperature"] == 0.3


def test_agent_token_budget_is_stripped_like_on_the_device(home: Path, client: TestClient) -> None:
    """``max_tokens`` 两端都判成凭据键，发布时就得剥掉。

    端侧 ``SyncDomains.FORBIDDEN_KEY_PARTS`` 里的 ``token`` 按子串命中
    ``max_tokens``，端侧的下行闸门会因此**整条拒绝**这份 agent 配置。云端
    跟着同一口径剥掉：配置照样下发，只是少了 token 预算——总比整条被端侧
    拒收强。
    """
    _write_agents(
        home,
        "capabilities:\n  solve:\n    temperature: 0.3\n    max_tokens: 8192\n",
    )

    items = _by_entity(_changes(client, "agent"))

    config = items["solve"]["payload"]["config"]
    assert "max_tokens" not in config
    assert config == {"temperature": 0.3}


def test_settings_credential_keys_are_stripped_and_the_rest_is_kept(
    home: Path, client: TestClient
) -> None:
    """发布设定前逐层剥离凭据键：整条丢弃，不是换成空串。"""
    _write_setting(
        home,
        "model_catalog",
        {
            "version": 1,
            "api_key": "sk-placeholder-value",
            "api_key_backup": "sk-placeholder-value",
            "services": {"llm": {"profiles": [{"id": "p1", "api_key": "sk-placeholder-value"}]}},
        },
    )

    items = _by_entity(_changes(client, "settings"))

    value = items["model_catalog"]["payload"]["value"]
    assert "api_key" not in value
    assert "api_key_backup" not in value
    assert value["version"] == 1
    profile = value["services"]["llm"]["profiles"][0]
    assert "api_key" not in profile
    assert profile["id"] == "p1"


def test_settings_credential_keys_nested_in_lists_are_stripped(
    home: Path, client: TestClient
) -> None:
    """凭据键藏在列表里的映射上也要剥掉。"""
    _write_setting(
        home,
        "integrations",
        {
            "turn_coordination": {"backend": "memory"},
            "connections": [
                {
                    "id": "c1",
                    "api_key": "sk-placeholder-value",
                    "base_url": "https://example.invalid",
                },
                {"id": "c2", "secret_token": "sk-placeholder-value"},
            ],
        },
    )

    items = _by_entity(_changes(client, "settings"))

    value = items["integrations"]["payload"]["value"]
    assert value["turn_coordination"] == {"backend": "memory"}
    first, second = value["connections"]
    assert "api_key" not in first
    assert first["base_url"] == "https://example.invalid"
    assert "secret_token" not in second
    assert second["id"] == "c2"


def test_published_settings_never_write_credentials_to_disk(home: Path, client: TestClient) -> None:
    """剥掉的凭据不出现在同步库的任何文件里。"""
    secret = "sk-never-reach-the-phone"
    _write_setting(
        home,
        "model_catalog",
        {"api_key": secret, "profiles": [{"id": "p1", "api_key": secret}]},
    )

    response = client.get("/api/sync/changes", params={"domain": "settings"})

    assert response.status_code == 200
    assert secret not in response.text
    sync_dir = home / "data" / "user" / "sync"
    for path in sync_dir.glob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()


def test_republishing_the_same_content_does_not_grow_the_revision(
    home: Path, client: TestClient
) -> None:
    """重复发布同一份内容：版本号不动，端侧不会每轮都拉到「变更」。"""
    _write_setting(home, "interface", {"theme": "snow"})

    first = _changes(client, "settings")
    second = _changes(client, "settings")

    assert len(first["items"]) == 1
    assert second["revision"] == first["revision"]
    assert len(second["items"]) == 1


def test_republishing_after_a_touch_still_does_not_grow_the_revision(
    home: Path, client: TestClient
) -> None:
    """源文件被动过（内容没变）：发布器重读一遍，版本号照样不动。"""
    path = _write_setting(home, "interface", {"theme": "snow"})

    first = _changes(client, "settings")

    stat = path.stat()
    os.utime(path, (stat.st_atime + 10, stat.st_mtime + 10))
    second = _changes(client, "settings")

    assert second["revision"] == first["revision"]
    assert len(second["items"]) == 1


def test_a_broken_setting_file_does_not_stop_the_other_settings(
    home: Path, client: TestClient
) -> None:
    """一份设定解析失败：跳过这一份，其余设定照发，端点不 500。"""
    _write_setting(home, "interface", raw="{ 不是合法 JSON")
    _write_setting(home, "system", {"version_check_enabled": True})

    response = client.get("/api/sync/changes", params={"domain": "settings"})

    assert response.status_code == 200
    items = _by_entity(response.json())
    assert "interface" not in items
    assert items["system"]["payload"]["value"] == {"version_check_enabled": True}


def test_a_failing_domain_does_not_stop_the_other_domains(
    home: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一个域发布失败：跳过那个域，其余域照常，端点不 500。"""

    def boom(store: Any) -> None:
        raise RuntimeError("发布失败")

    monkeypatch.setattr(sync, "_publish_settings", boom)
    _write_persona(home, "coach")
    _write_agents(home, "capabilities:\n  solve:\n    max_tokens: 8192\n")

    manifest = client.get("/api/sync/manifest")
    assert manifest.status_code == 200

    assert "coach" in _by_entity(_changes(client, "persona"))
    assert "solve" in _by_entity(_changes(client, "agent"))
    assert _changes(client, "settings")["items"] == []


def test_device_upload_and_cloud_publish_coexist(home: Path, client: TestClient) -> None:
    """端侧上行与云端发布走同一套变更日志，互不覆盖。"""
    _write_setting(home, "interface", {"theme": "snow"})

    result = _push(client, _push_item("op-1", "settings", "device_only", {"value": 1}))

    assert result["status"] == "applied"
    items = _by_entity(_changes(client, "settings"))
    assert items["device_only"]["payload"] == {"value": 1}
    assert items["interface"]["payload"]["value"] == {"theme": "snow"}


def test_cloud_publish_keeps_the_device_version_so_conflicts_are_detected(
    home: Path, client: TestClient
) -> None:
    """双向域：云端改了同一份设定，端侧再推回来是冲突，不是静默覆盖。"""
    pushed = _push(
        client,
        _push_item("op-1", "settings", "interface", {"value": {"theme": "dark"}}, revision=1),
    )
    assert pushed["status"] == "applied"

    _write_setting(home, "interface", {"theme": "snow"})
    _changes(client, "settings")

    again = _push(
        client,
        _push_item("op-2", "settings", "interface", {"value": {"theme": "dark"}}, revision=1),
    )

    assert again["status"] == "conflict"
    assert again["conflict_payload"] == {"value": {"theme": "snow"}}


# ---------------------------------------------------------------------------
# 记忆域：端权威，云端只做镜像
# ---------------------------------------------------------------------------

#: 端侧记忆条目的 id 形态：``m_<ULID>``。
MEMORY_ID = "m_01HZK4ABCDEFGHJKMNPQRSTVWX"


def _memory_item(
    op_id: str,
    entity_id: str = MEMORY_ID,
    *,
    level: str = "L2",
    scope: str = "chat",
    slot: str = "device",
    content: str = "用户偏好简洁回答",
    revision: int = 1,
) -> dict[str, Any]:
    return _push_item(
        op_id,
        "memory",
        entity_id,
        {"level": level, "scope": scope, "slot": slot, "content": content},
        revision=revision,
    )


def test_memory_domain_is_offered_in_the_manifest(client: TestClient) -> None:
    """端侧按清单决定同步哪些域：记忆不在清单里就永远同步不出去。"""
    body = client.get("/api/sync/manifest").json()

    assert "memory" in body["domains"]
    assert body["domains"]["memory"]["available"] is True
    assert body["domains"]["memory"]["revision"] >= 0


def test_memory_entry_is_accepted_and_pulled_back(client: TestClient) -> None:
    """记忆是端权威域：端侧上行接受，下行拿得到自己的镜像。"""
    result = _push(client, _memory_item("op-1"))

    assert result["status"] == "applied"

    page = _changes(client, "memory")
    items = _by_entity(page)
    assert MEMORY_ID in items
    item = items[MEMORY_ID]
    assert item["kind"] == "upsert"
    assert item["payload"] == {
        "level": "L2",
        "scope": "chat",
        "slot": "device",
        "content": "用户偏好简洁回答",
    }


def test_memory_entry_lands_in_the_mirror_table(home: Path, client: TestClient) -> None:
    """记忆镜像表按列存：云端不必解 JSON 就能读。"""
    _push(client, _memory_item("op-1"))

    import sqlite3

    db = home / "data" / "user" / "sync" / "sync.db"
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT entity_id, level, scope, slot, content FROM sync_memory_entries"
        ).fetchone()
    finally:
        conn.close()

    assert row == (MEMORY_ID, "L2", "chat", "device", "用户偏好简洁回答")


def test_memory_entry_is_written_into_the_cloud_memory_document(
    home: Path, client: TestClient
) -> None:
    """端侧的记忆要落进云端自己的 L2 文档，云端的对话才用得上。"""
    _push(client, _memory_item("op-1"))

    doc = home / "data" / "memory" / "L2" / "chat.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "用户偏好简洁回答" in text
    assert MEMORY_ID in text


def test_memory_entry_for_an_unknown_slot_stays_in_the_mirror(
    home: Path, client: TestClient
) -> None:
    """对不上云端文档的条目：留在镜像表里，不塞进不对的文档。"""
    result = _push(client, _memory_item("op-1", scope="不是云端的面"))

    assert result["status"] == "applied"
    assert not (home / "data" / "memory" / "L2").exists()


def test_deleted_memory_entry_leaves_the_cloud_memory_document(
    home: Path, client: TestClient
) -> None:
    """条目删掉了，云端文档里那一条也要拿掉，镜像表里也要空。"""
    _push(client, _memory_item("op-1"))
    doc = home / "data" / "memory" / "L2" / "chat.md"
    assert MEMORY_ID in doc.read_text(encoding="utf-8")

    result = _push(
        client,
        _push_item(
            "op-2",
            "memory",
            MEMORY_ID,
            {},
            revision=2,
            kind="delete",
        ),
    )

    assert result["status"] == "applied"
    assert MEMORY_ID not in doc.read_text(encoding="utf-8")

    import sqlite3

    conn = sqlite3.connect(home / "data" / "user" / "sync" / "sync.db")
    try:
        rows = conn.execute("SELECT entity_id FROM sync_memory_entries").fetchall()
    finally:
        conn.close()
    assert rows == []


def test_memory_push_is_never_a_conflict(client: TestClient) -> None:
    """端权威域不做双向冲突：端侧推什么，云端就镜像什么。"""
    first = _push(client, _memory_item("op-1", revision=1))
    second = _push(client, _memory_item("op-2", revision=1, content="改过的记忆"))

    assert first["status"] == "applied"
    assert second["status"] == "applied"


def test_cloud_does_not_publish_memory_of_its_own(client: TestClient) -> None:
    """端权威域：云端不把自己的记忆往下发，记忆变更只来自端侧上行。"""
    page = _changes(client, "memory")

    assert page["items"] == []
    assert page["revision"] == 0


# ---------------------------------------------------------------------------
# 上行回执的服务端版本号
# ---------------------------------------------------------------------------


def test_push_receipt_carries_the_server_revision(client: TestClient) -> None:
    """回执带版本号：端侧据此推进「云端那一半」的基线，不会误报假冲突。"""
    result = _push(client, _push_item("op-1", "settings", "theme", {"value": "dark"}))

    assert result["status"] == "applied"
    assert result["revision"] >= 1

    page = _changes(client, "settings")
    assert page["items"][0]["revision"] == result["revision"]


def test_replayed_push_returns_the_same_revision(client: TestClient) -> None:
    """重发同一条上行：回放首次结果，版本号也一样。"""
    item = _push_item("op-1", "settings", "theme", {"value": "dark"})

    first = _push(client, item)
    second = _push(client, item)

    assert second == first
    assert second["revision"] == first["revision"]


def test_conflict_receipt_reports_the_cloud_revision(client: TestClient) -> None:
    """冲突回执里的版本号是云端那一份的版本。"""
    _push(client, _push_item("op-1", "settings", "theme", {"value": "dark"}, revision=1))

    conflict = _push(client, _push_item("op-2", "settings", "theme", {"value": "light"}))

    assert conflict["status"] == "conflict"
    assert conflict["revision"] >= 1


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
