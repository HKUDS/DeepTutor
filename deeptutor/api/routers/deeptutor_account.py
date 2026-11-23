"""Self-service device sign-in for the current DeepTutor owner."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deeptutor.core.identities import is_partner_user_id
from deeptutor.multi_user.context import get_current_user
from deeptutor.services.deeptutor_account import DeepTutorAccount, SignIn, get_deeptutor_account
from deeptutor.services.deeptutor_account.client import DeepTutorAccountError
from deeptutor.services.llm.config import clear_llm_config_cache


def _require_human_actor() -> None:
    if is_partner_user_id(get_current_user().id):
        raise HTTPException(403, "Only the owner can manage this DeepTutor Studio connection.")


router = APIRouter(prefix="/providers/deeptutor/auth", dependencies=[Depends(_require_human_actor)])
_login_tasks: set[asyncio.Task[None]] = set()


class DeviceStart(BaseModel):
    device_label: str | None = Field(default=None, max_length=64)


def _http_error(exc: DeepTutorAccountError) -> HTTPException:
    return HTTPException(
        exc.status_code or 500,
        {"code": exc.error_code, "message": exc.message, "action_url": exc.action_url},
        headers={"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None,
    )


async def _finish(account: DeepTutorAccount, sign_in: SignIn) -> None:
    error = None
    try:
        access = await account.finish(sign_in)
        await account.refresh_models(access)
        clear_llm_config_cache()
        with suppress(DeepTutorAccountError):
            await account.refresh_balance(access)
    except DeepTutorAccountError as exc:
        error = exc
    finally:
        with suppress(DeepTutorAccountError):
            await account.cancel(sign_in, error=error)


@router.get("/status")
async def get_status() -> dict[str, Any]:
    try:
        return await get_deeptutor_account().status()
    except DeepTutorAccountError as exc:
        raise _http_error(exc) from None


@router.post("/start")
async def start_login(payload: DeviceStart | None = None) -> dict[str, Any]:
    account = get_deeptutor_account()
    try:
        current = await account.status()
        if current["state"] == "pending":
            return current
        sign_in = await account.start(device_label=payload.device_label if payload else None)
    except DeepTutorAccountError as exc:
        raise _http_error(exc) from None
    task = asyncio.create_task(_finish(account, sign_in))
    _login_tasks.add(task)
    task.add_done_callback(_login_tasks.discard)
    return {"state": "pending", **sign_in.public()}


@router.post("/cancel")
async def cancel_login() -> dict[str, Any]:
    account = get_deeptutor_account()
    try:
        await account.cancel()
        return await account.status()
    except DeepTutorAccountError as exc:
        raise _http_error(exc) from None


@router.post("/logout")
async def logout() -> dict[str, Any]:
    try:
        await get_deeptutor_account().logout()
        clear_llm_config_cache()
    except DeepTutorAccountError as exc:
        raise _http_error(exc) from None
    return {"state": "idle"}


@router.post("/models")
async def refresh_models() -> dict[str, Any]:
    account = get_deeptutor_account()
    try:
        await account.refresh_models()
        clear_llm_config_cache()
        with suppress(DeepTutorAccountError):
            await account.refresh_balance()
        return await account.status()
    except DeepTutorAccountError as exc:
        raise _http_error(exc) from None
