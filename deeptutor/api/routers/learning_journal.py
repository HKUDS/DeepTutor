"""Read-only view of the workspace's conversational learning journal."""

from fastapi import APIRouter, HTTPException

from deeptutor.services.learning_journal import get_learning_journal_store

router = APIRouter()


@router.get("")
def overview():
    try:
        return get_learning_journal_store().overview()
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Learning journal could not be read. Its original file has been preserved.",
        ) from exc
