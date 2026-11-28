"""``tools[]`` and the system prompt stay put across the turns of one chat.

Both sit at the very start of the provider's prompt-cache key. Before this
was pinned, a single conversation rewrote them on ordinary messages:

* the first turn of an unconfigured install mounted the four setup tools and a
  ~1k-token ``## setup`` system block (``intro``), and the second turn removed
  them again;
* "把语言切换成中文" mounted them again (``intent``);
* "论文" mounted the three research tools for that one message;
* a first favorite / saved question mid-conversation added a tool, and losing
  it again removed one.

Each of those turned the whole request into a cache miss. These tests drive the
real chat pipeline's tool assembly through such a conversation and require
every turn's ``tools[]`` to equal — or only extend — the previous turn's, and
the system prompt to be byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.setup import SETUP_TOOL_NAMES
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext
from deeptutor.tools.research_tools import SCIENTIFIC_TOOL_NAMES

SESSION = "stable-tools-session"


@pytest.fixture(autouse=True)
def _isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, bool]:
    from deeptutor.services.path_service import PathService

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(PathService, "_instance", paths)
    paths.ensure_all_directories()
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai",
            model="gpt-test",
            api_key="k",
            base_url="u",
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
        ),
    )
    # The user's data, switchable mid-conversation.
    data = {"notebooks": False, "question_bank": False}
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.user_has_notebooks", lambda: data["notebooks"]
    )
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.user_has_question_bank", lambda: data["question_bank"]
    )
    return data


class _Conversation:
    """Runs consecutive turns of one session the way ``run()`` assembles them."""

    def __init__(self, *, language: str = "zh") -> None:
        self.language = language
        self.history: list[dict[str, Any]] = []
        self.previous: dict[str, Any] | None = None

    async def turn(self, message: str, **context_kwargs: Any) -> dict[str, Any]:
        pipeline = AgenticChatPipeline(language=self.language)
        context = UnifiedContext(
            session_id=SESSION,
            user_message=message,
            language=self.language,
            conversation_history=list(self.history),
            runtime=TurnRuntimeContext(previous_model_turn=self.previous),
            **context_kwargs,
        )
        await pipeline._prepare_deferred_tools(context)
        pipeline._exec_enabled = False
        enabled = pipeline._compose_enabled_tools(context)
        schemas = pipeline._turn_tool_schemas(enabled, context)
        system = pipeline._build_system_prompt(enabled, context)
        note = pipeline._capability_pre_loop_seed(context)
        self.previous = {"tools": json.loads(json.dumps(schemas)), "system": system}
        self.history += [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "ok"},
        ]
        return {
            "pipeline": pipeline,
            "tools": schemas,
            "names": [item["function"]["name"] for item in schemas],
            "system": system,
            "note": note,
            "manifest": pipeline._deferred_tools_manifest(),
            "tool_manifest": pipeline._tool_manifest(enabled),
        }


def _only_extends(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> bool:
    return json.dumps(after[: len(before)]) == json.dumps(before)


@pytest.mark.asyncio
async def test_one_conversation_keeps_tools_and_system_stable(
    _isolated_runtime: dict[str, bool],
) -> None:
    chat = _Conversation()

    # Turn 1: a fresh install's first conversation — the setup intro fires.
    first = await chat.turn("什么是导数？")
    assert not set(SETUP_TOOL_NAMES) & set(first["names"])
    assert not set(SCIENTIFIC_TOOL_NAMES) & set(first["names"])
    assert "load_tools" in first["names"]
    assert "## setup" not in first["system"]
    # The product behaviour survives: the model hears about the blocking gap.
    assert "这是用户的第一次对话" in first["note"]
    assert "这个实例目前缺少的配置" in first["note"]
    # Every deferred tool is listed in the catalog from the first turn on.
    for name in (*SETUP_TOOL_NAMES, *SCIENTIFIC_TOOL_NAMES):
        assert name in first["manifest"]

    # Turn 2: the research regex only earns a hint.
    paper = await chat.turn("请帮我找一篇关于导数教学的论文")
    assert paper["tools"] == first["tools"]
    assert paper["system"] == first["system"]
    assert paper["manifest"] == first["manifest"]
    assert "load_tools" in paper["note"] and "preprint" in paper["note"]

    # Turn 3: a configuration request only earns a note.
    switch = await chat.turn("把语言切换成中文")
    assert switch["tools"] == first["tools"]
    assert switch["system"] == first["system"]
    assert "load_tools" in switch["note"] and "apply_setting" in switch["note"]
    assert "第一次对话" not in switch["note"], "the intro is offered once"

    # Turn 4: the user's first favorite and saved question appear.
    _isolated_runtime.update(notebooks=True, question_bank=True)
    data = await chat.turn("那二阶导数呢？")
    assert _only_extends(switch["tools"], data["tools"])
    assert {"list_favorites", "save_favorite", "question_bank"} <= set(data["names"])
    assert data["system"] == first["system"]
    assert not data["note"]

    # Turn 5: the data is gone again — the tools stay for this conversation.
    _isolated_runtime.update(notebooks=False, question_bank=False)
    after = await chat.turn("谢谢，再举个例子")
    assert after["tools"] == data["tools"]
    assert after["system"] == first["system"]


@pytest.mark.asyncio
async def test_loading_a_tool_leaves_tools_unchanged_and_call_tool_reaches_it(
    _isolated_runtime: dict[str, bool],
) -> None:
    """``load_tools`` used to append the schema to ``tools[]`` mid-turn.

    ``tools[]`` comes first in the provider's cache key, so the very next
    request re-processed the system prompt and the whole history. The schema
    now arrives in the ``load_tools`` result and ``call_tool`` reaches it.
    """
    from deeptutor.tools.builtin import LoadToolsTool

    chat = _Conversation(language="en")
    first = await chat.turn("find me an arxiv paper on teaching derivatives")
    assert "call_tool" in first["names"]
    before = json.dumps(first["tools"])
    loader = first["pipeline"]._deferred_loader
    result = await LoadToolsTool().execute(names=["preprint", "inspect_setup"], _tool_loader=loader)
    assert json.dumps(first["tools"]) == before, "loading must not touch tools[]"
    assert result.metadata["loaded"] == ["preprint", "inspect_setup"]
    assert "call_tool" in result.content
    definitions = [
        json.loads(line) for line in result.content.splitlines() if line.startswith('{"name"')
    ]
    assert [item["name"] for item in definitions] == ["preprint", "inspect_setup"]
    assert all("parameters" in item for item in definitions)
    # The setup protocol still travels with the setup tools.
    assert len(result.metadata["guides"]) == 1
    assert result.metadata["guides"][0] in result.content

    calls, renamed = first["pipeline"]._resolve_proxied_tool_calls(
        [
            {
                "id": "c1",
                "name": "call_tool",
                "arguments": json.dumps({"name": "preprint", "arguments": {"query": "x"}}),
            },
            # Not loaded: left for ``CallToolTool`` to refuse.
            {
                "id": "c2",
                "name": "call_tool",
                "arguments": json.dumps({"name": "apply_setting", "arguments": {}}),
            },
            {"id": "c3", "name": "web_fetch", "arguments": "{}"},
        ]
    )
    assert [call["name"] for call in calls] == ["preprint", "call_tool", "web_fetch"]
    assert json.loads(calls[0]["arguments"]) == {"query": "x"}
    assert renamed == {"c1"}

    # Later turns keep the same tools[] and still reach the loaded tools.
    second = await chat.turn("thanks")
    assert json.dumps(second["tools"]) == before
    assert second["pipeline"]._deferred_loader.callable_through_proxy("preprint")
    again = second["pipeline"]._deferred_loader.load(["preprint"])
    assert again["already_loaded"] == ["preprint"]
    # A model that lost the definition to compaction can read it again.
    assert [item["name"] for item in again["schemas"]] == ["preprint"]
    third = await chat.turn("and once more")
    assert json.dumps(third["tools"]) == before
    assert third["system"] == first["system"]


@pytest.mark.asyncio
async def test_tools_reached_through_call_tool_stay_out_of_the_text_tool_list(
    _isolated_runtime: dict[str, bool],
) -> None:
    """The text tool list (sent as a runtime snapshot when native schemas are
    not trusted) used to list proxied tools beside the real ones: that invited
    a direct call to a tool missing from ``tools[]``, and every load grew the
    list, so another full copy of it was appended to the history."""
    from deeptutor.tools.builtin import LoadToolsTool

    chat = _Conversation(language="en")
    first = await chat.turn("find me an arxiv paper on teaching derivatives")
    await LoadToolsTool().execute(
        names=["research_lit"], _tool_loader=first["pipeline"]._deferred_loader
    )
    second = await chat.turn("thanks")
    assert "research_lit" not in second["tool_manifest"]
    assert second["tool_manifest"] == first["tool_manifest"]
    # The catalog still names it, so a model that lost the definition to
    # compaction or snipping knows to call ``load_tools`` again.
    assert "research_lit" in second["manifest"]


@pytest.mark.asyncio
async def test_runtime_loads_still_land_in_tools(_isolated_runtime: dict[str, bool]) -> None:
    """A runtime-driven ``native`` load (mastery entering outline) mounts the
    schemas: the next turn would mount those tools eagerly anyway."""
    chat = _Conversation(language="en")
    first = await chat.turn("hello")
    loader = first["pipeline"]._deferred_loader
    loader.load(["preprint"])  # proxied first
    outcome = loader.load(["preprint", "research_lit"], native=True)
    assert outcome["schemas"] == []
    names = [item["function"]["name"] for item in first["tools"]]
    assert names[-2:] == ["preprint", "research_lit"]
    chat.previous["tools"] = json.loads(json.dumps(first["tools"]))

    second = await chat.turn("thanks")
    assert second["tools"] == first["tools"]


@pytest.mark.asyncio
async def test_typescript_engine_keeps_loading_into_tools(
    _isolated_runtime: dict[str, bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPTUTOR_CHAT_ENGINE", "typescript-native")
    chat = _Conversation(language="en")
    first = await chat.turn("hello")
    assert "call_tool" not in first["names"]
    outcome = first["pipeline"]._deferred_loader.load(["preprint"])
    assert outcome["loaded"] == ["preprint"] and outcome["schemas"] == []
    assert first["tools"][-1]["function"]["name"] == "preprint"


def test_recording_the_loaded_set_keeps_the_proxied_subset(
    _isolated_runtime: dict[str, bool],
) -> None:
    from deeptutor.services.mcp import load_proxied_tools, record_loaded_tools

    record_loaded_tools(SESSION, {"a", "b"}, proxied={"a"})
    # Writers that only know the loaded set (an eagerly opened mode) keep it.
    record_loaded_tools(SESSION, {"a", "b", "c"})
    assert load_proxied_tools(SESSION) == {"a"}
    record_loaded_tools(SESSION, {"b"})
    assert load_proxied_tools(SESSION) == set()


@pytest.mark.asyncio
async def test_call_tool_refuses_what_it_cannot_forward() -> None:
    from deeptutor.tools.builtin import CallToolTool

    result = await CallToolTool().execute(name="apply_setting", arguments={})
    assert not result.success and "load_tools" in result.content


@pytest.mark.asyncio
async def test_opening_setup_mode_loads_the_tools_once_and_never_touches_system(
    _isolated_runtime: dict[str, bool],
) -> None:
    chat = _Conversation(language="en")
    plain = await chat.turn("hello")
    opened = await chat.turn("show me my settings", active_capability="setup")
    assert _only_extends(plain["tools"], opened["tools"])
    assert set(SETUP_TOOL_NAMES) <= set(opened["names"])
    assert opened["system"] == plain["system"]
    # The rules arrive once, with the tools.
    assert "inspect_setup" in opened["note"] and "setup mode" in opened["note"]

    again = await chat.turn("and the language?", active_capability="setup")
    assert again["tools"] == opened["tools"]
    assert again["system"] == plain["system"]

    left = await chat.turn("back to calculus")
    assert left["tools"] == opened["tools"]
    assert left["system"] == plain["system"]
    assert not left["note"]


@pytest.mark.asyncio
async def test_unchanged_toggles_give_byte_identical_tools(
    _isolated_runtime: dict[str, bool],
) -> None:
    chat = _Conversation()
    first = await chat.turn("hi", enabled_tools=["web_search", "reason"])
    second = await chat.turn("论文", enabled_tools=["web_search", "reason"])
    assert json.dumps(second["tools"]) == json.dumps(first["tools"])
    # Turning a tool off is the user's call: its schema leaves (one miss).
    third = await chat.turn("hi", enabled_tools=["web_search"])
    assert "reason" not in third["names"]
    fourth = await chat.turn("hi again", enabled_tools=["web_search"])
    assert json.dumps(fourth["tools"]) == json.dumps(third["tools"])


@pytest.mark.asyncio
async def test_a_call_tool_round_runs_the_named_tool_and_keeps_the_models_call(
    _isolated_runtime: dict[str, bool],
) -> None:
    from deeptutor.agents.loop.loop_host import AgentLoopHost

    chat = _Conversation(language="en")
    turn = await chat.turn("hello")
    pipeline = turn["pipeline"]
    pipeline._deferred_loader.load(["preprint"])
    dispatched: list[dict[str, Any]] = []

    async def fake_dispatch(*, tool_calls, **_kwargs):
        dispatched.extend(tool_calls)
        return SimpleNamespace(
            sources=[],
            tool_messages=[
                {"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": "ok"}
                for call in tool_calls
            ],
            model_messages=[],
            pause=None,
        )

    async def no_op(*_args, **_kwargs):
        return None

    pipeline._dispatch_tool_calls = fake_dispatch
    model_call = {
        "id": "c1",
        "name": "call_tool",
        "arguments": json.dumps({"name": "preprint", "arguments": {"query": "x"}}),
    }
    host = AgentLoopHost.__new__(AgentLoopHost)
    host.pipeline = pipeline
    host.context = UnifiedContext(session_id=SESSION, user_message="hello", language="en")
    host.stream = None
    host.messages = []
    host.state = SimpleNamespace(tool_steps=0, sources=[])
    host.loop = SimpleNamespace(
        _clean=lambda text: text,
        _discard_deferred_output=no_op,
        _release_deferred_output=no_op,
        stage="exploring",
        _transient_model_messages=[],
    )
    host.result = SimpleNamespace(
        text="",
        tool_calls=[model_call],
        reasoning_content="",
        thinking_blocks=None,
        finish_reason="tool_calls",
        response_output_items=None,
    )
    await host.dispatch_tools()

    assert [call["name"] for call in dispatched] == ["preprint"]
    assert json.loads(dispatched[0]["arguments"]) == {"query": "x"}
    assistant, tool_message = host.messages
    # The replayed history is what the model emitted, byte for byte.
    assert assistant["tool_calls"][0]["function"]["name"] == "call_tool"
    assert assistant["tool_calls"][0]["function"]["arguments"] == model_call["arguments"]
    assert tool_message["tool_call_id"] == "c1" and tool_message["name"] == "call_tool"


@pytest.mark.asyncio
async def test_a_turn_without_the_research_module_never_imports_it(
    _isolated_runtime: dict[str, bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A minimal install has no ``deeptutor.tools.research_tools``.

    The setup tools alone are deferred there, and building the turn's notes for
    them must not reach for the research module.
    """
    import sys

    from deeptutor.modules import catalog

    real_enabled = catalog.module_enabled

    def enabled(name: str, *args: Any, **kwargs: Any) -> bool:
        return name != "research" and real_enabled(name, *args, **kwargs)

    monkeypatch.setattr(catalog, "module_enabled", enabled)
    # ``None`` in sys.modules makes any import of the module raise ImportError.
    monkeypatch.setitem(sys.modules, "deeptutor.tools.research_tools", None)

    chat = _Conversation()
    first = await chat.turn("请帮我找一篇关于导数教学的论文")
    assert "load_tools" in first["names"]
    assert not set(SCIENTIFIC_TOOL_NAMES) & set(first["names"])
    # The setup tools are still offered on demand, the research hint is not.
    assert "inspect_setup" in first["manifest"]
    assert "preprint" not in first["note"]
