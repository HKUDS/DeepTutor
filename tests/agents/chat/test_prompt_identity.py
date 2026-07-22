"""The general block swaps product identity for a partner's user-given one."""

from __future__ import annotations

from pathlib import Path

import yaml

from deeptutor.agents.chat.prompt_blocks import ChatPromptAssembler
from deeptutor.core.context import UnifiedContext

PROMPTS = {
    "general": "You are DeepTutor, an interactive tutor.",
    "general_partner": 'You are a companion created by the user. The name the user gave you is "{name}".',
    "general_partner_description": "The user's description of you: {description}",
    "partner_turn_policy": "Partner tutoring policy.",
    "runtime_policy": "policy",
    "loop": {"system": "loop"},
}


def _general_block(context: UnifiedContext) -> str:
    assembler = ChatPromptAssembler(prompts=PROMPTS, language="en")
    blocks = assembler.blocks(context=context, tool_manifest="- none")
    return next(b.content for b in blocks if b.name == "general")


def test_chat_turn_keeps_product_identity():
    content = _general_block(UnifiedContext(user_message="hi"))
    assert content == "You are DeepTutor, an interactive tutor."


def test_partner_identity_replaces_general():
    context = UnifiedContext(
        user_message="hi",
        metadata={"agent_identity": {"name": "frank", "description": "study buddy"}},
    )
    content = _general_block(context)
    assert "DeepTutor" not in content
    assert 'The name the user gave you is "frank"' in content
    assert "The user's description of you: study buddy" in content


def test_partner_identity_without_description():
    context = UnifiedContext(
        user_message="hi",
        metadata={"agent_identity": {"name": "frank"}},
    )
    content = _general_block(context)
    assert (
        content == 'You are a companion created by the user. The name the user gave you is "frank".'
    )


def test_partner_turn_policy_block_is_added_for_partner():
    assembler = ChatPromptAssembler(prompts=PROMPTS, language="en")
    context = UnifiedContext(
        user_message="hi",
        metadata={"agent_identity": {"name": "frank"}},
    )
    blocks = assembler.blocks(context=context, tool_manifest="- none")
    policy = next(b for b in blocks if b.name == "partner_turn_policy")
    assert policy.content == "Partner tutoring policy."


def test_partner_turn_policy_not_added_for_plain_chat():
    assembler = ChatPromptAssembler(prompts=PROMPTS, language="en")
    blocks = assembler.blocks(context=UnifiedContext(user_message="hi"), tool_manifest="- none")
    assert all(b.name != "partner_turn_policy" for b in blocks)


def test_blank_identity_falls_back_to_product():
    context = UnifiedContext(
        user_message="hi",
        metadata={"agent_identity": {"name": "  "}},
    )
    assert _general_block(context) == "You are DeepTutor, an interactive tutor."


def test_shipped_yaml_carries_partner_templates():
    root = Path(__file__).resolve().parents[3] / "deeptutor/agents/chat/prompts"
    for lang in ("en", "zh"):
        data = yaml.safe_load((root / lang / "agentic_chat.yaml").read_text())
        assert "{name}" in data["general_partner"]
        assert "{description}" in data["general_partner_description"]
        assert "partner_turn_policy" in data
