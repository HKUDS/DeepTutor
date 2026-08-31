from __future__ import annotations

from deeptutor.multi_user.learner_profile import normalize_profile, prompt_block


def test_chat_prompt_assembler_emits_profile_as_its_own_block() -> None:
    from deeptutor.agents.chat.prompt_blocks import ChatPromptAssembler
    from deeptutor.core.context import UnifiedContext

    context = UnifiedContext(
        metadata={"learner_profile_prompt": prompt_block({"age": 8, "language": "zh-CN"})}
    )
    rendered = ChatPromptAssembler(prompts={}, language="en").system_prompt(
        context=context, tool_manifest=""
    )
    assert "## learner_profile" in rendered
    assert "Age: 8" in rendered


def test_profile_normalizes_optional_fields_and_keeps_age_independent() -> None:
    profile = normalize_profile({"age": 8, "grade_level": "primary_4", "language": "zh-CN"})
    assert profile == {
        "schema_version": 1,
        "age": 8,
        "grade_level": "primary_4",
        "language": "zh-CN",
    }


def test_profile_rejects_invalid_age_and_oversized_text() -> None:
    for value in ({"age": 2}, {"age": True}, {"grade_level": "x" * 81}):
        try:
            normalize_profile(value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid learner profile was accepted")


def test_prompt_block_is_empty_for_missing_profile_and_lists_trusted_values() -> None:
    assert prompt_block(None) == ""
    block = prompt_block({"age": 8, "grade_level": "primary_4"})
    assert "trusted learner profile" in block
    assert "Age: 8" in block
    assert "Grade level: primary_4" in block
