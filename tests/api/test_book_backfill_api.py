"""P1-E D2 存量书增量补缺端点：路由注册 / 401 门 / dry-run 返回计划 / 后台任务."""

from __future__ import annotations

import time

from fastapi import FastAPI
from starlette.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import book as book_router
from deeptutor.book import backfill as backfill_module
import deeptutor.book.engine as engine_module
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    ContentType,
    Page,
    PageStatus,
    Spine,
)
import deeptutor.book.storage as storage_module
from deeptutor.services.path_service import PathService


class _StubBookEngine:
    def __init__(self, storage: storage_module.BookStorage) -> None:
        self.storage = storage

    def load_book(self, book_id: str) -> Book | None:
        return self.storage.load_book(book_id)

    def load_spine(self, book_id: str):
        return self.storage.load_spine(book_id)

    def list_pages(self, book_id: str) -> list[Page]:
        return self.storage.list_pages(book_id)


def _new_client(tmp_path, monkeypatch) -> tuple[TestClient, storage_module.BookStorage]:
    service = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(storage_module, "get_path_service", lambda: service)
    storage_module._storages.clear()
    storage = storage_module.get_book_storage()

    stub = _StubBookEngine(storage)
    # 端点书解析走 book_router.get_book_engine；服务层引擎也指向同一替身。
    monkeypatch.setattr(book_router, "get_book_engine", lambda: stub)
    monkeypatch.setattr(engine_module, "get_book_engine", lambda: stub)
    monkeypatch.setattr(backfill_module, "_JOBS", {})

    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")
    return TestClient(app), storage


def _seed_compiled_math_book(storage: storage_module.BookStorage, book_id: str) -> Page:
    """一本已编译的数学书：一个 THEORY 页，只有 READING 原文块。"""
    storage.save_book(
        Book(id=book_id, title="高中数学人教A版2019-选择性必修第二册", metadata={"subject": "数学"})
    )
    storage.save_spine(
        Spine(
            book_id=book_id,
            chapters=[
                _chapter("ch_1", "数列的概念"),
            ],
        )
    )
    page = Page(
        id="pg_1",
        book_id=book_id,
        chapter_id="ch_1",
        title="数列的概念",
        content_type=ContentType.THEORY,
        status=PageStatus.READY,
    )
    page.blocks = [Block(type=BlockType.READING, status=BlockStatus.READY, payload={"body": "x"})]
    storage.save_page(page)
    return page


def _chapter(chapter_id: str, title: str):
    from deeptutor.book.models import Chapter

    return Chapter(id=chapter_id, title=title, content_type=ContentType.THEORY)


def test_backfill_routes_are_registered() -> None:
    # FastAPI 0.141 惰性挂载 include 的路由，注册断言直接查 router 自身路由表。
    paths = {route.path for route in book_router.router.routes}
    assert "/books/{book_id}/backfill-blocks" in paths
    assert "/books/{book_id}/backfill-blocks/status" in paths


def test_backfill_endpoints_require_admin_or_teacher(tmp_path, monkeypatch) -> None:
    client, _storage = _new_client(tmp_path, monkeypatch)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)

    assert client.post("/api/books/bk_x/backfill-blocks", json={}).status_code == 401
    assert client.get("/api/books/bk_x/backfill-blocks/status").status_code == 401


def test_backfill_dry_run_returns_plan_without_writes(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_dry_run_api"
    page = _seed_compiled_math_book(storage, book_id)

    response = client.post(f"/api/books/{book_id}/backfill-blocks", json={"dry_run": True})

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    plan = body["plan"]
    assert plan["status"] == "dry_run"
    assert plan["blocks_planned"] > 0
    assert any(item["planned"] for item in plan["page_plans"])
    # 零写入：页面块未被改动。
    assert len(storage.load_page(book_id, "pg_1").blocks) == 1


def test_backfill_start_returns_task_id_and_status_tracks_job(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_bg_api"
    storage.save_book(Book(id=book_id, title="某书"))

    captured: dict = {}

    def fake_run_backfill(book_id: str, **kwargs):
        captured["book_id"] = book_id
        captured["kwargs"] = kwargs
        job = backfill_module.BackfillJob(
            book_id=book_id, task_id=kwargs.get("task_id", ""), stage="completed", pages_done=3
        )
        # 真服务层会登记进度；替身同样登记，状态端点才有进度可查。
        backfill_module._JOBS[book_id] = job
        return job

    monkeypatch.setattr(book_router, "run_backfill", fake_run_backfill)

    response = client.post(
        f"/api/books/{book_id}/backfill-blocks", json={"dry_run": False, "limit_page": 5}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    assert body["task_id"].startswith("book_backfill_")
    assert body["status"] == "started"
    # 后台任务排空后，服务层参数被正确透传，任务状态落为 completed。
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not captured:
        time.sleep(0.05)
    assert captured["book_id"] == book_id
    assert captured["kwargs"]["limit_page"] == 5
    assert captured["kwargs"]["concurrency"] == 2

    status = client.get(f"/api/books/{book_id}/backfill-blocks/status")
    assert status.status_code == 200
    assert status.json()["stage"] == "completed"
    assert status.json()["pages_done"] == 3


def test_backfill_status_reports_idle_for_untouched_book(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    storage.save_book(Book(id="bk_idle", title="某书"))

    response = client.get("/api/books/bk_idle/backfill-blocks/status")

    assert response.status_code == 200
    assert response.json() == {"book_id": "bk_idle", "stage": "idle"}


def test_backfill_rejects_duplicate_running_job(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_dup"
    storage.save_book(Book(id=book_id, title="某书"))
    running_job = backfill_module.BackfillJob(book_id=book_id, stage="running")
    running_job.task_id = "book_backfill_20260909_010101_abcd1234"
    monkeypatch.setattr(
        backfill_module,
        "_JOBS",
        {book_id: running_job},
    )

    response = client.post(f"/api/books/{book_id}/backfill-blocks", json={"dry_run": False})

    # P4-B：互斥语义要明确——冲突响应必须带在跑任务的 task_id 与状态，不误导。
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "backfill_running"
    assert detail["task_id"] == "book_backfill_20260909_010101_abcd1234"
    assert detail["task_status"] == "running"


def test_backfill_worker_crash_marks_job_failed_not_running_forever(tmp_path, monkeypatch) -> None:
    """P4-B：后台线程崩溃不能让 job 永远停在 running（否则同书被 409 永久锁死）。"""
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_crash"
    storage.save_book(Book(id=book_id, title="某书"))

    def exploding_run_backfill(book_id: str, **kwargs):
        raise RuntimeError("thread pool exploded")

    monkeypatch.setattr(book_router, "run_backfill", exploding_run_backfill)

    response = client.post(f"/api/books/{book_id}/backfill-blocks", json={"dry_run": False})
    assert response.status_code == 200

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = client.get(f"/api/books/{book_id}/backfill-blocks/status").json()
        if status.get("stage") != "running":
            break
        time.sleep(0.05)

    # 异常必须可见：状态端点反映 failed + 最近错误，而不是永远 running。
    assert status["stage"] == "error"
    assert "thread pool exploded" in status["error"]
    assert status["task_status"] == "failed"


def test_backfill_status_reports_task_status_and_last_error(tmp_path, monkeypatch) -> None:
    """P4-B：GET status 补 task 状态（running/failed/done）与最近错误。"""
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_status"
    storage.save_book(Book(id=book_id, title="某书"))

    def failing_run_backfill(book_id: str, **kwargs):
        job = backfill_module.BackfillJob(
            book_id=book_id, task_id=kwargs.get("task_id", ""), stage="failed"
        )
        job.error = "LLM call timed out after 300s"
        backfill_module._JOBS[book_id] = job
        return job

    monkeypatch.setattr(book_router, "run_backfill", failing_run_backfill)

    client.post(f"/api/books/{book_id}/backfill-blocks", json={"dry_run": False})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = client.get(f"/api/books/{book_id}/backfill-blocks/status").json()
        if status.get("task_status") == "failed":
            break
        time.sleep(0.05)

    assert status["task_status"] == "failed"
    assert "timed out" in status["error"]


def test_backfill_unknown_book_returns_404(tmp_path, monkeypatch) -> None:
    client, _storage = _new_client(tmp_path, monkeypatch)

    assert (
        client.post("/api/books/bk_ghost/backfill-blocks", json={"dry_run": True}).status_code
        == 404
    )
    assert client.get("/api/books/bk_ghost/backfill-blocks/status").status_code == 404
