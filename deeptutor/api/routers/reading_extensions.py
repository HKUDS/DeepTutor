"""Authenticated transport for schema-driven Immersive Reading extensions."""

from __future__ import annotations

import asyncio
from contextvars import copy_context
import inspect
import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from deeptutor.multi_user.learning_access import (
    allowed_reading_extensions,
    assert_learning_material,
)
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import (
    ReadingContext,
    ReadingExtensionResult,
    get_reading_extension_registry,
)

router = APIRouter()
ACTION_TIMEOUT_S = 30
logger = logging.getLogger(__name__)


class ReadingModelSelection(BaseModel):
    profile_id: str = Field(min_length=1, max_length=256)
    model_id: str = Field(min_length=1, max_length=256)
    reasoning_effort: str | None = Field(default=None, max_length=32)


class ActionPayload(BaseModel):
    llm_selection: ReadingModelSelection | None = None
    locator: int = Field(ge=1)
    selection: str = Field(default="", max_length=10_000)
    locale: str = Field(default="en", max_length=32)


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _verified_selection(candidate: str, unit_text: str) -> str:
    value = _normal(candidate)
    return value if value and value in _normal(unit_text) else ""


@router.get("/extensions")
async def list_extensions() -> list[dict[str, Any]]:
    allowed = allowed_reading_extensions()
    return [
        extension.manifest.model_dump()
        for extension in get_reading_extension_registry().all()
        if allowed is None or extension.manifest.id in allowed
    ]


@router.post("/materials/{material_id}/extensions/{extension_id}/actions/{action}")
async def run_extension_action(
    material_id: str,
    extension_id: str,
    action: str,
    payload: ActionPayload,
) -> dict[str, Any]:
    try:
        assert_learning_material(material_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    allowed = allowed_reading_extensions()
    if allowed is not None and extension_id not in allowed:
        raise HTTPException(status_code=403, detail="This reading extension is not allowed.")

    registry = get_reading_extension_registry()
    extension = registry.get(extension_id)
    if extension is None:
        raise HTTPException(status_code=404, detail="Reading extension not found.")
    declared_action = next((row for row in extension.manifest.actions if row.id == action), None)
    if declared_action is None:
        raise HTTPException(status_code=404, detail="Reading extension action not found.")
    store = ReadingStore()
    try:
        unit_text = store.unit_text(material_id, payload.locator)
        position = store.position(material_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    selection = _verified_selection(payload.selection, unit_text)
    if "selection" in declared_action.requires and not selection:
        raise HTTPException(status_code=400, detail="Select text from the visible unit first.")
    try:
        context = ReadingContext(
            material_id=material_id,
            locator=payload.locator,
            source_anchor=(position.source_anchor if position.locator == payload.locator else ""),
            locale=payload.locale,
            selection=selection,
            visible_text=unit_text,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="This reading unit is too large for the extension protocol.",
        ) from exc
    request_id = uuid4().hex

    def failure(code, message, *, recoverable=True, status=503):
        logger.warning("Reading action %s request=%s code=%s", extension_id, request_id, code)
        return HTTPException(
            status_code=status,
            detail={
                "message": message,
                "code": code,
                "recoverable": recoverable,
                "request_id": request_id,
            },
        )

    token = None
    if extension.manifest.requires_llm:
        from deeptutor.multi_user.model_access import apply_allowed_llm_selection
        from deeptutor.services.model_selection.runtime import (
            activate_llm_selection,
            reset_llm_selection,
        )

        try:
            selection_config = (
                payload.llm_selection.model_dump(exclude_none=True)
                if payload.llm_selection
                else None
            )
            selection_config = apply_allowed_llm_selection(selection_config)
            # A shared default is still subject to the caller's model grants.
            if selection_config is None:
                from deeptutor.multi_user.context import get_current_user
                from deeptutor.services.config.model_catalog import get_model_catalog_service

                user = get_current_user()
                if not user.is_admin:
                    service = get_model_catalog_service().load().get("services", {}).get("llm", {})
                    selection_config = {
                        "profile_id": service.get("active_profile_id"),
                        "model_id": service.get("active_model_id"),
                    }
                    if not all(selection_config.values()):
                        raise ValueError("No selected model")
                    apply_allowed_llm_selection(selection_config)
            config, token = activate_llm_selection(selection_config)
            if not config.model:
                raise ValueError("No selected model")
        except PermissionError:
            reset_llm_selection(token)
            raise failure(
                "model_forbidden",
                "This model is not assigned to your account. Choose an authorized model or contact your administrator.",
                recoverable=False,
                status=403,
            ) from None
        except Exception as exc:
            reset_llm_selection(token)
            logger.warning(
                "Reading action %s request=%s model configuration failed (%s)",
                extension_id,
                request_id,
                type(exc).__name__,
            )
            raise failure(
                "model_not_configured",
                "Choose a model in the reading conversation before using this action. Contact your administrator if no model is available.",
                recoverable=False,
            ) from None

    worker = None
    started = False
    try:
        if not registry.begin_action(extension_id):
            if registry.is_timed_out(extension_id):
                raise failure(
                    "worker_running",
                    "The previous reading action is still running. Wait for it to finish, or ask an administrator to restart the backend.",
                    recoverable=False,
                )
            raise failure("busy", "This reading action is busy. Try again after it finishes.")
        started = True
        async with asyncio.timeout(ACTION_TIMEOUT_S):
            if inspect.iscoroutinefunction(extension.run_action):
                value = await extension.run_action(action, context)
            else:
                worker = asyncio.get_running_loop().run_in_executor(
                    registry.executor_for(extension_id),
                    copy_context().run,
                    extension.run_action,
                    action,
                    context,
                )
                value = await asyncio.shield(worker)
                if inspect.isawaitable(value):
                    value = await value
        try:
            result = (
                value
                if isinstance(value, ReadingExtensionResult)
                else ReadingExtensionResult.model_validate(value)
            )
            if result.type not in extension.manifest.result_types:
                raise ValueError("Undeclared result type")
        except (ValueError, TypeError):
            raise failure(
                "invalid_output", "The reading provider returned an invalid result. Please retry."
            ) from None
        return result.model_dump()
    except HTTPException:
        raise
    except TimeoutError:
        if worker is not None and not worker.done():
            registry.mark_timed_out(extension_id)

            def settled(future):
                registry.clear_timeout(extension_id)
                if not future.cancelled():
                    future.exception()

            worker.add_done_callback(settled)
            raise failure(
                "worker_running",
                "The reading action timed out but is still running. Wait, or ask an administrator to restart the backend.",
                recoverable=False,
            ) from None
        logger.warning("Reading action %s request=%s timed out", extension_id, request_id)
        raise failure("timeout", "The reading action timed out. You can try again.") from None
    except Exception as exc:
        logger.warning(
            "Reading action %s request=%s failed (%s)", extension_id, request_id, type(exc).__name__
        )
        code = (
            "invalid_output" if isinstance(exc, (ValueError, ValidationError)) else "provider_error"
        )
        message = (
            "The reading provider returned an invalid result. Please retry."
            if code == "invalid_output"
            else "The reading provider failed. Check the selected model or contact your administrator."
        )
        raise failure(code, message) from None
    finally:
        if started:
            registry.finish_action(extension_id)
        if token is not None:
            from deeptutor.services.model_selection.runtime import reset_llm_selection

            reset_llm_selection(token)


__all__ = ["router"]
