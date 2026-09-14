""" "素材处理管线" API Router — 教师自助上传全自动化（P2 v1）.

把解析→建结构→生成题库→挂载串成一条异步管线。状态机诚实：每段
``queued/running/done/failed/skipped``，单段失败让后续段 skipped，支持单段
重试。核心编排在 :mod:`deeptutor.learning.ingest_pipeline`（JSON 文件仓 +
后台线程，copy_context 传播当前用户，故 KB 解析与学习仓读写与请求发起者同权）。

三个端点（前缀 ``/api/ingest-pipeline``，全部 require_admin_or_teacher）：

* ``POST ""``            {kb_name, book_id} → 建 run，后台顺次跑四段
* ``GET  ""``            ?kb_name=&book_id= → 最近 run 的状态全景
* ``POST "/{run_id}/retry"`` {stage}        → 重试指定段
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_admin_or_teacher
from deeptutor.learning import ingest_pipeline as pipe
from deeptutor.services.auth import TokenPayload

logger = logging.getLogger(__name__)

router = APIRouter()

#: 合法 stage 名（与编排器 STAGE_ORDER 一致，做白名单校验）。
_VALID_STAGES = set(pipe.STAGE_ORDER)


class StartRequest(BaseModel):
    kb_name: str = Field(min_length=1, max_length=200)
    book_id: str = Field(min_length=1, max_length=200)


class RetryRequest(BaseModel):
    stage: str = Field(min_length=1, max_length=40)


def _validate_book_id(book_id: str) -> None:
    """Reject path-traversal-bearing book ids（与 mastery_path._validate_book_id 一致）。"""
    if ".." in book_id or "/" in book_id or "\\" in book_id or ":" in book_id:
        raise HTTPException(status_code=400, detail="Invalid book_id")


@router.post("")
async def start_pipeline(
    body: StartRequest,
    _: TokenPayload = Depends(require_admin_or_teacher),
) -> dict[str, Any]:
    """创建管线 run 并后台执行四段（同书已有 run 在跑时不阻塞，直接再建一条）。"""
    _validate_book_id(body.book_id)
    kb_name = body.kb_name.strip()
    if not kb_name:
        raise HTTPException(status_code=400, detail="kb_name is required")
    record = pipe.start_pipeline(kb_name, body.book_id.strip())
    return {"ok": True, "run": record}


@router.get("")
async def pipeline_status(
    kb_name: str,
    book_id: str,
    _: TokenPayload = Depends(require_admin_or_teacher),
) -> dict[str, Any]:
    """返回 (kb_name, book_id) 最近一次 run 的状态全景；无记录返回 404。"""
    _validate_book_id(book_id)
    record = pipe.find_latest_run(kb_name.strip(), book_id.strip())
    if record is None:
        raise HTTPException(status_code=404, detail="No pipeline run found for this book")
    return {"ok": True, "run": record}


@router.post("/{run_id}/retry")
async def retry_pipeline_stage(
    run_id: str,
    body: RetryRequest,
    _: TokenPayload = Depends(require_admin_or_teacher),
) -> dict[str, Any]:
    """重试指定段；阶段名非法 / run 不存在 / 目标在跑分别 400 / 404 / 409。"""
    stage = body.stage.strip()
    if stage not in _VALID_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage '{stage}'. Valid stages: {', '.join(pipe.STAGE_ORDER)}",
        )
    # 防重入：run 或目标段已在跑时拒绝——同 run 双线程会互踩 save_run
    # 的整记录替换（读-改-写无跨线程合并），且同书并发出题会互相丢章。
    existing = pipe.get_run(run_id.strip())
    if existing is not None:
        busy = existing.get("status") in ("running", "queued") or (
            existing.get("stages", {}).get(stage, {}).get("status") in ("running", "queued")
        )
        if busy:
            raise HTTPException(
                status_code=409,
                detail="Pipeline run or target stage is currently running; retry later",
            )
    try:
        record = pipe.retry_stage(run_id.strip(), stage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pipe.IngestConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if record is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return {"ok": True, "run": record}
