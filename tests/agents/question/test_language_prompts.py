from __future__ import annotations

from typing import Any

import pytest

from deeptutor.agents.question.agents.followup_agent import FollowupAgent


class CaptureFollowupAgent(FollowupAgent):
    """``FollowupAgent`` subclass that records every system prompt sent to
    the LLM (so the language-directive injection can be asserted), while
    short-circuiting the actual network call."""

    def __init__(self, language: str = "zh") -> None:
        self.language = language
        self.prompts: dict[str, Any] = {
            "system": "Followup system",
            "answer_followup": (
                "Question context:\n{question_context}\n\n"
                "Conversation history:\n{history_context}\n\n"
                "User follow-up:\n{user_message}\n"
            ),
        }
        self.captured_system_prompts: list[str] = []

    async def stream_llm(self, **kwargs):  # type: ignore[override]
        self.captured_system_prompts.append(str(kwargs["system_prompt"]))
        yield "已回答"


@pytest.mark.asyncio
async def test_followup_agent_appends_language_directive_to_system_prompt() -> None:
    agent = CaptureFollowupAgent(language="zh")

    reply = await agent.process(
        user_message="为什么这题是这个答案？",
        question_context={
            "question_id": "q_1",
            "question_type": "choice",
            "question": "矩阵乘法什么时候有定义？",
            "correct_answer": "当内维度一致时。",
            "explanation": "矩阵 A 的列数必须等于矩阵 B 的行数。",
        },
        history_context="",
    )

    assert reply == "已回答"
    assert agent.captured_system_prompts
    assert "Followup system" in agent.captured_system_prompts[0]
    assert "请严格使用中文（简体）" in agent.captured_system_prompts[0]
