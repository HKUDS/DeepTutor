"""Solution sequences. The answer order stays in the session store."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from deeptutor.learning.sequence.schema import SequenceError
from deeptutor.learning.sequence.service import (
    build_outline,
    check_answer,
    explain_step,
    generate_problem,
    hint,
    place_step,
    read_outline,
    remove_step,
)
from deeptutor.learning.sequence.store import SequenceStore
from deeptutor.services.path_service import get_path_service

router = APIRouter()


class CreateProblem(BaseModel):
    knowledge_base: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=200)


class KnowledgeBaseName(BaseModel):
    knowledge_base: str = Field(min_length=1, max_length=200)


class PlaceStep(BaseModel):
    step_id: str = Field(min_length=1, max_length=80)
    index: int = Field(ge=0, le=12)


class StepId(BaseModel):
    step_id: str = Field(min_length=1, max_length=80)


class CheckSteps(BaseModel):
    step_ids: list[str] = Field(max_length=12)


class HintSteps(BaseModel):
    step_ids: list[str] = Field(default_factory=list, max_length=12)


def _store() -> SequenceStore:
    return SequenceStore(get_path_service().user_data_dir / "solution_sequence")


def _raise(exc: SequenceError) -> None:
    raise HTTPException(exc.status, exc.message) from exc


def _hint_step_ids(raw: bytes) -> list[str] | None:
    """None keeps the saved placement. A body may name the steps already assembled."""
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Say which steps are already assembled.") from exc
    if not isinstance(data, dict):
        raise HTTPException(422, "Say which steps are already assembled.")
    if "step_ids" not in data:
        return None
    try:
        return HintSteps.model_validate({"step_ids": data.get("step_ids")}).step_ids
    except ValidationError as exc:
        raise HTTPException(422, "Say which steps are already assembled.") from exc


@router.get("/outlines")
def get_outline(knowledge_base: str = Query(min_length=1, max_length=200)):
    try:
        return read_outline(_store(), knowledge_base)
    except SequenceError as exc:
        _raise(exc)


@router.post("/outlines")
async def create_outline(body: KnowledgeBaseName):
    try:
        return await build_outline(body.knowledge_base, _store())
    except SequenceError as exc:
        _raise(exc)


@router.post("/problems")
async def create_problem(body: CreateProblem):
    try:
        return await generate_problem(body.knowledge_base, body.topic, _store())
    except SequenceError as exc:
        _raise(exc)


@router.post("/problems/{problem_id}/place")
def place(problem_id: str, body: PlaceStep):
    try:
        return place_step(_store(), problem_id, body.step_id, body.index)
    except SequenceError as exc:
        _raise(exc)


@router.post("/problems/{problem_id}/remove")
def remove(problem_id: str, body: StepId):
    try:
        return remove_step(_store(), problem_id, body.step_id)
    except SequenceError as exc:
        _raise(exc)


@router.post("/problems/{problem_id}/check")
def check(problem_id: str, body: CheckSteps):
    try:
        return check_answer(_store(), problem_id, body.step_ids)
    except SequenceError as exc:
        _raise(exc)


@router.post("/problems/{problem_id}/hint")
async def get_hint(problem_id: str, request: Request):
    step_ids = _hint_step_ids(await request.body())
    try:
        return await hint(_store(), problem_id, step_ids=step_ids)
    except SequenceError as exc:
        _raise(exc)


@router.post("/problems/{problem_id}/explain")
async def explain(problem_id: str, body: StepId):
    try:
        return await explain_step(_store(), problem_id, body.step_id)
    except SequenceError as exc:
        _raise(exc)
