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


@pytest.mark.asyncio
async def test_book_agent_preserves_base_positional_arguments(monkeypatch):
    from deeptutor.book.agents.ideation_agent import IdeationAgent

    monkeypatch.setattr(context, "_owner", lambda: ("account", "workspace"))
    monkeypatch.setattr(context, "_instructions", lambda owner: "Use examples")
    messages = [{"role": "user", "content": "question"}]
    seen = []

    async def streamed(self, user_prompt, system_prompt, messages, temperature, **kwargs):
        seen.append((user_prompt, system_prompt, messages, temperature, kwargs))
        yield "streamed"

    async def completed(self, user_prompt, system_prompt, messages, response_format, **kwargs):
        seen.append((user_prompt, system_prompt, messages, response_format, kwargs))
        return "completed"

    monkeypatch.setattr(BaseAgent, "stream_llm", streamed)
    monkeypatch.setattr(BaseAgent, "call_llm", completed)
    agent = IdeationAgent()
    assert [
        chunk async for chunk in agent.stream_llm("q", "schema", messages, 0.3, stage="outline")
    ] == ["streamed"]
    assert (
        await agent.call_llm("q", "schema", messages, {"type": "json_object"}, stage="outline")
        == "completed"
    )
    assert len(seen) == 2
    assert all(row[0] == "q" and "Use examples" in row[1] for row in seen)
    assert all(row[2] is messages and row[4]["stage"] == "outline" for row in seen)
    assert seen[0][3] == 0.3
    assert seen[1][3] == {"type": "json_object"}
