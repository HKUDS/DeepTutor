from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.capabilities.partner_authoring import PartnerAuthoringCapability
from deeptutor.capabilities.partner_authoring.binding import is_partner_authoring_turn
from deeptutor.capabilities.partner_authoring.tools import ProposePartnerTool
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


def test_capability_forces_a_draft_before_finishing() -> None:
    capability = PartnerAuthoringCapability()
    context = _context("创建一个伙伴")
    assert "propose_partner" in capability.finish_instruction(context, "好的")
    context.extension("partner_authoring")["draft_created"] = "draft"
    assert capability.finish_instruction(context, "完成") == ""


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
