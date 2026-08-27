"""What this deployment's capability registry actually resolved at boot.

Chat surfaces address a capability by name — ``mastery_path``,
``immersive_reading``, and so on — but not every name ships in this
repository. Capabilities also arrive from plugins, and the Whisper practice
room is one of those: its pages live here while ``whisper_visitor`` /
``whisper_trainee`` are served by an out-of-tree capability. A page had no way
to ask whether the backend could honour the name it was about to send, so a
stock install offered the entry, sent the turn anyway, and the learner got
``Unknown capability: whisper_visitor. Available: [...]`` (#963).

This endpoint is the missing fact, and deliberately nothing more: the names the
registry holds, built-ins and plugins alike. Callers that need a capability's
description or schema already have ``/api/v1/plugins/list``, which enumerates
every tool as well and is far too heavy to ask "is this feature installed?".
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/registered")
async def list_registered_capabilities() -> dict[str, list[str]]:
    """Every capability name a turn can be started with, sorted."""
    from deeptutor.runtime.registry.capability_registry import get_capability_registry

    return {"capabilities": sorted(get_capability_registry().list_capabilities())}
