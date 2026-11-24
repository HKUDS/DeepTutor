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
async def test_loaded_tools_join_the_end_and_stay(_isolated_runtime: dict[str, bool]) -> None:
    chat = _Conversation(language="en")
    first = await chat.turn("find me an arxiv paper on teaching derivatives")
    result = first["pipeline"]._deferred_loader.load(["preprint", "inspect_setup"])
    assert result["loaded"] == ["preprint", "inspect_setup"]
    # The setup protocol travels with the setup tools, not in the system prompt.
    assert len(result["guides"]) == 1 and "inspect_setup" in result["guides"][0]
    first_tools = first["tools"]  # The live list the loader appended to.
    chat.previous["tools"] = json.loads(json.dumps(first_tools))
    assert first_tools[-2]["function"]["name"] == "preprint"

    second = await chat.turn("thanks")
    assert second["tools"] == first_tools
    third = await chat.turn("and once more")
    assert third["tools"] == first_tools
    assert third["system"] == first["system"]


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
