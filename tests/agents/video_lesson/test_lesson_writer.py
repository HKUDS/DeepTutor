"""Parsing the lesson writer's reply into meta and code."""

from __future__ import annotations

import pytest

from deeptutor.agents.video_lesson.lesson_writer import LessonWriterAgent, parse_draft

REPLY = """```json
{"title": "Golden ratio", "summary": "Cobweb first, then the proof."}
```
```tsx
export const LESSON = {durationInFrames: 300, fps: 30, width: 1920, height: 1080};
export const Lesson = () => null;
```"""


def test_parse_draft_reads_meta_and_code() -> None:
    draft = parse_draft(REPLY)
    assert draft.title == "Golden ratio"
    assert draft.summary == "Cobweb first, then the proof."
    assert draft.code.startswith("export const LESSON")


def test_parse_draft_keeps_the_longest_code_block() -> None:
    reply = "```tsx\nconst a = 1;\n```\n" + REPLY
    assert "durationInFrames" in parse_draft(reply).code


@pytest.mark.parametrize("reply", ["no code at all", "```json\n{not json}\n```"])
def test_parse_draft_without_code_is_unusable(reply: str) -> None:
    draft = parse_draft(reply)
    assert draft.code == ""
    assert draft.title == ""


def test_writer_agent_starts_a_conversation_with_the_kit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "deeptutor.agents.base_agent.get_agent_params",
        lambda _: {"temperature": 0.7, "max_tokens": 16000},
    )
    agent = LessonWriterAgent(api_key="test", base_url="http://localhost", language="en")
    agent.start(user_input="Explain a cobweb plot", history="")
    system, user = agent._messages
    assert "export const Stage" in system["content"]
    assert "Explain a cobweb plot" in user["content"]


def test_parse_draft_reads_the_narration() -> None:
    reply = (
        '```json\n{"title": "t", "narration": [{"id": "s1", "text": "第一句。"}, {"id": "", "text": "x"}]}\n```\n'
        "```tsx\nexport const Lesson = () => null;\n```"
    )
    draft = parse_draft(reply)
    assert [(n.id, n.text) for n in draft.narration] == [("s1", "第一句。")]
