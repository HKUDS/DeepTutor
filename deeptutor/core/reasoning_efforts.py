"""Reasoning-effort vocabulary shared by core validation and the service layer."""

# What a conversation-level override (#641) is allowed to ask for. This is a
# request-validation vocabulary, deliberately the union of every level any
# provider understands — `services/llm/reasoning_params.py` is what maps a
# level onto a given provider's actual knob, and the per-backend `efforts`
# lists in `services/subagent/models.py` describe what each subagent CLI
# accepts. Neither of those is interchangeable with this one. Not every
# provider/model supports every value, so callers that can offer a narrower,
# model-specific list should filter before submitting a selection.
#
# Core owns the canonical tuple so the turn-request validator can check it
# without importing the service layer; the service layer re-exports it.
VALID_REASONING_EFFORTS: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)


def normalize_reasoning_effort(value: object) -> str | None:
    """Trim and lowercase an override; blank (or ``None``) means "no override"."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


__all__ = [
    "VALID_REASONING_EFFORTS",
    "normalize_reasoning_effort",
]
