from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.capabilities.partner_authoring import PartnerAuthoringCapability
from deeptutor.capabilities.partner_authoring.binding import (
    is_partner_authoring_turn,
    partner_authoring_trigger,
)
from deeptutor.capabilities.partner_authoring.tools import ProposePartnerTool
from deeptutor.capabilities.registry import active_loop_capabilities
from deeptutor.core.context import UnifiedContext
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import user_context


def _context(message: str) -> UnifiedContext:
    return UnifiedContext(user_message=message, language="zh")


def test_partner_authoring_activation_requires_action_and_partner_object() -> None:
    assert is_partner_authoring_turn(_context("帮我创建一个严格但有耐心的数学学习伙伴"))
    assert is_partner_authoring_turn(_context("I want to build a Socratic tutor"))
    assert not is_partner_authoring_turn(_context("解释一下数学里的 partner function"))
    assert not is_partner_authoring_turn(_context("帮我创建一份复习计划"))
    partner_context = _context("帮我创建一个学习伙伴")
    partner_context.metadata["source"] = "partner"
    assert not is_partner_authoring_turn(partner_context)


@pytest.mark.parametrize(
    "message",
    [
        "Create a partner that quizzes me on French verbs",
        "I want a patient math tutor",
        "Can you make me a strict coach?",
        "Set up a new study buddy for physics",
        "我想要一个数学导师",
        "来个学习搭子",
        'Create a tutor named "Ada"',
        "I don't want a coach; create a tutor instead",
        "请不要创建一个伙伴，请帮我创建一个数学导师",
    ],
)
def test_partner_authoring_activates_on_a_creation_request(message: str) -> None:
    assert is_partner_authoring_turn(_context(message))


@pytest.mark.parametrize(
    "message",
    [
        "I want to file an issue about the Partner bug",
        "I want to report that Partner creation keeps triggering",
        "I need help understanding my tutor's feedback",
        "Make sure my tutor sees this",
        "Why can a flash-tier model answer well? The release notes mention Partner channels.",
        "我想提交一个关于伙伴功能的 bug",
        "生成的回答里提到了伙伴",
        "我需要解释一下，为什么会触发伙伴创建",
        "I don't want a tutor",
        "I do not need a partner",
        "Please don't create a partner",
        "I don't want you to create a tutor",
        "我不想要一个伙伴",
        "请不要创建一个伙伴",
        "我不想让你创建一个伙伴",
        'Why does "create a Partner" trigger here?',
        "The issue title is 'create a Partner'",
        "请解释“创建一个伙伴”为什么会误触发",
        "```text\ncreate a Partner\n```",
        "> create a Partner\nWhy did this trigger?",
        "Please add a companion-style tone to my summary",
        "Why does create a Partner trigger here?",
        "Create a Partner issue for me",
        "Can you make a partner checklist?",
        "请解释为什么创建一个伙伴会触发",
        "帮我创建一个伙伴功能的说明",
    ],
)
def test_partner_authoring_ignores_turns_that_only_mention_a_partner(message: str) -> None:
    context = _context(message)
    assert not is_partner_authoring_turn(context)
    assert "partner_authoring" not in {
        capability.name for capability in active_loop_capabilities(context)
    }


def test_explicit_partner_authoring_selection_still_routes_the_turn() -> None:
    context = _context("I don't want a tutor")
    context.active_capability = "partner_authoring"
    assert is_partner_authoring_turn(context)


def test_capability_forces_a_draft_before_finishing() -> None:
    capability = PartnerAuthoringCapability()
    context = _context("创建一个伙伴")
    context.active_capability = "partner_authoring"
    assert "propose_partner" in capability.finish_instruction(context, "好的")
    context.extension("partner_authoring")["draft_created"] = "draft"
    assert capability.finish_instruction(context, "完成") == ""


def test_heuristic_match_never_discards_a_written_answer() -> None:
    capability = PartnerAuthoringCapability()
    context = _context("Create a partner that quizzes me on French verbs")
    assert partner_authoring_trigger(context) == "heuristic"
    assert capability.finish_instruction(context, "A complete answer") == ""
    prompt = capability.system_block(context, language="en", prompts={})
    assert prompt is not None
    assert "First decide from the full request" in prompt.content
    assert "If they are asking about an existing Partner" in prompt.content


def test_explicit_selection_keeps_the_authoring_instruction() -> None:
    capability = PartnerAuthoringCapability()
    context = _context("Create a partner")
    context.active_capability = "partner_authoring"
    assert partner_authoring_trigger(context) == "explicit"
    prompt = capability.system_block(context, language="en", prompts={})
    assert prompt is not None
    assert "call `propose_partner` exactly once" in prompt.content
    assert "propose_partner" in capability.finish_instruction(context, "A description only")


@pytest.mark.asyncio
async def test_propose_partner_persists_user_scoped_reviewable_draft(tmp_path: Path) -> None:
    user = CurrentUser(
        id="u-alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u-alice", root=tmp_path / "alice"),
    )
    context = _context("创建一个数学伙伴")
    with user_context(user):
        result = await ProposePartnerTool().execute(
            name="欧拉",
            description="循序渐进的数学教练",
            soul="# Soul\nUse Socratic questions and verify each step.",
            language="zh",
            emoji="🧮",
            color="#3366AA",
            _partner_authoring_context=context,
        )

    assert result.success is True
    draft = result.metadata["partner_draft"]
    assert draft["name"] == "欧拉"
    assert draft["color"] == "#3366aa"
    assert draft["owner_id"] == "u-alice"
    assert context.extension("partner_authoring")["draft_created"] == draft["draft_id"]
    assert (tmp_path / "alice" / "user" / "partner_drafts" / f"{draft['draft_id']}.json").exists()
