"""Discussion-mode protocol and built-in Partner Group implementations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from deeptutor.services.partner_groups.models import GroupMessage, PartnerGroupConfig

GroupEmitter = Callable[[dict], Awaitable[None]]


class GroupResponder(Protocol):
    async def __call__(
        self,
        partner_id: str,
        *,
        extra_context: str = "",
        instruction: str = "",
        allow_invoke_other: bool = True,
    ) -> GroupMessage: ...


@dataclass(slots=True)
class DiscussionContext:
    group: PartnerGroupConfig
    targets: list[str]
    respond: GroupResponder
    emit: GroupEmitter


class DiscussionMode(Protocol):
    name: str
    label: str
    description: str

    async def run(self, context: DiscussionContext) -> list[GroupMessage]: ...


class DiscussionModeRegistry:
    def __init__(self) -> None:
        self._modes: dict[str, DiscussionMode] = {}

    def register(self, mode: DiscussionMode) -> None:
        if mode.name in self._modes:
            raise ValueError(f"Discussion mode already registered: {mode.name}")
        self._modes[mode.name] = mode

    def get(self, name: str) -> DiscussionMode:
        mode = self._modes.get(name)
        if mode is None:
            raise ValueError(f"Unknown discussion mode: {name}")
        return mode

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": mode.name, "label": mode.label, "description": mode.description}
            for mode in self._modes.values()
        ]


class PanelParallelMode:
    """All selected Partners reason independently over the same public snapshot."""

    name = "panel_parallel"
    label = "Parallel panel"
    description = (
        "Selected Partners answer concurrently from shared public context; "
        "their private intermediate work is not shared."
    )

    async def run(self, context: DiscussionContext) -> list[GroupMessage]:
        async def one(partner_id: str) -> GroupMessage:
            await context.emit({"type": "partner_started", "partner_id": partner_id})
            message = await context.respond(partner_id)
            await context.emit({"type": "partner_message", "message": message.to_dict()})
            return message

        return list(await asyncio.gather(*(one(partner_id) for partner_id in context.targets)))


class SequentialMode:
    """Partners build on completed contributions in the configured member order."""

    name = "sequential"
    label = "Sequential Build"
    description = (
        "Selected Partners respond in Group member order, each building on messages "
        "already produced this round without repeating them."
    )
    instruction = (
        "Supplement, correct, or advance the prior points, and do not repeat what has "
        "already been said. If you genuinely agree with no addition, briefly state which "
        "point you agree with and offer one new angle."
    )

    async def run(self, context: DiscussionContext) -> list[GroupMessage]:
        target_ids = set(context.targets)
        ordered_targets = [
            partner_id for partner_id in context.group.member_ids if partner_id in target_ids
        ]
        replies: list[GroupMessage] = []
        for partner_id in ordered_targets:
            await context.emit({"type": "partner_started", "partner_id": partner_id})
            message = await context.respond(
                partner_id,
                extra_context=_render_messages(replies),
                instruction=self.instruction,
            )
            await context.emit({"type": "partner_message", "message": message.to_dict()})
            replies.append(message)
        return replies


class DebateMode:
    """Two parallel rounds: independent openings followed by an informed clash."""

    name = "debate"
    label = "Cross Debate"
    description = (
        "Selected Partners debate in two parallel rounds: clear opening positions, then "
        "substantive clashes informed by every opening statement."
    )
    opening_instruction = (
        "This is the debate's opening statement. State a clear position on the user's "
        "question and support it with your strongest reasons."
    )
    clash_instruction = (
        "This is the debate's clash round. Identify substantive disagreements with other "
        "opening statements, state clearly what you disagree with and why, and explicitly "
        "concede and revise if another opening persuades you. Do not restate your own Round 1 "
        "content."
    )

    async def run(self, context: DiscussionContext) -> list[GroupMessage]:
        async def opening(partner_id: str) -> GroupMessage:
            await context.emit({"type": "partner_started", "partner_id": partner_id})
            message = await context.respond(
                partner_id,
                instruction=self.opening_instruction,
            )
            await context.emit({"type": "partner_message", "message": message.to_dict()})
            return message

        openings = list(
            await asyncio.gather(*(opening(partner_id) for partner_id in context.targets))
        )
        # A debate needs someone to disagree with. Addressing a single Partner
        # (an @mention of one member) is a legitimate thing to do, so the clash
        # round is skipped rather than refused — otherwise that speaker would be
        # asked to find disagreements with an empty set and argue against
        # themselves.
        if len(context.targets) < 2:
            return openings
        opening_context = _render_messages(openings)

        async def clash(partner_id: str) -> GroupMessage:
            await context.emit({"type": "partner_started", "partner_id": partner_id})
            message = await context.respond(
                partner_id,
                extra_context=opening_context,
                instruction=self.clash_instruction,
                # The clash round *is* the peer response, so proposing another
                # peer question here duplicates the mechanism and would leave
                # one approval card per speaker per round.
                allow_invoke_other=False,
            )
            message.kind = "debate_rebuttal"
            await context.emit({"type": "partner_message", "message": message.to_dict()})
            return message

        clashes = list(await asyncio.gather(*(clash(partner_id) for partner_id in context.targets)))
        return [*openings, *clashes]


def _render_messages(messages: list[GroupMessage]) -> str:
    return "\n\n".join(f"{message.author_name}: {message.content}" for message in messages)


discussion_mode_registry = DiscussionModeRegistry()
discussion_mode_registry.register(PanelParallelMode())
discussion_mode_registry.register(SequentialMode())
discussion_mode_registry.register(DebateMode())

__all__ = [
    "DiscussionContext",
    "DiscussionMode",
    "DiscussionModeRegistry",
    "GroupResponder",
    "PanelParallelMode",
    "SequentialMode",
    "DebateMode",
    "discussion_mode_registry",
]
