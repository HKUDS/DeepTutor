from __future__ import annotations

import pytest

from deeptutor.capabilities.partner_group import PartnerGroupCapability
from deeptutor.capabilities.partner_group.tools import InvokeOtherTool
from deeptutor.core.context import UnifiedContext


def _context(*, allow: bool = True) -> UnifiedContext:
    return UnifiedContext(
        user_message="Discuss this",
        metadata={
            "source": "partner",
            "partner_group": {
                "group_id": "panel",
                "name": "Panel",
                "self_id": "ada",
                "allow_invoke_other": allow,
                "members": [
                    {"partner_id": "ada", "name": "Ada"},
                    {"partner_id": "bob", "name": "Bob"},
                ],
            },
        },
    )


def test_group_capability_saves_formal_answer_before_decision_round() -> None:
    capability = PartnerGroupCapability()
    context = _context()

    assert capability.is_active(context) is True
    instruction = capability.finish_instruction(context, "My complete answer")
    assert "invoke_other" in instruction
    assert context.extension("partner_group")["formal_answer"] == "My complete answer"

    assert capability.finish_instruction(context, "NO_INVOKE") == ""
    assert context.extension("partner_group")["invocation_decided"] is True
    assert PartnerGroupCapability().is_active(_context(allow=False)) is True
    assert PartnerGroupCapability().is_active(UnifiedContext()) is False


def test_trailing_prose_peer_question_is_removed_in_favor_of_tool_proposal() -> None:
    capability = PartnerGroupCapability()
    context = _context()
    answer = "My actual conclusion.\n\n**@Bob，你会挑战哪个假设？**"

    instruction = capability.finish_instruction(context, answer)

    assert context.extension("partner_group")["formal_answer"] == "My actual conclusion."
    assert "invoke_other" in instruction
    assert "@Bob" in instruction


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            "My actual conclusion.\n\nFollow-up for @bob: Bob, how would you test it?",
            "My actual conclusion.",
        ),
        (
            "我的正式回答。\n\n追问 Bob： @bob ，如果学生连续三次都没领会，你会怎么办？",
            "我的正式回答。",
        ),
        (
            "My actual conclusion. Follow-up for @bob: Bob, how would you test it?",
            "My actual conclusion.",
        ),
        (
            "我的正式回答。追问 Bob： @bob ，如果学生连续三次都没领会，你会怎么办？",
            "我的正式回答。",
        ),
    ],
)
def test_real_world_trailing_peer_request_shapes_are_removed(
    answer: str,
    expected: str,
) -> None:
    capability = PartnerGroupCapability()
    context = _context()

    instruction = capability.finish_instruction(context, answer)

    assert context.extension("partner_group")["formal_answer"] == expected
    assert "only two valid actions" in instruction


def test_group_protocol_forbids_peer_requests_in_the_first_response() -> None:
    block = PartnerGroupCapability().system_block(_context(), language="en", prompts={})

    assert block is not None
    assert "public formal answer" in block.content
    assert "never write the peer request as prose" in block.content


def test_invoked_reply_keeps_cleanup_without_advertising_another_invocation() -> None:
    capability = PartnerGroupCapability()
    context = _context(allow=False)
    answer = (
        "My complete answer for the user.\n\n"
        "---\n\n"
        "**想请教一下 @bob：**\n"
        "从另一个角度看，你还会补充什么？"
    )

    block = capability.system_block(context, language="zh", prompts={})
    instruction = capability.finish_instruction(context, answer)

    assert block is not None
    assert "不得出现任何面向同伴的追问" in block.content
    assert "invoke_other" not in block.content
    assert "NO_INVOKE" not in block.content
    assert "Eligible peers" not in block.content
    assert instruction == ""
    assert context.extension("partner_group")["invocation_decided"] is True
    assert context.extension("partner_group")["formal_answer"] == "My complete answer for the user."
    assert capability.final_text_override(context, answer) == "My complete answer for the user."


@pytest.mark.asyncio
async def test_invoke_other_requires_saved_answer_and_records_only_a_proposal() -> None:
    tool = InvokeOtherTool()
    early_context = _context()

    early = await tool.execute(
        target_partner_id="bob",
        question="What do you think?",
        _partner_group_context=early_context,
    )
    assert early.success is False
    assert early.terminate_turn is False
    assert early_context.extension("partner_group")["invocation_decided"] is True
    capability = PartnerGroupCapability()
    assert capability.finish_instruction(early_context, "Recovered formal answer") == ""
    assert capability.final_text_override(early_context, "ignored") == "Recovered formal answer"

    context = _context()
    context.extension("partner_group")["formal_answer"] = "Finished"
    result = await tool.execute(
        target_partner_id="bob",
        question="Which assumption would you challenge?",
        _partner_group_context=context,
    )
    assert result.success is True
    assert result.metadata["partner_invocation"] == {
        "target_partner_id": "bob",
        "target_partner_name": "Bob",
        "question": "Which assumption would you challenge?",
    }
    assert context.extension("partner_group")["invocation_proposal"]["target_partner_id"] == "bob"

    duplicate = await tool.execute(
        target_partner_id="bob",
        question="Ask again",
        _partner_group_context=context,
    )
    assert duplicate.success is False
    assert duplicate.terminate_turn is True
    assert "do not rewrite" in duplicate.content


@pytest.mark.asyncio
async def test_repeated_answerless_invoke_other_is_terminal() -> None:
    context = _context()
    tool = InvokeOtherTool()

    first = await tool.execute(
        target_partner_id="bob",
        question="What do you think?",
        _partner_group_context=context,
    )
    repeated = await tool.execute(
        target_partner_id="bob",
        question="Trying again",
        _partner_group_context=context,
    )

    assert first.terminate_turn is False
    assert repeated.success is False
    assert repeated.terminate_turn is True
    assert "do not call invoke_other" in repeated.content


@pytest.mark.asyncio
async def test_invoke_other_rejects_self_and_unknown_targets() -> None:
    context = _context()
    context.extension("partner_group")["formal_answer"] = "Finished"
    tool = InvokeOtherTool()

    self_call = await tool.execute(
        target_partner_id="ada",
        question="Can I ask myself?",
        _partner_group_context=context,
    )
    unknown = await tool.execute(
        target_partner_id="eve",
        question="Can Eve answer?",
        _partner_group_context=context,
    )
    assert self_call.success is False
    assert unknown.success is False
    assert self_call.terminate_turn is True
    assert unknown.terminate_turn is True


@pytest.mark.asyncio
async def test_invoked_reply_tool_call_is_refused_and_cannot_chain() -> None:
    context = _context(allow=False)
    context.extension("partner_group")["formal_answer"] = "The invoked answer."

    result = await InvokeOtherTool().execute(
        target_partner_id="bob",
        question="Can this create another hop?",
        _partner_group_context=context,
    )

    assert result.success is False
    assert result.terminate_turn is True
    assert "cannot create another Partner proposal" in result.content
    assert "invocation_proposal" not in context.extension("partner_group")


def test_answer_and_invoke_in_one_tool_round_saves_and_publishes_answer_once() -> None:
    context = _context()
    capability = PartnerGroupCapability()

    policy = capability.tool_round_output_policy(
        context,
        "My complete answer.",
        ("invoke_other",),
    )

    assert policy == "publish"
    assert context.extension("partner_group")["formal_answer"] == "My complete answer."
    assert context.capability_output.answer_published is True


def test_any_tool_call_consumes_the_single_private_decision_round() -> None:
    context = _context()
    capability = PartnerGroupCapability()
    capability.finish_instruction(context, "My complete answer.")

    policy = capability.tool_round_output_policy(
        context,
        "My complete answer repeated by the model.",
        ("web_search",),
    )

    assert policy == "discard"
    assert context.extension("partner_group")["invocation_decided"] is True
    assert capability.final_text_override(context, "anything") == "My complete answer."


def test_invoked_reply_can_still_use_ordinary_tools() -> None:
    context = _context(allow=False)
    capability = PartnerGroupCapability()

    policy = capability.tool_round_output_policy(
        context,
        "I will inspect the source first.",
        ("web_search",),
    )

    assert policy == ""
    assert "formal_answer" not in context.extension("partner_group")
    assert "invocation_decided" not in context.extension("partner_group")


def test_invoked_reply_combined_with_forbidden_invoke_is_canonicalized() -> None:
    context = _context(allow=False)
    capability = PartnerGroupCapability()

    policy = capability.tool_round_output_policy(
        context,
        "The invoked answer.\n\n---\n\n@bob: can you add more?",
        ("invoke_other",),
    )

    assert policy == "discard"
    assert context.extension("partner_group")["formal_answer"] == "The invoked answer."
    assert context.extension("partner_group")["invocation_decided"] is True
    assert capability.final_text_override(context, "ignored") == "The invoked answer."
    assert "invocation_proposal" not in context.extension("partner_group")
