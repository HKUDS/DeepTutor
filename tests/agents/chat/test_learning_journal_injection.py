"""Carried-over learning state reaches the system prompt without a tool call (#740).

Stage 1 only advertised the journal through ``learning_status``, so a learner
who opened a new conversation and said "继续上次那个" got a tutor that had to
think to look. These tests pin stage 2: the snapshot the turn executor takes
before the loop runs mounts as its own block, right beside memory.
"""

from __future__ import annotations

from deeptutor.agents.chat.prompt_blocks import ChatPromptAssembler
from deeptutor.core.context import UnifiedContext

PROMPTS = {
    "general": "You are DeepTutor, an interactive tutor.",
    "runtime_policy": "policy",
    "loop": {"system": "loop"},
}

SNAPSHOT = "# Learning journal\n\n## Mission\n- Topic: Fourier transform"


def _blocks(context: UnifiedContext) -> list[str]:
    assembler = ChatPromptAssembler(prompts=PROMPTS, language="en")
    return [b.name for b in assembler.blocks(context=context, tool_manifest="- none")]


def test_journal_snapshot_mounts_as_its_own_block():
    names = _blocks(UnifiedContext(user_message="继续", learning_journal_context=SNAPSHOT))
    assert "learning_journal" in names


def test_journal_block_sits_with_memory_not_behind_a_tool_call():
    names = _blocks(
        UnifiedContext(
            user_message="继续",
            memory_context="## Preferences",
            learning_journal_context=SNAPSHOT,
        )
    )
    assert names.index("learning_journal") == names.index("memory") + 1


def test_empty_journal_mounts_nothing():
    assert "learning_journal" not in _blocks(UnifiedContext(user_message="hi"))


def test_system_prompt_keeps_the_snapshot_verbatim():
    assembler = ChatPromptAssembler(prompts=PROMPTS, language="en")
    context = UnifiedContext(user_message="继续", learning_journal_context=SNAPSHOT)
    prompt = assembler.system_prompt(context=context, tool_manifest="- none")
    assert SNAPSHOT in prompt
