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
