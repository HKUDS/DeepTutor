"""The per-turn mastery_status snapshot, kept to what changes between turns.

Every mastery turn starts with a fresh ``mastery_status`` read placed in the
request as a runtime snapshot, and earlier turns' snapshots stay in the replayed
history so the cached prefix keeps growing. Whatever a snapshot carries is
therefore paid for once per turn and then kept. A full status read repeats
guidance that never changes (how to treat an open question, how to use the
learner profile, what a working brief is) and spells out every default value
of every knowledge point. The snapshot leaves both out: the fixed guidance is
stated once in the system prompt (:func:`status_guide`), and empty or default
values are simply omitted, which the same guide explains.

An explicit ``mastery_status`` tool call still returns the full payload.
"""

from __future__ import annotations

from typing import Any

from deeptutor.capabilities.mastery.history import SNAPSHOT_HEADER
from deeptutor.capabilities.mastery.tools import (
    GROUP_REPLY_INSTRUCTION,
    INTAKE_INSTRUCTION,
    OPEN_QUESTION_INSTRUCTION,
    WORKING_BRIEF_INSTRUCTION,
)
from deeptutor.learning.teaching import TEACHING_FOCUS_INSTRUCTION, TEACHING_GUIDANCE

# Knowledge-point fields that are left out while they hold their default.
_POINT_DEFAULTS: dict[str, Any] = {
    "prerequisite_ids": [],
    "topic_source_ids": [],
    "status": "new",
    "mastery": 0,
    "mastery_source": "",
    "override_note": "",
    "deferred": False,
}
_FIXED_INSTRUCTIONS = frozenset({GROUP_REPLY_INSTRUCTION, OPEN_QUESTION_INSTRUCTION})


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _point(point: Any) -> Any:
    if not isinstance(point, dict):
        return point
    return {
        key: value
        for key, value in point.items()
        if not (key in _POINT_DEFAULTS and value == _POINT_DEFAULTS[key])
    }


def _map(overview: Any) -> Any:
    if not isinstance(overview, dict) or not isinstance(overview.get("modules"), list):
        return overview
    modules = []
    for module in overview["modules"]:
        if isinstance(module, dict) and isinstance(module.get("knowledge_points"), list):
            module = {**module, "knowledge_points": [_point(p) for p in module["knowledge_points"]]}
        modules.append(module)
    return {**overview, "modules": modules}


def _next(step: Any) -> Any:
    if not isinstance(step, dict):
        return step
    step = dict(step)
    question = step.get("pending_question")
    if isinstance(question, dict) and step.get("pending_prompt") == question.get("prompt"):
        step.pop("pending_prompt")
    for key in ("pending_prompt", "pending_question", "session_id"):
        if key in step and _empty(step[key]):
            step.pop(key)
    return step


def _profile(profile: Any) -> Any:
    if not isinstance(profile, dict):
        return profile
    profile = {
        key: value
        for key, value in profile.items()
        if key != "teaching_guidance" or value != TEACHING_GUIDANCE
    }
    focus = profile.get("teaching_focus")
    if isinstance(focus, dict):
        focus = {
            key: value
            for key, value in focus.items()
            if key != "instruction" or value != TEACHING_FOCUS_INSTRUCTION
        }
        profile["teaching_focus"] = focus if focus.get("observations") else None
    return {key: value for key, value in profile.items() if not _empty(value)}


def _pending(interaction: Any) -> Any:
    if not isinstance(interaction, dict):
        return interaction
    interaction = dict(interaction)
    interaction.pop("session_id", None)
    if interaction.get("instruction") in _FIXED_INSTRUCTIONS:
        interaction.pop("instruction")
    return interaction


def compact_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop fixed guidance and default values from a ``mastery_status`` payload."""
    result = dict(payload)
    if result.get("inspection_instruction") == WORKING_BRIEF_INSTRUCTION:
        result.pop("inspection_instruction")
    if result.get("intake_instruction") == INTAKE_INSTRUCTION:
        result.pop("intake_instruction")
    if result.get("intake_needed") is False:
        result.pop("intake_needed")
    if "next" in result:
        result["next"] = _next(result["next"])
    if "map" in result:
        result["map"] = _map(result["map"])
    if "learner_profile" in result:
        result["learner_profile"] = _profile(result["learner_profile"])
    if isinstance(result.get("learning_stages"), dict):
        result["learning_stages"] = {
            key: value
            for key, value in result["learning_stages"].items()
            if value != "not_yet_covered"
        }
    if isinstance(result.get("visual_requirements"), dict):
        result["visual_requirements"] = {
            key: value
            for key, value in result["visual_requirements"].items()
            if not (isinstance(value, dict) and all(_empty(item) for item in value.values()))
        }
    if "pending_interaction" in result:
        result["pending_interaction"] = _pending(result["pending_interaction"])
    for key in ("goal", "sources", "due_review_ids", "learning_stages", "visual_requirements"):
        if key in result and _empty(result[key]):
            result.pop(key)
    return result


def status_guide(template: str) -> str:
    """Fill the localized guide with the fixed guidance the snapshot leaves out."""
    values = {
        "{working_brief}": WORKING_BRIEF_INSTRUCTION,
        "{intake}": INTAKE_INSTRUCTION,
        "{open_question}": OPEN_QUESTION_INSTRUCTION,
        "{group_reply}": GROUP_REPLY_INSTRUCTION,
        "{teaching_guidance}": TEACHING_GUIDANCE,
        "{teaching_focus}": TEACHING_FOCUS_INSTRUCTION,
    }
    for placeholder, value in values.items():
        template = template.replace(placeholder, value)
    return template


__all__ = ["SNAPSHOT_HEADER", "compact_status", "status_guide"]
