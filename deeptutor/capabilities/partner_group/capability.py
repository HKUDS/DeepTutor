"""Additive chat capability for user-approved Partner-to-Partner questions."""

from __future__ import annotations

from importlib import resources
import re
from typing import Any

from deeptutor.capabilities.partner_group.tools import PARTNER_GROUP_TOOL_NAMES
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext


def _state(context: UnifiedContext) -> dict[str, Any]:
    return context.extension("partner_group")


class PartnerGroupCapability:
    """Enforce the public-answer protocol for every Partner Group turn.

    First-hop turns may additionally register one invocation proposal. Invoked
    replies keep the same answer cleanup and identity constraints, while the
    tool itself remains the final guard against creating a second hop.
    """

    name = "partner_group"
    owned_tools = PARTNER_GROUP_TOOL_NAMES
    # The published answer is not the round's raw prose: a trailing peer
    # request is stripped from it, and ``final_text_override`` republishes the
    # saved, cleaned copy after the private invoke/no-invoke round. Streaming
    # the raw prose would show text that is about to be edited, and then show
    # the answer a second time.
    buffers_visible_output = True

    def is_active(self, context: UnifiedContext) -> bool:
        group = context.metadata.get("partner_group")
        return isinstance(group, dict)

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        _ = prompts
        group = context.metadata.get("partner_group")
        if not isinstance(group, dict):
            return None
        lang = "zh" if str(language or "").lower().startswith("zh") else "en"
        prompt_root = resources.files(__package__).joinpath("prompts", lang)
        members = group.get("members") or []
        roster = "\n".join(
            f"- {str(item.get('name') or item.get('partner_id') or '')} "
            f"(@{str(item.get('partner_id') or '')})"
            for item in members
            if isinstance(item, dict) and item.get("partner_id")
        )
        content = prompt_root.joinpath("system.md").read_text(encoding="utf-8").strip()
        if group.get("allow_invoke_other"):
            proposal = prompt_root.joinpath("invoke_other.md").read_text(encoding="utf-8").strip()
            content = f"{content}\n\n{proposal}\n\nEligible peers:\n{roster}"
        return PromptBlock(self.name, content)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if tool_name == "invoke_other":
            kwargs["_partner_group_context"] = context
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""

    def finish_instruction(self, context: UnifiedContext, final_text: str) -> str:
        """Canonicalize the answer, then permit one proposal only when allowed."""
        state = _state(context)
        if not state.get("formal_answer"):
            answer = str(final_text or "").strip()
            if not answer:
                return ""
            answer, removed_request = self._save_formal_answer(context, answer)
            group = context.metadata.get("partner_group")
            if not isinstance(group, dict) or not group.get("allow_invoke_other"):
                # An invoked reply must still pass through canonical cleanup,
                # but a fresh collaboration decision would violate one-hop.
                state["invocation_decided"] = True
                return ""
            # An answer-less early invoke_other already consumed the one
            # collaboration decision. Saving this recovery answer is required,
            # but sending the model through a fresh decision round is not.
            if state.get("invocation_decided"):
                return ""
            instruction = (
                "Your formal answer is now complete and saved. Do not rewrite or extend it. "
                "Decide whether one other Partner's answer would materially help the user. "
                "If yes, call invoke_other exactly once with one eligible peer and a standalone "
                "question. If no, reply with exactly NO_INVOKE. These are the only two valid "
                "actions in this private protocol round: never write a prose peer request, and "
                "never claim that the peer has answered."
            )
            if removed_request:
                instruction += (
                    " A prose @Partner question was removed from the published answer. If that "
                    "request is still useful, express it now through invoke_other instead: "
                    + removed_request[:600]
                )
            return instruction

        if state.get("invocation_decided"):
            return ""

        # A tool-less private response (NO_INVOKE or stray prose) also consumes
        # the decision; the runner restores the saved public answer instead.
        state["invocation_decided"] = True
        return ""

    def tool_round_output_policy(
        self,
        context: UnifiedContext,
        final_text: str,
        tool_names: tuple[str, ...],
    ) -> str:
        """Classify the one collaboration tool round as public or private.

        Some models emit their complete answer and ``invoke_other`` together,
        despite the requested two-step protocol. Treating that as an ordinary
        tool preamble made the tool reject the proposal, after which the model
        repeated the same answer until the loop budget was exhausted. Saving
        the prose here lets the tool see the formal answer before dispatch.
        """
        has_invoke = "invoke_other" in tool_names
        state = _state(context)
        formal_answer = str(state.get("formal_answer") or "").strip()
        group = context.metadata.get("partner_group")
        can_invoke = isinstance(group, dict) and bool(group.get("allow_invoke_other"))
        if not can_invoke and has_invoke:
            if not formal_answer:
                answer = str(final_text or "").strip()
                if answer:
                    self._save_formal_answer(context, answer)
            # The schema is statically capability-owned, so a disallowed model
            # call may still arrive. Consume it without exposing its prose or
            # opening another collaboration round.
            state["invocation_decided"] = True
            return "discard"
        if not formal_answer and has_invoke:
            answer = str(final_text or "").strip()
            if not answer:
                return "discard"
            answer, _removed_request = self._save_formal_answer(context, answer)
            if state.get("invocation_decided"):
                return "discard"
            context.capability_output.answer_published = True
            return "publish"

        if formal_answer and not state.get("invocation_decided"):
            # The finish guard promised exactly one private decision round. Any
            # tool choice consumes it, even if the model chose a different tool.
            if not has_invoke:
                state["invocation_decided"] = True
            return "discard"
        return ""

    def final_text_override(self, context: UnifiedContext, final_text: str) -> str | None:
        """Restore the saved answer after the bounded private decision round."""
        _ = final_text
        state = _state(context)
        if not state.get("invocation_decided"):
            return None
        answer = str(state.get("formal_answer") or "").strip()
        return answer or None

    @staticmethod
    def _save_formal_answer(context: UnifiedContext, answer: str) -> tuple[str, str]:
        cleaned, removed_request = _without_trailing_peer_request(context, answer)
        _state(context)["formal_answer"] = cleaned
        return cleaned, removed_request


def _without_trailing_peer_request(
    context: UnifiedContext,
    answer: str,
) -> tuple[str, str]:
    """Remove a final peer-addressed block so the approval tool is canonical."""
    group = context.metadata.get("partner_group")
    if not isinstance(group, dict):
        return answer, ""
    self_id = str(group.get("self_id") or "").lower()
    peer_ids: set[str] = set()
    for member in group.get("members") or []:
        if not isinstance(member, dict):
            continue
        partner_id = str(member.get("partner_id") or "").strip()
        if not partner_id or partner_id.lower() == self_id:
            continue
        peer_ids.add(partner_id.casefold())

    if not peer_ids:
        return answer, ""

    # The public-answer contract forbids an addressed peer request altogether.
    # Locate the final peer tag first, then cut at the nearest paragraph, line,
    # or sentence boundary before it. This treats wording around the tag as data
    # instead of trying to enumerate English/Chinese follow-up prefixes.
    tags = list(re.finditer(r"(?<![\w@])@([A-Za-z0-9][A-Za-z0-9_-]*)", answer))
    peer_tags = [tag for tag in tags if tag.group(1).casefold() in peer_ids]
    if not peer_tags:
        return answer, ""
    tag_start = peer_tags[-1].start()
    boundaries = [
        boundary.end() for boundary in re.finditer(r"\n\s*\n|\n|[.!?。！？]\s*", answer[:tag_start])
    ]
    if not boundaries:
        return answer, ""
    request_start = boundaries[-1]
    cleaned = answer[:request_start].strip()
    # A thematic break immediately before the removed request belongs to that
    # request card; retaining it would leave a confusing dangling separator.
    cleaned = re.sub(r"(?:^|\n)\s*(?:-{3,}|\*{3,}|_{3,})\s*$", "", cleaned).strip()
    candidate = answer[request_start:].strip()
    return (cleaned or answer), candidate


__all__ = ["PartnerGroupCapability"]
