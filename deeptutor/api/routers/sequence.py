"""Solution sequences. The answer order stays in the session store."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.learning.sequence.schema import SequenceError
from deeptutor.learning.sequence.service import (
    explain_step,
    generate_problem,
    hint,
    place_step,
    remove_step,
)
from deeptutor.learning.sequence.store import SequenceStore
from deeptutor.services.path_service import get_path_service

router = APIRouter()


class CreateProblem(BaseModel):
    knowledge_base: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=200)


class PlaceStep(BaseModel):
    step_id: str = Field(min_length=1, max_length=80)
    index: int = Field(ge=0, le=12)


class StepId(BaseModel):
    step_id: str = Field(min_length=1, max_length=80)


def _store() -> SequenceStore:
    return SequenceStore(get_path_service().user_data_dir / "solution_sequence")


def _raise(exc: SequenceError) -> None:
    raise HTTPException(exc.status, exc.message) from exc


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


@router.post("/problems/{problem_id}/hint")
async def get_hint(problem_id: str):
    try:
        return await hint(_store(), problem_id)
    except SequenceError as exc:
        _raise(exc)


@router.post("/problems/{problem_id}/explain")
async def explain(problem_id: str, body: StepId):
    try:
        return await explain_step(_store(), problem_id, body.step_id)
    except SequenceError as exc:
        _raise(exc)
