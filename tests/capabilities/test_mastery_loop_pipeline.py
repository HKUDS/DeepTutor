"""The mastery loop is its own loop, assembled from the tutor's own prompt pack.

What these lock down is the split the pipeline exists for: the *protocol* half
of the prompt is the tutor's, while the *tool* half stays exactly what a chat
turn would get. Both directions have failed before — a tutoring mode that
inherits chat's playbook argues with it, and one that curates its own tool list
silently takes away a tool the learner turned on.
"""

from __future__ import annotations

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.mastery.loop import NATIVE_LOOP_FLAG, MasteryLoopCapability
from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline
from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.core.context import UnifiedContext


class _FakeRegistry:
    def build_prompt_text(self, *_args, **_kwargs) -> str:
        return "- tool"


@pytest.fixture(autouse=True)
def _stub_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.get_tool_registry",
        lambda: _FakeRegistry(),
    )


def _mastery_context() -> UnifiedContext:
    return UnifiedContext(
        metadata={
            "mastery_mode": True,
            "mastery_path_id": "p1",
            NATIVE_LOOP_FLAG: True,
        }
    )


@pytest.mark.parametrize(
    ("language", "tutor_phrase", "chat_phrase"),
    [
        ("zh", "掌握式导师", "你是 DeepTutor"),
        ("en", "mastery tutor", "You are DeepTutor"),
    ],
)
def test_tutor_identity_replaces_chat_identity(
    language: str, tutor_phrase: str, chat_phrase: str
) -> None:
    """The prompt opens as a tutor, not as DeepTutor-behaving-like-a-tutor."""
    prompt = MasteryLoopPipeline(language=language)._build_system_prompt([], _mastery_context())

    assert tutor_phrase in prompt
    assert chat_phrase not in prompt
    # Chat's exploring-loop protocol is what "posing a question ends the turn"
    # used to have to argue against; it is simply not in this prompt.
    assert "## mastery_loop" in prompt
    assert "## loop" not in prompt


def test_playbook_is_stated_once() -> None:
    """The foundation carries the playbook, so the extension must not add one.

    Two copies is not a cosmetic problem: the window pays for both, and the
    second one lands *below* the tool manifest, where a contradiction between
    the copies would be read last.
    """
    context = _mastery_context()
    prompt = MasteryLoopPipeline(language="en")._build_system_prompt([], context)

    assert prompt.count("## mastery_playbook") == 1
    assert "## mastery_tutor\n" in prompt
    assert MasteryLoopCapability().system_block(context, language="en", prompts={}) is None


def test_playbook_still_reaches_a_mastery_turn_running_on_chat() -> None:
    """A non-tutor action inside a mastery workspace still knows it is in one."""
    context = UnifiedContext(metadata={"mastery_mode": True, "mastery_path_id": "p1"})
    block = MasteryLoopCapability().system_block(context, language="en", prompts={})

    assert block is not None
    assert "mastery tutor" in block.content
    assert "mastery_quiz" in block.content


def test_tool_surface_matches_chat_plus_the_mastery_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entering a course never takes a tool away from the learner.

    The tutor's tools are *added* to whatever the same turn would have had in
    chat — the composer toggles the learner set, the same auto-mounts. A
    narrower surface may well be worth trying, but it has to be a deliberate
    override here, not a side effect of the mode.
    """
    composed: list[dict] = []

    def _record(**kwargs):
        composed.append(kwargs)
        return []

    monkeypatch.setattr("deeptutor.agents.loop.pipeline.compose_enabled_tools", _record)

    chat_context = UnifiedContext(metadata={})
    AgenticChatPipeline(language="en")._compose_enabled_tools(chat_context)
    MasteryLoopPipeline(language="en")._compose_enabled_tools(_mastery_context())

    chat_call, mastery_call = composed
    assert chat_call["optional_whitelist"] == mastery_call["optional_whitelist"]
    # The one difference is the capability's own tools, which the mastery turn
    # carries and the chat turn does not. Every mastery tool is mounted in every
    # mode on purpose — a mode can change inside a turn and a turn's schemas
    # cannot, so the mode is enforced when a tool runs (see
    # ``deeptutor.capabilities.mastery.mode``), not by withholding it here.
    assert set(mastery_call["capability_owned"]) >= {*MASTERY_TOOL_NAMES, "read_source"}
    assert not chat_call["capability_owned"]


def test_engine_copy_is_inherited_not_restated() -> None:
    """Notices and labels are engine copy; the tutor pack only overrides its own.

    Without the inherited base, a notice the engine emits (a retry, a snipped
    tool result) would fall back to its English default in the tutor loop only.
    """
    pack = MasteryLoopPipeline(language="zh")._prompts

    assert pack["notices"]["context_window_guard"]
    assert pack["labels"]["retrieve"]
    # Overridden by the tutor pack…
    assert "mastery_status" in pack["loop"]["system"]
    # …while the sibling keys chat defines survive the override.
    assert pack["loop"]["continue_truncated"]
