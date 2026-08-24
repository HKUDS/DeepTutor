"""Authenticated, policy-aware transport for schema-driven Reading extensions."""

from __future__ import annotations

import inspect
import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.multi_user.learning_access import (
    allowed_reading_extensions,
    assert_learning_material,
    current_learning_policy,
)
from deeptutor.multi_user.paths import get_current_path_service
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import (
    ReadingContext,
    ReadingExtensionResult,
    dispatch_learning_event,
    get_reading_extension_registry,
)
from deeptutor.reading.learning import LearningLedger

router = APIRouter()


class ActionPayload(BaseModel):
    locator: int = Field(ge=1)
    source_anchor: str = Field(default="", max_length=4096)
    selection: str = Field(default="", max_length=10_000)
    visible_text: str = Field(default="", max_length=60_000)
    locale: str = Field(default="en", max_length=32)


class SubmissionPayload(BaseModel):
    submission_id: str = Field(default="", max_length=128)
    values: dict[str, Any] = Field(default_factory=dict)


def _root(feature: str):
    service = get_current_path_service()
    if feature == "reading":
        return service.get_workspace_feature_dir("reading")  # type: ignore[arg-type]
    return service.workspace_root / "user" / "workspace" / feature


def _store() -> ReadingStore:
    return ReadingStore(_root("reading"))


def _ledger() -> LearningLedger:
    return LearningLedger(_root("learning"))


def _extension(extension_id: str):
    allowed = allowed_reading_extensions()
    if allowed is not None and extension_id not in allowed:
        # Do not reveal whether a non-authorized extension is installed.
        raise HTTPException(status_code=404, detail="Reading extension not found.")
    extension = get_reading_extension_registry().get(extension_id)
    if extension is None:
        raise HTTPException(status_code=404, detail="Reading extension not found.")
    return extension


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _verified(candidate: str, unit_text: str) -> str:
    value = _normal(candidate)
    return value if value and value in _normal(unit_text) else ""


def _public_result(result: ReadingExtensionResult) -> dict[str, Any]:
    row = result.model_dump()
    payload = dict(row.get("payload") or {})
    payload.pop("_answers", None)
    row["payload"] = payload
    return row


def _validate_result(extension: Any, result: ReadingExtensionResult) -> ReadingExtensionResult:
    if result.type not in extension.manifest.result_types:
        raise ValueError(f"Extension returned undeclared result type {result.type!r}.")
    return result


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
    extension = _extension(extension_id)
    declared_action = next((row for row in extension.manifest.actions if row.id == action), None)
    if declared_action is None:
        raise HTTPException(status_code=404, detail="Reading extension action not found.")
    store = _store()
    try:
        manifest = store.manifest(material_id)
        unit_text = store.unit_text(material_id, payload.locator)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ref = next(
        (row for row in store.unit_references(material_id) if row.locator == payload.locator),
        None,
    )
    selection = _verified(payload.selection, unit_text)
    if "selection" in declared_action.requires and not selection:
        raise HTTPException(status_code=400, detail="Select text from the visible unit first.")
    policy = current_learning_policy() or {}
    context = ReadingContext(
        material_id=material_id,
        locator=payload.locator,
        source_href=ref.source_href if ref else "",
        source_anchor=payload.source_anchor,
        locale=payload.locale,
        age_band=str(policy.get("age_band") or ""),
        selection=selection,
        visible_text=_verified(payload.visible_text, unit_text) or unit_text,
        unit_text=unit_text,
    )
    try:
        value = extension.run_action(action, context)
        if inspect.isawaitable(value):
            value = await value
        result = _validate_result(
            extension,
            (
                value
                if isinstance(value, ReadingExtensionResult)
                else ReadingExtensionResult.model_validate(value)
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "This reading action is temporarily unavailable.",
                "recoverable": True,
            },
        ) from exc

    if result.interaction_id:
        answers = result.payload.get("_answers") if isinstance(result.payload, dict) else {}
        _ledger().save_interaction(
            {
                "interaction_id": result.interaction_id,
                "extension": extension_id,
                "action": action,
                "material_id": material_id,
                "locator": payload.locator,
                "private": {"answers": answers if isinstance(answers, dict) else {}},
                "created_at": time.time(),
            }
        )
    return _public_result(result)


@router.post(
    "/materials/{material_id}/extensions/{extension_id}/interactions/{interaction_id}/submit"
)
async def submit_extension_interaction(
    material_id: str,
    extension_id: str,
    interaction_id: str,
    payload: SubmissionPayload,
) -> dict[str, Any]:
    try:
        assert_learning_material(material_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    extension = _extension(extension_id)
    ledger = _ledger()
    interaction = ledger.interaction(interaction_id)
    if (
        interaction is None
        or interaction.get("material_id") != material_id
        or interaction.get("extension") != extension_id
    ):
        raise HTTPException(status_code=404, detail="Reading interaction not found.")
    try:
        value = extension.submit(interaction, payload.values)
        if inspect.isawaitable(value):
            value = await value
        result = _validate_result(
            extension,
            (
                value
                if isinstance(value, ReadingExtensionResult)
                else ReadingExtensionResult.model_validate(value)
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "This submission could not be checked.", "recoverable": True},
        ) from exc
    event = ledger.record(
        interaction=interaction,
        submission={"submission_id": payload.submission_id, "values": payload.values},
        result=result.model_dump(),
    )
    dispatch_learning_event(event, allowed=allowed_reading_extensions())
    return _public_result(result) | {"event_id": event["event_id"]}


@router.get("/records")
async def list_learning_records() -> list[dict[str, Any]]:
    return _ledger().records()


__all__ = ["router"]
