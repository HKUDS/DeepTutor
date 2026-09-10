"""What this deployment's capability registry actually resolved at boot.

Chat surfaces address a capability by name — ``deep_research``,
``visualize``, and so on — but not every name ships in this
repository. Capabilities also arrive from plugins, and the Whisper practice
room is one of those: its pages live here while ``whisper_visitor`` /
``whisper_trainee`` are served by an out-of-tree capability. A page had no way
to ask whether the backend could honour the name it was about to send, so a
stock install offered the entry, sent the turn anyway, and the learner got
``Unknown capability: whisper_visitor. Available: [...]`` (#963).

This endpoint exposes the backend-owned identity, manifest, and validated
configuration schema for every turn capability. Presentation remains a
frontend concern.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/resource-providers")
async def list_resource_providers() -> dict[str, list[dict[str, object]]]:
    """Describe every registered resource provider plus its live state."""
    from deeptutor.services.resource_providers import get_resource_provider_registry

    return {"providers": get_resource_provider_registry().descriptions()}


@router.put("/resource-providers/{name}/state")
async def set_resource_provider_state(name: str, body: dict[str, object]) -> dict[str, object]:
    """Persist one resource provider's enable/disable state."""
    from fastapi import HTTPException

    from deeptutor.services.resource_providers import (
        get_resource_provider_registry,
        set_provider_enabled,
    )

    registry = get_resource_provider_registry()
    if registry.get(name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown resource provider: {name}")
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="Body must contain boolean 'enabled'")
    set_provider_enabled(name, enabled)
    row = next(
        item for item in registry.descriptions() if str(item.get("name")) == name
    )
    return row


@router.get("/registered")
async def list_registered_capabilities() -> dict[str, list[dict[str, object]]]:
    """Describe every turn capability the deployment can execute."""
    from deeptutor.runtime.registry.capability_registry import get_capability_registry

    descriptors: list[dict[str, object]] = []
    for item in get_capability_registry().get_manifests():
        manifest = {
            key: value for key, value in item.items() if key not in {"request_schema", "kind"}
        }
        descriptors.append(
            {
                "id": str(item["name"]),
                "kind": str(item.get("kind") or "turn"),
                "available": True,
                "manifest": manifest,
                "config_schema": item.get("request_schema") or {},
            }
        )
    descriptors.sort(key=lambda item: str(item["id"]))
    return {"capabilities": descriptors}
