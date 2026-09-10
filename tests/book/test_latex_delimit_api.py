"""P5fix 渲染端验证：存量修复必须落进 GET /pages 服务端读取的层。

09-09 生产实锤：存量修复只改了 params（文件镜像），API 返回 0 处定界——
修复是否生效只能以「教师请求页面 API、响应体含定界公式」为准，不是 CLI
计数。这个测试钉住该判据：修复前 API 裸着，走官方写路径修复后同一请求
必须看得见 ``$\\overrightarrow{OA}$``。
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
import pytest
from starlette.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import book as book_router
from deeptutor.book import engine as engine_module
from deeptutor.book import storage as storage_module
from deeptutor.book.latex_delimit import fix_book
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    Page,
    PageStatus,
)
from deeptutor.multi_user.book_permission import BookPermission
from deeptutor.services.auth import TokenPayload

BOOK_ID = "bk_7a519f7e6e"
PAGE_ID = "pg_page8"

# 09-09 老板贴的页8 原样样本：params 与 payload 各持一份的存量形态。
PAGE8_BODY = (
    "（2）如图1.1-3，已知向量 \\overrightarrow{OA}、\\overrightarrow{OB}，"
    "以 OA、OB 为邻边作平行四边形 OA CB，则对角线 \\overrightarrow{OC} "
    "就是表示向量 \\overrightarrow{OA} 与 \\overrightarrow{OB} 的和的向量。\n"
    "(1) a+b=\\overrightarrow{OA}+\\overrightarrow{AB}=\\overrightarrow{OB};\n"
    "\\lambda(\\mu a)=(\\lambda\\mu)a"
)


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    from deeptutor.multi_user import audit, grants, identity, paths
    from deeptutor.multi_user.identity import save_user, set_book_permission
    from deeptutor.multi_user.paths import get_admin_path_service
    from deeptutor.services import auth as auth_service

    admin_root = (tmp_path / "data").resolve()
    system_root = admin_root / "system"
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "missing-secret")
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")
    monkeypatch.setattr(audit, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")
    storage_module._storages.clear()
    engine_module._engines.clear()

    teacher = save_user("teacher1", "hash", role="user")
    set_book_permission("teacher1", BookPermission(books=((BOOK_ID, "read"),)))
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda token: (
            TokenPayload(username="teacher1", role="user", user_id=teacher["id"])
            if token == "teacher-token"
            else None
        ),
    )

    from deeptutor.book.storage import BookStorage

    # 页面在 admin（教材目录）工作区，教师经授权读取——与生产共享书同构。
    admin_storage = BookStorage(path_service=get_admin_path_service())
    admin_storage.save_book(Book(id=BOOK_ID, title="高中数学人教A版选择性必修第一册"))
    page = Page(
        id=PAGE_ID,
        book_id=BOOK_ID,
        title="页8",
        status=PageStatus.READY,
        blocks=[
            Block(
                type=BlockType.READING,
                status=BlockStatus.READY,
                params={"body": PAGE8_BODY, "variant": "prose", "source_label": "textbook"},
                payload={"body": PAGE8_BODY, "format": "markdown", "author": "textbook"},
            )
        ],
    )
    admin_storage.save_page(page)

    app = FastAPI()
    app.include_router(
        book_router.router,
        prefix="/api",
        dependencies=[Depends(auth_router.require_auth)],
    )
    return TestClient(app), admin_storage


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer teacher-token"}


def test_fix_book_makes_delimited_formula_visible_through_page_api(api_env) -> None:
    client, admin_storage = api_env

    # 修复前：教师请求页面 API——裸命令原样漏出（09-09 的线上现状）。
    before = client.get(f"/api/books/{BOOK_ID}/pages/{PAGE_ID}", headers=_headers())
    assert before.status_code == 200
    before_body = before.json()["page"]["blocks"][0]["payload"]["body"]
    assert "$\\overrightarrow{OA}$" not in before_body

    summary = fix_book(BOOK_ID, storage=admin_storage)

    assert summary["blocks_fixed"] == 1
    # 修复后：同一请求必须看见定界公式——渲染端判据，不是 CLI 计数。
    after = client.get(f"/api/books/{BOOK_ID}/pages/{PAGE_ID}", headers=_headers())
    assert after.status_code == 200
    after_body = after.json()["page"]["blocks"][0]["payload"]["body"]
    assert "$\\overrightarrow{OA}$" in after_body
    assert "$\\lambda(\\mu a)=(\\lambda\\mu)a$" in after_body
    assert "$\\overrightarrow{OC}$" in after_body
    # 幂等：再跑一遍不产生新改动。
    assert fix_book(BOOK_ID, storage=admin_storage)["blocks_fixed"] == 0
