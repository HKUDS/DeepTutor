"""Book generation uses the admitted workspace, including concurrent operations."""

import asyncio
from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.book import generation_context as context


@pytest.mark.asyncio
async def test_agent_and_block_calls_share_frozen_owner_preferences(monkeypatch):
    from deeptutor.book.agents.ideation_agent import IdeationAgent
    from deeptutor.book.blocks import _llm_writer as writer

    owner = ContextVar("test_owner", default=("account", "a"))
    prefs = {"a": "Use visual examples", "b": "Use concise German"}
    monkeypatch.setattr(context, "_owner", owner.get)
    monkeypatch.setattr(context, "_instructions", lambda key: prefs[key[1]])
    seen = []

    async def streamed(self, user_prompt, system_prompt, **kwargs):
        seen.append(system_prompt)
        yield "answer"

    async def complete(**kwargs):
        seen.append(kwargs["system_prompt"])
        return "answer"

    monkeypatch.setattr(BaseAgent, "stream_llm", streamed)
    monkeypatch.setattr(writer, "llm_complete", complete)
    monkeypatch.setattr(
        writer,
        "get_llm_config",
        lambda: SimpleNamespace(model="fixture", api_key="", base_url="", binding="openai"),
    )

    async def run(workspace):
        token = owner.set(("account", workspace))
        try:
            with context.book_instruction_scope():
                prefs[workspace] += " edited later"
                await asyncio.sleep(0)
                agent = IdeationAgent()
                assert [x async for x in agent.stream_llm("question", "schema")] == ["answer"]
                await writer.llm_text(user_prompt="block", system_prompt="schema")
        finally:
            owner.reset(token)

    await asyncio.gather(run("a"), run("b"))
    assert len(seen) == 4
    assert all("edited later" not in value for value in seen)
    assert sum("Use visual examples" in value for value in seen) == 2
    assert sum("Use concise German" in value for value in seen) == 2
    assert all(value.count("[Workspace preferences]") == 1 for value in seen)
    # A different authenticated owner may not inherit a task's earlier snapshot.
    with context.book_instruction_scope():
        token = owner.set(("other-account", "b"))
        assert "Use concise German" in context.with_workspace_instructions("schema")
        owner.reset(token)
