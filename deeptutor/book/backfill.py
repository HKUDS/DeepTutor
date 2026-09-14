"""存量书增量补缺服务（P1-E D2）——能力已从 ``scripts/backfill_blocks.py`` 入 DT。

对照 ``page_planner._TEMPLATES_V2`` 检测每页缺失的生成块类型，通过
``BookEngine.insert_block`` 官方插入路径补产 —— 数据访问全部走既有 storage 层，
绝不直连 sqlite / 页面 JSON，不碰 engine 编译主链。检测逻辑与补产执行共用，
dry-run（:func:`plan_backfill`）零副作用。

规则（与 P1-B 脚本一致，此处为唯一真源）
----
* 页型模板：``_TEMPLATES_V2[page.content_type]``；OVERVIEW 页无模板 → 跳过。
* 学科门控：复用 ``page_planner._math_blocks_allowed`` 逻辑，非数学书剔除交互族。
* 长文骨架（SECTION/TEXT）不补：存量书已有 READING 原文。
* 生成器未注册的块类型不插（registry 查询为准）。
* 429 退避：指数退避重试，重试前删掉半成品 ERROR 壳，不留重复块。
* 断点续跑：每页完成即追加 ``<state-dir>/backfill-<book>.jsonl``，重跑跳过已完成页。
  服务层默认状态目录为数据卷绝对路径 ``<workspace>/pipeline-state/``。
* P4-B 停摆防线：单次 LLM 调用有兜底超时（``DEEPTUTOR_BACKFILL_LLM_TIMEOUT``，
  默认 300s）、并发槽获取有超时、连续失败达阈值熔断（
  ``DEEPTUTOR_BACKFILL_MAX_CONSECUTIVE_ERRORS``，默认 8）——挂死的 provider
  调用不再能占住槽位冻结批次；任务级 started/done/failed 事件与逐页成败
  都落状态文件，异常必须落日志，禁止静默吞。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any, Callable

from deeptutor.book.blocks.base import get_block_registry
from deeptutor.book.errors import BookPausedError
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    Chapter,
    Page,
)

logger = logging.getLogger(__name__)


# ``page_planner`` 是重依赖（api 导入边界测试要求保持冷态），延迟到真正做
# 缺失检测/学科门控时再导入。
def _page_planner():
    from deeptutor.book.agents import page_planner

    return page_planner


_MATH_BLOCK_TYPES: frozenset | None = None
_TEMPLATES_V2: dict | None = None


def _planner():
    """惰性解析 page_planner 常量（首次调用后缓存到模块级名字）。"""
    global _MATH_BLOCK_TYPES, _TEMPLATES_V2
    if _TEMPLATES_V2 is None:
        planner = _page_planner()
        _MATH_BLOCK_TYPES = planner._MATH_BLOCK_TYPES
        _TEMPLATES_V2 = planner._TEMPLATES_V2
    return _MATH_BLOCK_TYPES, _TEMPLATES_V2


def _subject_of(title: str) -> str:
    from deeptutor.learning.ingest_pipeline import _subject_of as _impl

    return _impl(title)


#: 断点续跑状态目录名（挂在数据卷 workspace 根下的绝对路径）。
STATE_DIR_NAME = "pipeline-state"
#: LLM 并发上限（任务书硬约束 ≤2）。
DEFAULT_CONCURRENCY = 2
#: 单块 429 退避重试次数。
DEFAULT_MAX_RETRIES = 3
#: 退避基数（秒），指数增长 5s → 10s → 20s。
DEFAULT_BACKOFF_SECONDS = 5.0
#: 单次 LLM 调用兜底超时（秒）。P4-B：doubao 过载窗口下无超时的调用会永久
#: 占住并发槽，整个批次静默冻结——任何一次 LLM 调用都必须有界。
DEFAULT_LLM_TIMEOUT_SECONDS = 300.0
#: LLM 调用超时环境变量（部署可调；生成器走 RAG + 长产出，默认给足 5 分钟）。
LLM_TIMEOUT_ENV = "DEEPTUTOR_BACKFILL_LLM_TIMEOUT"
#: 连续失败熔断阈值：连续 N 个块补产失败即中止批次（provider 整体不可用时
#: 不再把整本书逐块打满错误）。
DEFAULT_MAX_CONSECUTIVE_ERRORS = 8
#: 熔断阈值环境变量。
MAX_CONSECUTIVE_ERRORS_ENV = "DEEPTUTOR_BACKFILL_MAX_CONSECUTIVE_ERRORS"


def default_llm_timeout() -> float:
    """单次 LLM 调用兜底超时（秒），``DEEPTUTOR_BACKFILL_LLM_TIMEOUT`` 可覆盖。"""
    raw = os.getenv(LLM_TIMEOUT_ENV, "").strip()
    try:
        value = float(raw) if raw else DEFAULT_LLM_TIMEOUT_SECONDS
    except ValueError:
        logger.warning(
            "非法的 %s=%r，回退默认 %.0fs", LLM_TIMEOUT_ENV, raw, DEFAULT_LLM_TIMEOUT_SECONDS
        )
        value = DEFAULT_LLM_TIMEOUT_SECONDS
    return max(1.0, value)


def default_max_consecutive_errors() -> int:
    """连续失败熔断阈值，``DEEPTUTOR_BACKFILL_MAX_CONSECUTIVE_ERRORS`` 可覆盖。"""
    raw = os.getenv(MAX_CONSECUTIVE_ERRORS_ENV, "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_CONSECUTIVE_ERRORS
    except ValueError:
        logger.warning(
            "非法的 %s=%r，回退默认 %d",
            MAX_CONSECUTIVE_ERRORS_ENV,
            raw,
            DEFAULT_MAX_CONSECUTIVE_ERRORS,
        )
        value = DEFAULT_MAX_CONSECUTIVE_ERRORS
    return max(1, value)


def _slot_timeout(llm_timeout: float, max_retries: int, backoff_seconds: float) -> float:
    """并发槽获取超时：略高于单个块的极端占用时长（全部重试都打满超时）。

    每个块最多占槽 ``(max_retries + 1)`` 次调用 × 调用超时，加上重试间退避；
    超过该上界仍拿不到槽说明批次已死锁，等待方必须有界脱身（P4-B）。
    """
    attempts = max(1, max_retries + 1)
    backoff_total = sum(backoff_seconds * (2**i) for i in range(max_retries))
    return llm_timeout * attempts + backoff_total + 60.0


# 长文骨架：存量书已有 READING 原文块，不再补 LLM 长文（记 note 跳过）。
_PROSE_BLOCK_TYPES = frozenset({BlockType.SECTION, BlockType.TEXT})

# 视作"该类型已有内容"的块状态。PENDING/GENERATING 是欠着的工作，补了会重复。
_PRESENT_STATUSES = frozenset({BlockStatus.PENDING, BlockStatus.GENERATING, BlockStatus.READY})

# 各科均可产的补位块（不进 _TEMPLATES_V2，但生成器已就绪）。
_DEEP_DIVE_TYPE = BlockType.DEEP_DIVE
_ERROR_DIAGNOSIS_TYPE = BlockType.ERROR_DIAGNOSIS


def default_state_dir() -> Path:
    """断点状态目录：数据卷上的绝对路径 ``<workspace>/pipeline-state/``。

    通过 :class:`~deeptutor.services.path_service.PathService` 的 workspace 根
    解析（多用户/容器部署下即数据卷挂载点），不再依赖进程当前工作目录。
    """
    from deeptutor.book.storage import get_book_storage

    path_service = getattr(get_book_storage(), "path_service", None)
    if path_service is None:
        from deeptutor.services.path_service import get_path_service

        path_service = get_path_service()
    return Path(path_service.workspace_root) / STATE_DIR_NAME


# ─────────────────────────────────────────────────────────────────────────────
# 学科门控（复用 page_planner 逻辑）
# ─────────────────────────────────────────────────────────────────────────────


def effective_subject(chapter: Chapter, book: Book, *, subject_override: str = "") -> str:
    """Resolve the subject hint used for the math-block gate.

    章节自带的 ``subject`` / ``discipline`` extra 最可信（与 planner 同源）；
    否则回退书 metadata，再否则按书名推断（复用 ``ingest_pipeline._subject_of``，
    排除其兜底值"通用"）。返回空串表示实在拿不到学科信息，由调用方决定退路。
    """
    if subject_override.strip():
        return subject_override.strip()
    for attr in ("subject", "discipline"):
        value = str(getattr(chapter, attr, "") or "").strip()
        if value:
            return value
    metadata = book.metadata or {}
    value = str(metadata.get("subject") or "").strip()
    if value:
        return value
    inferred = _subject_of(book.title)
    return inferred if inferred and inferred != "通用" else ""


def math_blocks_allowed(chapter: Chapter, book: Book, *, subject_override: str = "") -> bool:
    """学科门控：非数学书剔除交互族。逻辑本体复用 ``_math_blocks_allowed``。"""
    subject = effective_subject(chapter, book, subject_override=subject_override)
    if not subject:
        # 拿不到学科信息时让书名自证（复用 planner 同一张非数学关键词表）：
        # 书名命中"英语/历史/语文…"即门控，否则沿用 planner 的 fail-open 放行。
        subject = book.title
    return _page_planner()._math_blocks_allowed(SimpleNamespace(subject=subject))


# ─────────────────────────────────────────────────────────────────────────────
# 缺失检测（纯函数，dry-run 与正式补产共用）
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PlanItem:
    """One block the page is missing and should get."""

    block_type: BlockType
    params: dict[str, Any]
    reason: str  # template | deep_dive | error_loop


@dataclass
class PagePlan:
    """检测结果：该页补什么、跳过什么、为什么。"""

    page_id: str
    page_title: str
    content_type: str
    skip: str = ""  # 非空 = 整页跳过的原因
    planned: list[PlanItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # 正式补产时回填的逐页成败（dry-run 恒为空）。
    inserted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _present_counts(page: Page) -> dict[BlockType, int]:
    counts: dict[BlockType, int] = {}
    for block in page.blocks:
        if block.status in _PRESENT_STATUSES:
            counts[block.type] = counts.get(block.type, 0) + 1
    return counts


def plan_page(
    page: Page,
    chapter: Chapter | None,
    book: Book,
    *,
    subject_override: str = "",
) -> PagePlan:
    """对照 ``_TEMPLATES_V2`` 该页型模板检测缺失的生成块。"""
    plan = PagePlan(
        page_id=page.id,
        page_title=page.title,
        content_type=page.content_type.value,
    )
    if chapter is None:
        plan.skip = "chapter_missing"
        return plan
    if page.parent_page_id:
        plan.skip = "deep_dive_subpage"
        return plan
    math_types, templates = _planner()
    template = templates.get(page.content_type)
    if template is None:
        # OVERVIEW 等无模板页：概览页本身就是确定性渲染的。
        plan.skip = "no_template"
        return plan
    if not any(block.status == BlockStatus.READY for block in page.blocks):
        # 没有任何 READY 块的页（纯空壳 / 中断残骸）归常规编译管线管，补产不掺和。
        plan.skip = "page_not_compiled"
        return plan

    math_allowed = math_blocks_allowed(chapter, book, subject_override=subject_override)
    registry = get_block_registry()
    present = _present_counts(page)

    for block_type, template_params in template:
        if block_type in _PROSE_BLOCK_TYPES:
            plan.notes.append(f"{block_type.value}: prose_backbone")
            continue
        if not math_allowed and block_type in math_types:
            plan.notes.append(f"{block_type.value}: subject_gate")
            continue
        if registry.get(block_type) is None:
            # 未注册生成器：insert 会留下永远 PENDING 的空壳，绝不插。
            plan.notes.append(f"{block_type.value}: no_generator")
            continue
        if present.get(block_type):
            plan.notes.append(f"{block_type.value}: already_present")
            continue
        params = {k: v for k, v in template_params.items() if k != "transition_in"}
        plan.planned.append(PlanItem(block_type, params, "template"))

    # 各科均可产的补位块：deep_dive（深挖卡）与 error_diagnosis（真实错题数据，
    # 无数据时生成器 BlockSkipped 静默剪块）。
    for block_type, reason in (
        (_DEEP_DIVE_TYPE, "deep_dive"),
        (_ERROR_DIAGNOSIS_TYPE, "error_loop"),
    ):
        if registry.get(block_type) is None:
            plan.notes.append(f"{block_type.value}: no_generator")
            continue
        if present.get(block_type):
            plan.notes.append(f"{block_type.value}: already_present")
            continue
        plan.planned.append(PlanItem(block_type, {}, reason))

    return plan


# ─────────────────────────────────────────────────────────────────────────────
# 断点续跑状态（pipeline-state/backfill-<book>.jsonl）
# ─────────────────────────────────────────────────────────────────────────────


def _state_path(state_dir: Path, book_id: str) -> Path:
    return state_dir / f"backfill-{book_id}.jsonl"


def load_done_page_ids(state_dir: Path, book_id: str) -> set[str]:
    path = _state_path(state_dir, book_id)
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("page_id"):
            done.add(str(record["page_id"]))
    return done


def append_state(
    state_dir: Path,
    book_id: str,
    *,
    page_id: str,
    page_title: str,
    inserted: list[str],
    skipped: list[str],
    errors: list[str],
    dry_run: bool,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "book_id": book_id,
        "page_id": page_id,
        "page_title": page_title,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
    }
    with _state_path(state_dir, book_id).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_task_event(
    state_dir: Path,
    book_id: str,
    *,
    event: str,
    task_id: str = "",
    error: str = "",
    **extra: Any,
) -> None:
    """任务级事件落状态文件（``event: task_started/task_done/task_failed``）。

    P4-B：任务级成败必须落盘可见，禁止只在内存里悄悄吞掉。记录不带
    ``page_id``，:func:`load_done_page_ids` 天然忽略它，页级 jsonl 格式不变。
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "book_id": book_id,
        "event": event,
        "task_id": task_id,
        "error": error,
    }
    record.update(extra)
    with _state_path(state_dir, book_id).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# 补产执行
# ─────────────────────────────────────────────────────────────────────────────


class _ErrorBreaker:
    """连续失败熔断：provider 整体不可用时中止批次，明确 failed 收场（P4-B）。

    ``threshold <= 0`` 视为不启用。``tripped`` 置位后各页协程在下一个块边界
    停手，未处理页不落页级断点记录，下次重跑幂等续补。
    """

    def __init__(self, threshold: int) -> None:
        self.threshold = threshold
        self.consecutive = 0
        self.tripped = False
        self.last_error = ""

    def record_success(self) -> None:
        self.consecutive = 0

    def record_failure(self, message: str) -> None:
        self.consecutive += 1
        self.last_error = message
        if self.threshold > 0 and self.consecutive >= self.threshold:
            self.tripped = True
            logger.error(
                "backfill 熔断：连续 %d 个块补产失败，中止批次（最后错误: %s）",
                self.consecutive,
                message[:200],
            )


async def _delete_stale_shells(engine, book_id: str, page_id: str, block_type: BlockType) -> None:
    """删掉超时中断留下的 PENDING/GENERATING 空壳。

    ``insert_block`` 先落壳再调生成器；调用被超时取消时壳已落盘，不删的话
    下次补产会按 ``already_present`` 幂等跳过，缺块永远补不上。
    """
    storage = getattr(engine, "storage", None)
    try:
        page = storage.load_page(book_id, page_id) if storage is not None else None
        if page is None:
            return
        for block in list(page.blocks):
            if block.type == block_type and block.status in (
                BlockStatus.PENDING,
                BlockStatus.GENERATING,
            ):
                await engine.delete_block(book_id=book_id, page_id=page_id, block_id=block.id)
    except Exception:  # noqa: BLE001 — 清理失败不阻断主流程
        logger.warning("backfill 清理 %s/%s 的 %s 空壳失败", book_id, page_id, block_type.value)


async def _insert_with_backoff(
    engine,
    book: Book,
    page_id: str,
    item: PlanItem,
    *,
    semaphore: asyncio.Semaphore,
    max_retries: int,
    backoff_seconds: float,
    llm_timeout: float,
    slot_timeout: float,
    breaker: _ErrorBreaker,
    log,
) -> str:
    """Insert one block, backing off (exponentially) on rate-limit failures.

    Returns ``ready`` / ``skipped`` / ``error``. A rate-limited block is dropped
    (its ERROR shell is deleted) before the retry so the page never keeps a
    half-written duplicate.

    P4-B 停摆防线：LLM 调用与并发槽获取都有超时——任何一次 ``await`` 都有界，
    挂死的 provider 调用不再能永久占住槽位冻结整个批次；每次成败都过熔断器。
    """
    registry = get_block_registry()
    if registry.get(item.block_type) is None:
        return "error"  # plan 阶段已拦，这里兜底。

    attempt = 0
    while True:
        block: Block | None = None
        failure: dict[str, Any] = {}
        # 并发槽获取带超时：槽位被挂死调用占住时，等待方要在有界时间内脱身。
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=slot_timeout)
        except asyncio.TimeoutError:
            message = f"并发槽 {slot_timeout:.0f}s 内未取得（批次疑似死锁）"
            log(f"[error] {page_id} {item.block_type.value} 获取并发槽超时")
            breaker.record_failure(message)
            return "error"
        try:
            try:
                block = await asyncio.wait_for(
                    engine.insert_block(
                        book_id=book.id,
                        page_id=page_id,
                        block_type=item.block_type,
                        params=dict(item.params),
                    ),
                    timeout=llm_timeout,
                )
            except asyncio.TimeoutError:
                failure = {
                    "kind": "timeout",
                    "retryable": False,
                    "message": f"LLM call timed out after {llm_timeout:.0f}s",
                }
                log(f"[warn] {page_id} {item.block_type.value} LLM 调用超时 {llm_timeout:.0f}s")
                await _delete_stale_shells(engine, book.id, page_id, item.block_type)
            except BookPausedError:
                log(f"[pause] {book.id} 已暂停，停止补产（BookPausedError）")
                return "paused"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — provider 层异常统一走退避
                failure = {"kind": "provider_error", "retryable": True, "message": str(exc)}
                log(f"[warn] {page_id} {item.block_type.value} insert raised: {exc}")
        finally:
            semaphore.release()
        if block is None and not failure:
            return "error"

        if block is not None:
            if block.status == BlockStatus.READY:
                breaker.record_success()
                return "ready"
            if block.status == BlockStatus.HIDDEN and (block.metadata or {}).get("skipped"):
                # BlockSkipped（如无错题数据）：块已被 compiler 剪掉，天然安全。
                breaker.record_success()
                return "skipped"
            failure = (block.metadata or {}).get("failure") or {}

        kind = str(failure.get("kind") or "unknown")
        if kind == "rate_limit" and attempt < max_retries:
            delay = backoff_seconds * (2**attempt)
            attempt += 1
            log(
                f"[backoff] {page_id} {item.block_type.value} 429 → {delay:.0f}s 后重试 {attempt}/{max_retries}"
            )
            if block is not None:
                try:
                    await engine.delete_block(book_id=book.id, page_id=page_id, block_id=block.id)
                except Exception:  # noqa: BLE001 — 删失败也不影响重试
                    pass
            await asyncio.sleep(delay)
            continue

        message = str(failure.get("message") or failure.get("kind") or "unknown failure")
        log(f"[error] {page_id} {item.block_type.value} 补产失败: {message[:200]}")
        breaker.record_failure(f"{page_id} {item.block_type.value}: {message}")
        return "error"


async def _process_page(
    engine,
    book: Book,
    page: Page,
    chapter: Chapter | None,
    *,
    dry_run: bool,
    subject_override: str,
    semaphore: asyncio.Semaphore,
    max_retries: int,
    backoff_seconds: float,
    llm_timeout: float,
    slot_timeout: float,
    breaker: _ErrorBreaker,
    state_dir: Path,
    resume: bool,
    log,
) -> PagePlan:
    plan = plan_page(page, chapter, book, subject_override=subject_override)
    if plan.skip:
        log(f"  [skip] {page.title or plan.page_id} → {plan.skip}")
        return plan

    if dry_run:
        wanted = ", ".join(item.block_type.value for item in plan.planned) or "(无缺失)"
        log(f"  [plan] {page.title or plan.page_id} → 补 {wanted}")
        for note in plan.notes:
            log(f"         - {note}")
        # dry-run 零副作用：连断点状态文件也不写，避免污染正式跑的续跑判断。
        return plan

    if resume and plan.page_id in load_done_page_ids(state_dir, book.id):
        log(f"  [resume] {page.title or plan.page_id} 已在断点状态中，跳过")
        return plan

    inserted: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    breaker_hit = False
    for item in plan.planned:
        if breaker.tripped:
            # 熔断已触发：本页剩余块不再补，页级断点也不写，重跑时幂等续补。
            plan.notes.append("circuit_breaker_open")
            breaker_hit = True
            break
        outcome = await _insert_with_backoff(
            engine,
            book,
            plan.page_id,
            item,
            semaphore=semaphore,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            llm_timeout=llm_timeout,
            slot_timeout=slot_timeout,
            breaker=breaker,
            log=log,
        )
        if outcome == "ready":
            inserted.append(item.block_type.value)
        elif outcome == "skipped":
            skipped.append(item.block_type.value)
        elif outcome == "paused":
            break
        else:
            errors.append(item.block_type.value)

    log(
        f"  [page] {page.title or plan.page_id} "
        f"补 {len(inserted)}/跳 {len(skipped)}/错 {len(errors)}"
    )
    plan.inserted, plan.skipped, plan.errors = inserted, skipped, errors
    if not breaker_hit:
        append_state(
            state_dir,
            book.id,
            page_id=plan.page_id,
            page_title=plan.page_title,
            inserted=inserted,
            skipped=skipped,
            errors=errors,
            dry_run=False,
        )
    return plan


def resolve_subject_overrides(raw_values: list[str]) -> tuple[str, dict[str, str]]:
    """Parse ``--subject`` entries into (global, per-book) overrides.

    每个条目要么是裸学科名（作用于本次全部书），要么是 ``书id=学科``（只作用于
    那本书）。例如 ``--subject 英语 --subject bk_123=数学``。
    """
    global_subject = ""
    per_book: dict[str, str] = {}
    for raw in raw_values:
        value = raw.strip()
        if not value:
            continue
        if "=" in value:
            book_id, _, subject = value.partition("=")
            if book_id.strip() and subject.strip():
                per_book[book_id.strip()] = subject.strip()
            continue
        global_subject = value
    return global_subject, per_book


async def run_book(
    engine,
    book: Book,
    *,
    dry_run: bool,
    subject_override: str = "",
    concurrency: int = DEFAULT_CONCURRENCY,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    state_dir: Path | None = None,
    resume: bool = True,
    limit_page: int | None = None,
    llm_timeout: float | None = None,
    max_consecutive_errors: int | None = None,
    log: Callable[[str], None] = lambda _msg: None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """对一本书逐页补产。返回统计。

    ``state_dir`` 缺省落数据卷绝对路径 ``<workspace>/pipeline-state/``；
    ``progress_cb`` 每页结束回调一次（dry-run 不回调），负载见
    :class:`BackfillJob` 的计数字段。

    P4-B：``llm_timeout`` 为单次 LLM 调用兜底超时（缺省读
    ``DEEPTUTOR_BACKFILL_LLM_TIMEOUT``，默认 300s）；``max_consecutive_errors``
    为连续失败熔断阈值（缺省读 ``DEEPTUTOR_BACKFILL_MAX_CONSECUTIVE_ERRORS``，
    默认 8）。熔断触发时批次以 ``status="failed"`` 收场。
    """
    state_dir = state_dir or default_state_dir()
    llm_timeout = default_llm_timeout() if llm_timeout is None else max(1.0, float(llm_timeout))
    breaker = _ErrorBreaker(
        default_max_consecutive_errors()
        if max_consecutive_errors is None
        else max_consecutive_errors
    )
    slot_timeout = _slot_timeout(llm_timeout, max_retries, backoff_seconds)
    spine = engine.load_spine(book.id)
    if spine is None:
        log(f"[error] 书 {book.id} 无 spine，跳过")
        return {"book_id": book.id, "status": "no_spine", "pages": 0, "planned": 0}
    chapters = {chapter.id: chapter for chapter in spine.chapters}
    pages = engine.list_pages(book.id)
    if limit_page is not None:
        pages = pages[:limit_page]

    log(f"== 书 {book.title} ({book.id}) status={book.status.value} pages={len(pages)} ==")
    semaphore = asyncio.Semaphore(max(1, concurrency))
    if not dry_run and resume:
        log(f"  断点续跑：已完成 {len(load_done_page_ids(state_dir, book.id))} 页将跳过")

    done = 0
    plans: list[PagePlan] = []

    async def _tracked(page: Page) -> PagePlan:
        nonlocal done
        plan = await _process_page(
            engine,
            book,
            page,
            chapters.get(page.chapter_id),
            dry_run=dry_run,
            subject_override=subject_override,
            semaphore=semaphore,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            llm_timeout=llm_timeout,
            slot_timeout=slot_timeout,
            breaker=breaker,
            state_dir=state_dir,
            resume=resume,
            log=log,
        )
        done += 1
        if progress_cb is not None and not dry_run:
            progress_cb(
                {
                    "stage": "running",
                    "pages_total": len(pages),
                    "pages_done": done,
                    "blocks_inserted": sum(len(p.inserted) for p in [*plans, plan]),
                    "blocks_skipped": sum(len(p.skipped) for p in [*plans, plan]),
                    "blocks_errors": sum(len(p.errors) for p in [*plans, plan]),
                }
            )
        return plan

    plans = await asyncio.gather(*(_tracked(page) for page in pages))

    summary = {
        "book_id": book.id,
        "title": book.title,
        "status": "dry_run" if dry_run else "ok",
        "pages": len(plans),
        "pages_planned": sum(1 for p in plans if p.planned and not p.skip),
        "pages_skipped": sum(1 for p in plans if p.skip),
        "blocks_planned": sum(len(p.planned) for p in plans),
        "blocks_inserted": sum(len(p.inserted) for p in plans),
        "blocks_skipped": sum(len(p.skipped) for p in plans),
        "blocks_errors": sum(len(p.errors) for p in plans),
        "notes": sorted({note for p in plans for note in p.notes}),
    }
    if breaker.tripped and not dry_run:
        summary["status"] = "failed"
        summary["aborted"] = True
        summary["error"] = (
            f"连续 {breaker.consecutive} 个块补产失败，已熔断中止批次: {breaker.last_error[:200]}"
        )
    log(
        f"== 小结 {book.title}: 页 {summary['pages']} / 待补页 {summary['pages_planned']} "
        f"/ 待补块 {summary['blocks_planned']} / 整页跳过 {summary['pages_skipped']} =="
    )
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# 服务层入口（API 端点用）：计划 / 后台补产 / 进度登记
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BackfillJob:
    """一次补产任务的进度登记（单事件循环内读写，无需加锁）。

    P4-B：``started_at`` / ``updated_at`` 让"冻结的 running"可辨（心跳时间戳
    停走即停摆）；``last_message`` 保存最近一次进展或错误；``task_status`` 把
    stage 归一为 running/done/failed，供状态端点直接消费。
    """

    book_id: str
    task_id: str = ""
    stage: str = "pending"  # pending | running | completed | failed | error
    pages_total: int = 0
    pages_done: int = 0
    blocks_planned: int = 0
    blocks_inserted: int = 0
    blocks_skipped: int = 0
    blocks_errors: int = 0
    error: str = ""
    started_at: str = ""
    updated_at: str = ""
    last_message: str = ""

    _TASK_STATUS_BY_STAGE = {
        "pending": "running",
        "running": "running",
        "completed": "done",
        "failed": "failed",
        "error": "failed",
    }

    def _touch(self) -> None:
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def mark_running(self, task_id: str = "") -> None:
        self.stage = "running"
        if task_id:
            self.task_id = task_id
        self.error = ""
        self.last_message = ""
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._touch()

    def mark_failed(self, message: str) -> None:
        """线程外崩溃兜底：job 必须脱离 running，否则同书被互斥 409 永久锁死。"""
        self.stage = "error"
        self.error = message
        self.last_message = message
        self._touch()
        logger.error("backfill job %s 失败: %s", self.book_id, message)

    def snapshot(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "task_id": self.task_id,
            "stage": self.stage,
            "task_status": self._TASK_STATUS_BY_STAGE.get(self.stage, "failed"),
            "pages_total": self.pages_total,
            "pages_done": self.pages_done,
            "blocks_planned": self.blocks_planned,
            "blocks_inserted": self.blocks_inserted,
            "blocks_skipped": self.blocks_skipped,
            "blocks_errors": self.blocks_errors,
            "error": self.error,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "last_message": self.last_message,
        }


#: 运行中的补产任务登记（book_id → job），状态端点的进度来源。
_JOBS: dict[str, BackfillJob] = {}


def get_backfill_job(book_id: str) -> BackfillJob | None:
    return _JOBS.get(book_id)


def fail_backfill_job(book_id: str, message: str) -> None:
    """崩溃兜底：把登记（或新建）的 job 拉离 running，防止同书互斥永久锁死。"""
    job = _JOBS.setdefault(book_id, BackfillJob(book_id=book_id))
    job.mark_failed(message)


def plan_backfill(
    book_id: str,
    *,
    subject_override: str = "",
    limit_page: int | None = None,
) -> dict[str, Any]:
    """检测 ``book_id`` 缺失的生成块，返回补缺计划（零写入、零 LLM 调用）。

    与正式补产共用 ``plan_page`` 检测逻辑；不触引擎写路径，也不落断点状态。
    """
    from deeptutor.book.engine import get_book_engine

    engine = get_book_engine()
    book = engine.load_book(book_id)
    if book is None:
        raise KeyError(f"Book not found: {book_id}")
    spine = engine.load_spine(book_id)
    if spine is None:
        return {
            "book_id": book_id,
            "title": book.title,
            "status": "no_spine",
            "pages": 0,
            "pages_planned": 0,
            "pages_skipped": 0,
            "blocks_planned": 0,
            "notes": [],
            "page_plans": [],
        }
    chapters = {chapter.id: chapter for chapter in spine.chapters}
    pages = engine.list_pages(book_id)
    if limit_page is not None:
        pages = pages[:limit_page]

    plans = [
        plan_page(page, chapters.get(page.chapter_id), book, subject_override=subject_override)
        for page in pages
    ]
    return {
        "book_id": book.id,
        "title": book.title,
        "status": "dry_run",
        "pages": len(plans),
        "pages_planned": sum(1 for p in plans if p.planned and not p.skip),
        "pages_skipped": sum(1 for p in plans if p.skip),
        "blocks_planned": sum(len(p.planned) for p in plans),
        "notes": sorted({note for p in plans for note in p.notes}),
        "page_plans": [
            {
                "page_id": p.page_id,
                "page_title": p.page_title,
                "content_type": p.content_type,
                "skip": p.skip,
                "planned": [
                    {
                        "block_type": item.block_type.value,
                        "reason": item.reason,
                    }
                    for item in p.planned
                ],
                "notes": list(p.notes),
            }
            for p in plans
        ],
    }


def run_backfill(
    book_id: str,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    limit_page: int | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    subject_override: str = "",
    state_dir: Path | None = None,
    task_id: str = "",
    llm_timeout: float | None = None,
    max_consecutive_errors: int | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> BackfillJob:
    """对存量书跑一次增量补缺（同步阻塞，调用方负责放入后台任务）。

    走 ``BookEngine.insert_block`` 官方路径；断点状态写数据卷
    ``pipeline-state/``；429 指数退避。进度登记到 :data:`_JOBS`，
    供状态端点查询。

    P4-B：每次 LLM 调用带 ``llm_timeout`` 兜底超时；连续失败达
    ``max_consecutive_errors`` 熔断收场（``stage="failed"``）；任务级
    started/done/failed 事件落状态文件；异常必须落日志，禁止静默吞。
    """
    from deeptutor.book.engine import get_book_engine

    state_dir = state_dir or default_state_dir()
    job = _JOBS.setdefault(book_id, BackfillJob(book_id=book_id))
    job.mark_running(task_id)
    logger.info("backfill task %s 开始（book=%s）", task_id or "-", book_id)
    engine = get_book_engine()
    book = engine.load_book(book_id)
    if book is None:
        job.stage = "error"
        job.error = f"Book not found: {book_id}"
        job.last_message = job.error
        job._touch()
        logger.error("backfill task %s 失败: %s", task_id or "-", job.error)
        append_task_event(state_dir, book_id, event="task_failed", task_id=task_id, error=job.error)
        return job

    append_task_event(state_dir, book_id, event="task_started", task_id=task_id)

    def _progress(payload: dict[str, Any]) -> None:
        job.pages_total = int(payload.get("pages_total", 0))
        job.pages_done = int(payload.get("pages_done", 0))
        job.blocks_inserted = int(payload.get("blocks_inserted", 0))
        job.blocks_skipped = int(payload.get("blocks_skipped", 0))
        job.blocks_errors = int(payload.get("blocks_errors", 0))
        job.last_message = (
            f"页 {job.pages_done}/{job.pages_total} · 补 {job.blocks_inserted}"
            f"/跳 {job.blocks_skipped}/错 {job.blocks_errors}"
        )
        job._touch()
        if progress_cb is not None:
            progress_cb(dict(payload))

    try:
        summary = asyncio.run(
            run_book(
                engine,
                book,
                dry_run=False,
                subject_override=subject_override,
                concurrency=concurrency,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
                state_dir=state_dir,
                resume=True,
                limit_page=limit_page,
                llm_timeout=llm_timeout,
                max_consecutive_errors=max_consecutive_errors,
                progress_cb=_progress,
            )
        )
    except Exception as exc:  # noqa: BLE001 — 后台任务失败要落在状态里
        logger.exception("backfill task %s 异常中止（book=%s）", task_id or "-", book_id)
        job.stage = "error"
        job.error = str(exc)
        job.last_message = str(exc)
        job._touch()
        append_task_event(state_dir, book_id, event="task_failed", task_id=task_id, error=str(exc))
        return job

    job.blocks_planned = int(summary.get("blocks_planned", 0))
    job.pages_total = int(summary.get("pages", 0))
    job.pages_done = int(summary.get("pages", 0))
    job.blocks_inserted = int(summary.get("blocks_inserted", 0))
    job.blocks_skipped = int(summary.get("blocks_skipped", 0))
    job.blocks_errors = int(summary.get("blocks_errors", 0))
    if summary.get("status") == "failed":
        # 熔断收场：批次明确 failed，而不是伪装成正常完成。
        job.stage = "failed"
        job.error = str(summary.get("error") or "backfill aborted")
        job.last_message = job.error
        logger.error("backfill task %s 熔断收场: %s", task_id or "-", job.error)
        append_task_event(state_dir, book_id, event="task_failed", task_id=task_id, error=job.error)
    else:
        job.stage = "completed"
        job.last_message = (
            f"页 {job.pages_done}/{job.pages_total} · 补 {job.blocks_inserted}"
            f"/跳 {job.blocks_skipped}/错 {job.blocks_errors}"
        )
        append_task_event(
            state_dir,
            book_id,
            event="task_done",
            task_id=task_id,
            blocks_inserted=job.blocks_inserted,
            blocks_skipped=job.blocks_skipped,
            blocks_errors=job.blocks_errors,
        )
    job._touch()
    return job
