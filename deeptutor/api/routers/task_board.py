"""Authenticated task board endpoints using the current content workspace."""

from fastapi import APIRouter, HTTPException

from deeptutor.services.task_board import CreateCard, TaskBoard, UpdateCard, get_task_board_store

router = APIRouter()


@router.get("", response_model=TaskBoard)
def get_board() -> TaskBoard:
    """Return active and archived cards in the current workspace."""
    return get_task_board_store().read()


@router.post("/cards", response_model=TaskBoard, status_code=201)
def create_card(payload: CreateCard) -> TaskBoard:
    """Create a task in the To do column."""
    return get_task_board_store().create(payload)


@router.patch("/cards/{card_id}", response_model=TaskBoard)
def update_card(card_id: str, payload: UpdateCard) -> TaskBoard:
    """Edit, move, archive or restore an existing task."""
    try:
        return get_task_board_store().update(card_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task card not found.") from exc
