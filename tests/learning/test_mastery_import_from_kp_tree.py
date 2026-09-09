"""P7【2】import-from-kp-tree：鉴权（无书权限 404）、幂等、正常路径。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
Depends = pytest.importorskip("fastapi").Depends

from deeptutor.api.routers import mastery_path as mastery_router_module
from deeptutor.book.models import Book
from deeptutor.learning.storage import LearningStore
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import local_admin_user

#: 目级 canonical KP tree：import-from-kp-tree 应取目级模块（比章级机械
#: 转换更细），两个目合成一个 module，桥直达教材树。
KP_TREE: dict[str, Any] = {
    "title": "人教A数学选择性必修第三册",
    "children": [
        {
            "title": "第六章 计数原理",
            "struct_path": "第六章 计数原理",
            "node_id": "ch6",
            "children": [
                {
                    "title": "6.2 排列与组合",
                    "struct_path": "第六章 计数原理/6.2 排列与组合",
                    "node_id": "62",
                    "children": [
                        {
                            "title": "6.2.1 排列",
                            "struct_path": "第六章 计数原理/6.2 排列与组合/6.2.1 排列",
                            "node_id": "621",
                            "type": "mu",
                        },
                        {
                            "title": "6.2.2 组合",
                            "struct_path": "第六章 计数原理/6.2 排列与组合/6.2.2 组合",
                            "node_id": "622",
                            "type": "mu",
                        },
                    ],
                }
            ],
        }
    ],
}


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Multi-user paths isolated under tmp_path; the caller is local admin.

    与 multi_user conftest 同样的全局隔离。另有两处单用户兜底也要指到
    隔离根：``PathService.get_instance()``（无 current user 时的默认工作区）
    和请求内的 current user（用 FastAPI dependency 注入，等价于生产环境的
    auth 中间件）。书保存在 admin 工作区，resolve_book 走 own 分支。
    """
    from deeptutor.book import engine as engine_module
    from deeptutor.book import storage as storage_module
    from deeptutor.multi_user import identity, paths
    from deeptutor.services import auth as auth_service
    from deeptutor.services import path_service as path_service_module

    admin_root = (tmp_path / "data").resolve()
    system_root = admin_root / "system"
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")
    # 无请求上下文时（fixture 准备阶段）的默认工作区。
    monkeypatch.setattr(
        path_service_module.PathService,
        "_instance",
        path_service_module.PathService(workspace_root=admin_root),
    )
    storage_module._storages.clear()
    engine_module._engines.clear()
    monkeypatch.setattr(
        mastery_router_module,
        "_cancel_active_learning_turn",
        lambda book_id: asyncio.sleep(0),
    )

    storage = storage_module.get_book_storage()
    storage.save_book(Book(id="bk_kp", title="数学选必三"))
    assert storage.save_canonical_kp_tree("bk_kp", KP_TREE) is True

    # 请求内 current user —— 测试用 isolated["current"]["user"] 切人。
    current: dict[str, CurrentUser] = {"user": local_admin_user()}

    async def install_user():
        token = set_current_user(current["user"])
        try:
            yield
        finally:
            reset_current_user(token)

    app = FastAPI(dependencies=[Depends(install_user)])
    app.include_router(mastery_router_module.router, prefix="/api/v1/learning")
    return {
        "client": TestClient(app),
        "book_storage": storage,
        "root": tmp_path,
        "admin_root": admin_root,
        "current": current,
    }


@contextmanager
def _as(user: CurrentUser) -> Iterator[None]:
    token = set_current_user(user)
    try:
        yield
    finally:
        reset_current_user(token)


def test_import_from_kp_tree_builds_path(isolated: dict) -> None:
    response = isolated["client"].post(
        "/api/v1/learning/progress/bk_kp/import-from-kp-tree", json={}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"

    # 目级 mu 模块优先于转换器的章级草图。
    with _as(local_admin_user()):
        progress = LearningStore().load("bk_kp")
    assert progress is not None
    assert [m.name for m in progress.modules] == ["6.2 排列与组合"]
    assert [kp.name for kp in progress.modules[0].knowledge_points] == [
        "6.2.1 排列",
        "6.2.2 组合",
    ]
    assert progress.modules[0].knowledge_points[0].textbook_node_id == "621"


def test_import_from_kp_tree_is_idempotent(isolated: dict) -> None:
    client = isolated["client"]
    assert (
        client.post("/api/v1/learning/progress/bk_kp/import-from-kp-tree", json={}).status_code
        == 200
    )

    # 学了一点：再调用必须返回现状，而不是把掌握度清零重建。
    with _as(local_admin_user()):
        store = LearningStore()
        progress = store.load("bk_kp")
        assert progress is not None
        kp_id = progress.modules[0].knowledge_points[0].id
        progress.mastery_levels[kp_id] = 0.9
        store.save(progress)

    second = client.post("/api/v1/learning/progress/bk_kp/import-from-kp-tree", json={})
    assert second.status_code == 200, second.text
    assert second.json()["idempotent"] is True
    assert second.json()["module_count"] == 1

    with _as(local_admin_user()):
        after = LearningStore().load("bk_kp")
    assert after is not None
    assert after.mastery_levels.get(kp_id) == 0.9
    assert [m.name for m in after.modules] == ["6.2 排列与组合"]


def test_import_from_kp_tree_force_rebuilds(isolated: dict) -> None:
    client = isolated["client"]
    assert (
        client.post("/api/v1/learning/progress/bk_kp/import-from-kp-tree", json={}).status_code
        == 200
    )

    with _as(local_admin_user()):
        store = LearningStore()
        progress = store.load("bk_kp")
        assert progress is not None
        progress.modules[0].name = "被改坏的章名"
        store.save(progress)

    forced = client.post(
        "/api/v1/learning/progress/bk_kp/import-from-kp-tree", json={"force": True}
    )
    assert forced.status_code == 200, forced.text
    assert forced.json().get("idempotent") is not True

    with _as(local_admin_user()):
        rebuilt = LearningStore().load("bk_kp")
    assert rebuilt is not None
    assert [m.name for m in rebuilt.modules] == ["6.2 排列与组合"]


def test_import_from_kp_tree_requires_book_read_access(isolated: dict, monkeypatch) -> None:
    """有书但无权限（bob 对 admin 的书没有任何授权）→ 404。"""
    from deeptutor.multi_user import book_access
    from deeptutor.multi_user.book_permission import BookPermission
    from deeptutor.multi_user.models import UserScope
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        book_access, "permission_for_user", lambda user: BookPermission(default="none")
    )
    bob = CurrentUser(
        id="u_bob",
        username="bob",
        role="user",
        scope=UserScope(
            kind="user",
            user_id="u_bob",
            root=(isolated["admin_root"] / "users" / "u_bob").resolve(),
        ),
    )
    isolated["current"]["user"] = bob
    response = isolated["client"].post(
        "/api/v1/learning/progress/bk_kp/import-from-kp-tree", json={}
    )
    # 书在 admin 工作区，bob 无授权 → resolve_book 语义下与不存在不可区分。
    assert response.status_code == 404, response.text

    # bob 的工作区没有被写入任何 path。
    with _as(bob):
        assert LearningStore().load("bk_kp") is None


def test_import_from_kp_tree_read_grant_allows_import(isolated: dict, monkeypatch) -> None:
    """read 授权即可导入：书读的是 owner 工作区，path 写进读者自己的 mastery 库。"""
    from deeptutor.multi_user import book_access
    from deeptutor.multi_user.book_permission import BookPermission
    from deeptutor.multi_user.models import UserScope
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        book_access,
        "permission_for_user",
        lambda user: BookPermission(books=(("bk_kp", "read"),)),
    )
    carol = CurrentUser(
        id="u_carol",
        username="carol",
        role="user",
        scope=UserScope(
            kind="user",
            user_id="u_carol",
            root=(isolated["admin_root"] / "users" / "u_carol").resolve(),
        ),
    )
    isolated["current"]["user"] = carol
    response = isolated["client"].post(
        "/api/v1/learning/progress/bk_kp/import-from-kp-tree", json={}
    )
    assert response.status_code == 200, response.text
    assert response.json()["module_count"] == 1

    with _as(carol):
        progress = LearningStore().load("bk_kp")
    assert progress is not None
    assert [m.name for m in progress.modules] == ["6.2 排列与组合"]
