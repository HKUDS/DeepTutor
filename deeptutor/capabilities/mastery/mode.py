"""What a mastery conversation is doing right now.

Three things are deliberately separate here, and keeping them separate is the
whole point of this module:

* the **engine** — one agent loop, the same reasoning substrate in every mode;
* the **mode** — which prompt block frames the sitting and which tools it may
  use;
* the **session** — the conversation the learner is actually having, which
  carries a *current* mode and can change it.

A mode is therefore mutable state on a session, not a property of it. The tutor
changes it with ``mastery_mode`` when the learner asks for something the
current mode cannot do; the learner changes it by pressing one of the three
buttons above the transcript. Either way the conversation continues — nobody
has to open a new one to fix a knowledge point.

Why the mode is enforced when a tool is *called*, not when it is mounted
----------------------------------------------------------------------
The obvious implementation is to mount only the current mode's tools. It was
the first one here, and it cannot survive a mutable mode: a turn's tool
schemas *and* its system prompt are both assembled once, before the first
round (see ``AgenticLoopPipeline.run``), so a mode changed mid-turn would win
no new tools until the next one. "Call a tool to unlock that mode's tools"
would then be false for the turn that called it.

So every mastery tool is mounted every turn, and the ones that belong to a
mode check :func:`ensure_mode` when they run. The guarantee the learner cares
about is identical — an outline sitting still cannot examine them, because the
engine refuses — it just moves from mount time to call time. What the model
pays is a few extra schemas it should not reach for, and the refusal it gets
back names the tool that would unlock them.

``mastery_mode`` returns the new mode's instructions in its own result for the
same reason: the system prompt above it still describes the mode the turn
started in, and a tool result is the only thing that can correct it without
waiting for the next turn.
"""

from __future__ import annotations

from typing import Any

#: Designing the outline with the learner. The mode a goal's first
#: conversation opens in, and the only one that may change the map.
OUTLINE = "outline"
#: Working the agreed outline forward — the ordinary learning mode.
STUDY = "study"
#: Re-testing what is already mastered, whether or not it is due.
REVIEW = "review"

MODES: tuple[str, ...] = (OUTLINE, STUDY, REVIEW)

#: What a conversation is doing when it never said. Every mastery conversation
#: that existed before modes was a learning conversation, so reading a missing
#: value as anything else would retroactively change what those were doing.
DEFAULT_MODE = STUDY

#: Which mode owns each mode-exclusive tool. Everything absent from this table
#: is shared by all three — "where am I", "who is learning this", "read that
#: material", "change modes" are true regardless of what the sitting is for.
#:
#: The two halves:
#:
#: * **Changing the map** belongs to ``outline`` alone, so that a learner can
#:   always tell which mode is allowed to alter their course. Reaching it from
#:   a lesson costs one ``mastery_mode`` call, and that call is visible — which
#:   is the point, not the cost.
#: * **Examining the learner** belongs to ``study`` and ``review``. An outline
#:   sitting has nothing agreed to examine on yet.
TOOL_MODES: dict[str, frozenset[str]] = {
    "mastery_build": frozenset({OUTLINE}),
    "mastery_revise": frozenset({OUTLINE}),
    "mastery_quiz": frozenset({STUDY, REVIEW}),
    "mastery_grade": frozenset({STUDY, REVIEW}),
    "mastery_assess": frozenset({STUDY, REVIEW}),
    "mastery_skip_question": frozenset({STUDY, REVIEW}),
}


def normalize_mode(value: Any) -> str:
    """The mode to *show and frame with*, always one of :data:`MODES`.

    Never raises: an unrecognised mode is a client ahead of or behind this
    server, and something has to pick a prompt block. That is why this is not
    the function tool gating uses — see :func:`enforced_mode`.
    """
    candidate = str(value or "").strip().lower()
    return candidate if candidate in MODES else DEFAULT_MODE


def enforced_mode(value: Any) -> str | None:
    """The mode to *enforce against*, or ``None`` when none was recorded.

    Deliberately different from :func:`normalize_mode`. Every mastery
    conversation that predates modes carries no mode at all, and so do the CLI
    and SDK entry points, which never pass one. Falling those back to a real
    mode would retroactively forbid things they have always been allowed to do
    — a chat that builds a path for the first time would find ``mastery_build``
    refused, having never been in any mode.

    So an unrecorded mode enforces nothing. Every conversation opened through
    the product carries one explicitly, which is what makes the guarantee real
    where it matters.
    """
    candidate = str(value or "").strip().lower()
    return candidate if candidate in MODES else None


def tool_is_allowed(tool_name: str, mode: Any) -> bool:
    """Whether *tool_name* may run in *mode*. Unlisted tools are shared."""
    allowed = TOOL_MODES.get(tool_name)
    if allowed is None:
        return True
    current = enforced_mode(mode)
    return True if current is None else current in allowed


def admission_error(mode: Any, *, has_outline: bool) -> str:
    """Why this mode cannot be entered, or ``""``.

    Exactly one refusal exists, and it is the only one that can: there is
    nothing to study until an outline is agreed. Reviewing is deliberately
    *not* gated on anything being due — a due date is a reminder, not a
    permission, and a learner may always ask to go back over something they
    have already mastered.

    Shared by the tool and the REST endpoint the mode buttons call, so the
    tutor and the learner cannot be told different things about the same move.
    """
    if normalize_mode(mode) == STUDY and not has_outline:
        return (
            "There is no outline to study yet. Stay in 'outline' and design "
            "one with the learner first."
        )
    return ""


def owning_modes(tool_name: str) -> tuple[str, ...]:
    """The modes *tool_name* belongs to, or ``()`` when it is shared."""
    allowed = TOOL_MODES.get(tool_name)
    return tuple(mode for mode in MODES if mode in allowed) if allowed else ()


def wrong_mode_message(tool_name: str, mode: Any) -> str:
    """Why this call was refused, and the one move that fixes it.

    A refusal that only says "no" is one the model retries verbatim, so this
    always names ``mastery_mode`` and the mode to switch into.
    """
    targets = owning_modes(tool_name)
    current = normalize_mode(mode)
    listed = " or ".join(repr(target) for target in targets) or "another mode"
    return (
        f"{tool_name} belongs to the {listed} mode, and this conversation is "
        f"in {current!r}. Call mastery_mode with mode={targets[0]!r} first — "
        "tell the learner what you are switching to and why, because the mode "
        "is shown to them above the conversation."
        if targets
        else f"{tool_name} cannot run in {current!r}."
    )


__all__ = [
    "DEFAULT_MODE",
    "MODES",
    "OUTLINE",
    "REVIEW",
    "STUDY",
    "TOOL_MODES",
    "admission_error",
    "enforced_mode",
    "normalize_mode",
    "owning_modes",
    "tool_is_allowed",
    "wrong_mode_message",
]
