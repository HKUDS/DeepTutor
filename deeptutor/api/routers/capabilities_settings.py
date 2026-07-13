"""Capabilities settings endpoint.

Surfaces the per-capability tunables (temperature, max_tokens, stage
budgets, iteration limits) currently scattered across
``data/user/settings/agents.yaml`` and ``data/user/settings/main.yaml``.

Mirrors the pattern used by ``/api/v1/memory/settings``:

* ``GET  /settings``  → returns the full schema with defaults merged in.
* ``PUT  /settings``  → merges payload back into both YAML files and
                        returns the new state.

Validation lives in
:mod:`deeptutor.services.config.capabilities_settings` so the API stays
a thin transport layer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/settings")
async def get_capabilities_settings_endpoint() -> dict[str, Any]:
    from deeptutor.services.config.capabilities_settings import capabilities_settings_dict

    return capabilities_settings_dict()


@router.put("/settings")
async def put_capabilities_settings(payload: dict[str, Any]) -> dict[str, Any]:
    from deeptutor.services.config.capabilities_settings import save_capabilities_settings

    return save_capabilities_settings(payload)
