"""Read-only deployment inventory; code mutations run in the offline CLI."""

from fastapi import APIRouter

from deeptutor.modules.catalog import module_statuses

router = APIRouter()


@router.get("")
def list_modules():
    return {"modules": module_statuses()}
