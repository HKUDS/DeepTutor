"""P1-E D2 存量书增量补缺服务层：缺失检测 / dry-run 零写入 / BlockSkipped / 断点续跑.

mock 方式移植自 ``tests/book/test_backfill_blocks.py``（P1-B 脚本测试）：
全部 mock 书页结构，不依赖真实生产数据、不调真实 LLM（生成器被替身替换）。
服务层单一真源：``deeptutor/book/backfill.py``。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.book import backfill as backfill_module
from deeptutor.book.blocks.base import BlockSkipped, get_block_registry
from deeptutor.book.engine import BookEngine
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    Chapter,
    ContentType,
    Page,
    Spine,
)
from deeptutor.services.path_service import PathService


class FakeBookStorage:
    """只实现补产服务会触到的读/写面；save_page 计数用于零写入断言。"""

    def __init__(self, books: list[Book], spines: list[Spine], pages: list[Page]) -> None:
        self.books = {book.id: book for book in books}
        self.spines = {spine.book_id: spine for spine in spines}
        self.pages: dict[str, Page] = {page.id: page for page in pages}
        self.save_page_calls = 0

    def list_book_ids(self) -> list[str]:
        return list(self.books)

    def load_book(self, book_id: str) -> Book | None:
        return self.books.get(book_id)

    def load_spine(self, book_id: str) -> Spine | None:
        return self.spines.get(book_id)

    def list_pages(self, book_id: str) -> list[Page]:
        return sorted(
            (p for p in self.pages.values() if p.book_id == book_id),
            key=lambda p: (p.order, p.created_at),
        )

    def load_page(self, book_id: str, page_id: str) -> Page | None:
        return self.pages.get(page_id)

    def save_page(self, page: Page) -> None:
        self.save_page_calls += 1
        self.pages[page.id] = page

    def append_log(self, book_id: str, message: str, op: str = "info") -> None:
        pass


def _book(book_id: str, title: str, *, subject: str | None = None) -> Book:
    metadata = {"subject": subject} if subject else {}
    return Book(id=book_id, title=title, language="zh", metadata=metadata)


def _reading_page(book_id: str, chapter: Chapter) -> Page:
    page = Page(
        id=f"pg-{chapter.id}",
        book_id=book_id,
        chapter_id=chapter.id,
        title=chapter.title,
        content_type=chapter.content_type,
        order=chapter.order,
    )
    page.blocks = [
        Block(type=BlockType.READING, status=BlockStatus.READY, payload={"body": "教材原文……"})
    ]
    return page


_MATH_CHAPTER = Chapter(
    id="ch-math-1", title="数列的概念", content_type=ContentType.THEORY, summary="等差与等比数列。"
)


def _engine(books, spines, pages) -> tuple[Any, FakeBookStorage]:
    storage = FakeBookStorage(books, spines, pages)
    engine = BookEngine(storage=storage)
    return engine, storage


def _patch_engine(monkeypatch: pytest.MonkeyPatch, engine: Any) -> None:
    """服务层经 ``deeptutor.book.engine.get_book_engine`` 取引擎（调用时才解析）。"""
    import deeptutor.book.engine as engine_module

    monkeypatch.setattr(engine_module, "get_book_engine", lambda: engine)


def _stub_all_generators(
    monkeypatch: pytest.MonkeyPatch, skip_error_diagnosis: bool = False
) -> None:
    registry = get_block_registry()

    def make_ready():
        async def _generate(_ctx):
            return {"stub": True}, [], {}

        return _generate

    def make_skip():
        async def _generate(_ctx):
            raise BlockSkipped(
                "No real error data recorded for this book; skipping error_diagnosis."
            )

        return _generate

    for block_type in registry.types():
        generator = registry.get(block_type)
        assert generator is not None
        if skip_error_diagnosis and block_type == BlockType.ERROR_DIAGNOSIS:
            monkeypatch.setattr(generator, "_generate", make_skip())
        else:
            monkeypatch.setattr(generator, "_generate", make_ready())


# ─────────────────────────────────────────────────────────────────────────────
# plan_backfill：缺失检测正确性 + dry-run 零写入
# ─────────────────────────────────────────────────────────────────────────────


def test_plan_backfill_lists_missing_blocks_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = _book("bk-svc-1", "高中数学人教A版2019-选择性必修第二册", subject="数学")
    page = _reading_page(book.id, _MATH_CHAPTER)
    engine, storage = _engine([book], [Spine(book_id=book.id, chapters=[_MATH_CHAPTER])], [page])
    _patch_engine(monkeypatch, engine)

    plan = backfill_module.plan_backfill(book.id)

    assert plan["status"] == "dry_run"
    assert plan["pages"] == 1
    assert plan["blocks_planned"] > 0
    planned_types = {"quiz", "callout", "flash_cards", "retrieval_practice", "deep_dive"}
    planned_in_plan = {item["block_type"] for pp in plan["page_plans"] for item in pp["planned"]}
    assert planned_types & planned_in_plan
    # dry-run 零写入：页面无新块、不触 storage 写路径。
    assert storage.save_page_calls == 0
    assert len(page.blocks) == 1


def test_plan_backfill_unknown_book_raises_keyerror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _storage = _engine([], [], [])
    _patch_engine(monkeypatch, engine)

    with pytest.raises(KeyError):
        backfill_module.plan_backfill("bk-missing")


# ─────────────────────────────────────────────────────────────────────────────
# run_backfill：insert_block 官方路径 / BlockSkipped 不中断 / 进度回调 / 断点续跑
# ─────────────────────────────────────────────────────────────────────────────


def test_run_backfill_inserts_blocks_and_reports_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_all_generators(monkeypatch)
    monkeypatch.setattr(backfill_module, "_JOBS", {})
    book = _book("bk-svc-run", "某书")
    page = _reading_page(book.id, _MATH_CHAPTER)
    engine, storage = _engine([book], [Spine(book_id=book.id, chapters=[_MATH_CHAPTER])], [page])
    _patch_engine(monkeypatch, engine)

    progress: list[dict[str, Any]] = []

    job = backfill_module.run_backfill(book.id, state_dir=tmp_path, progress_cb=progress.append)

    assert job.stage == "completed"
    assert job.pages_total == 1 and job.pages_done == 1
    assert job.blocks_planned > 0
    assert job.blocks_inserted > 0
    assert job.blocks_errors == 0
    assert progress and progress[-1]["pages_done"] == 1
    # insert_block 官方路径 → storage.save_page 真实落盘。
    assert storage.save_page_calls >= 1
    stored = storage.pages[page.id]
    inserted_types = {block.type for block in stored.blocks}
    assert {BlockType.QUIZ, BlockType.CALLOUT, BlockType.DEEP_DIVE} <= inserted_types
    # 断点状态写到指定目录。
    assert (tmp_path / f"backfill-{book.id}.jsonl").exists()


def test_run_backfill_block_skipped_does_not_break_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_all_generators(monkeypatch, skip_error_diagnosis=True)
    monkeypatch.setattr(backfill_module, "_JOBS", {})
    book = _book("bk-svc-skip", "某书")
    page = _reading_page(book.id, _MATH_CHAPTER)
    engine, storage = _engine([book], [Spine(book_id=book.id, chapters=[_MATH_CHAPTER])], [page])
    _patch_engine(monkeypatch, engine)

    job = backfill_module.run_backfill(book.id, state_dir=tmp_path)

    assert job.stage == "completed"
    assert job.blocks_skipped == 1
    assert job.blocks_inserted > 0
    # 被跳过的块已被 compiler 剪掉，不留空壳。
    stored = storage.pages[page.id]
    assert not any(block.type == BlockType.ERROR_DIAGNOSIS for block in stored.blocks)


def test_run_backfill_resumes_from_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_all_generators(monkeypatch)
    monkeypatch.setattr(backfill_module, "_JOBS", {})
    book = _book("bk-svc-resume", "某书")
    page = _reading_page(book.id, _MATH_CHAPTER)
    engine, storage = _engine([book], [Spine(book_id=book.id, chapters=[_MATH_CHAPTER])], [page])
    _patch_engine(monkeypatch, engine)
    (tmp_path / f"backfill-{book.id}.jsonl").write_text(
        json.dumps({"page_id": page.id, "inserted": ["quiz"]}) + "\n", encoding="utf-8"
    )

    job = backfill_module.run_backfill(book.id, state_dir=tmp_path)

    # 断点命中：零写入，任务照常完成。
    assert job.stage == "completed"
    assert storage.save_page_calls == 0
    assert job.blocks_inserted == 0


def test_run_backfill_unknown_book_marks_job_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backfill_module, "_JOBS", {})
    engine, _storage = _engine([], [], [])
    _patch_engine(monkeypatch, engine)

    job = backfill_module.run_backfill("bk-missing", state_dir=tmp_path)

    assert job.stage == "error"
    assert "bk-missing" in job.error


def test_default_state_dir_is_data_volume_pipeline_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """断点状态默认写数据卷绝对路径 ``<workspace>/pipeline-state/``。"""
    service = PathService(workspace_root=tmp_path / "data")

    class _StubStorage:
        path_service = service

    import deeptutor.book.storage as storage_module

    monkeypatch.setattr(storage_module, "get_book_storage", lambda: _StubStorage())

    state_dir = backfill_module.default_state_dir()

    assert state_dir == tmp_path / "data" / "pipeline-state"
    assert state_dir.is_absolute()


# ─────────────────────────────────────────────────────────────────────────────
# P4-B 停摆修复：LLM 挂死 / 全挂场景必须有界收场，禁止 started-但不干活
# ─────────────────────────────────────────────────────────────────────────────


def _patch_engine_hung_generators(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有生成器的 LLM 调用永久阻塞（模拟 doubao 过载窗口的挂死连接）。"""
    registry = get_block_registry()

    async def _hang(_ctx) -> None:
        await asyncio.Event().wait()  # 永不 set：模拟无响应的 LLM 调用

    for block_type in registry.types():
        generator = registry.get(block_type)
        assert generator is not None
        monkeypatch.setattr(generator, "_generate", _hang)


def test_run_backfill_hung_llm_call_terminates_and_leaves_visible_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复现 P4-B：LLM 调用永久挂死时任务必须以失败收场，状态文件可见，不留空壳。"""
    _patch_engine_hung_generators(monkeypatch)
    monkeypatch.setattr(backfill_module, "_JOBS", {})
    book = _book("bk-svc-hang", "某书")
    page = _reading_page(book.id, _MATH_CHAPTER)
    engine, storage = _engine([book], [Spine(book_id=book.id, chapters=[_MATH_CHAPTER])], [page])
    _patch_engine(monkeypatch, engine)

    job = backfill_module.run_backfill(
        book.id,
        state_dir=tmp_path,
        llm_timeout=0.2,
        max_consecutive_errors=2,
    )

    # 有界收场：批次以 failed 收场（熔断），而不是永远 running。
    assert job.stage == "failed"
    assert "timeout" in (job.error or "").lower() or "timed out" in (job.error or "").lower()
    # 状态文件可见：任务级事件落盘（task_failed）。
    state_text = (tmp_path / f"backfill-{book.id}.jsonl").read_text(encoding="utf-8")
    assert '"event": "task_failed"' in state_text or '"event":"task_failed"' in state_text
    # 不留半成品壳：超时清理掉 PENDING/GENERATING 空壳，重跑可幂等补产。
    stored = storage.pages[page.id]
    assert not any(
        block.status in (BlockStatus.PENDING, BlockStatus.GENERATING) for block in stored.blocks
    )


def test_run_backfill_all_provider_errors_fail_batch_via_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复现 P4-B：provider 持续报错时批次熔断为 failed，任务事件落状态文件。"""
    registry = get_block_registry()

    def make_fail():
        async def _fail(_ctx):
            raise Exception("doubao server overloaded, connection reset by peer")

        return _fail

    for block_type in registry.types():
        generator = registry.get(block_type)
        assert generator is not None
        monkeypatch.setattr(generator, "_generate", make_fail())

    monkeypatch.setattr(backfill_module, "_JOBS", {})
    book = _book("bk-svc-alldown", "某书")
    page = _reading_page(book.id, _MATH_CHAPTER)
    engine, _storage = _engine([book], [Spine(book_id=book.id, chapters=[_MATH_CHAPTER])], [page])
    _patch_engine(monkeypatch, engine)

    job = backfill_module.run_backfill(
        book.id,
        state_dir=tmp_path,
        max_consecutive_errors=2,
        backoff_seconds=0.0,
    )

    assert job.stage == "failed"
    assert job.error
    state_text = (tmp_path / f"backfill-{book.id}.jsonl").read_text(encoding="utf-8")
    assert '"event": "task_failed"' in state_text or '"event":"task_failed"' in state_text
