from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.agents.chat.chat_agent import ChatAgent
from deeptutor.agents.chat.prompt_blocks import ChatPromptAssembler


@pytest.fixture(autouse=True)
def _fake_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(
        binding="openai",
        model="gpt-test",
        api_key="sk-test",
        base_url="https://example.test/v1",
        api_version=None,
    )
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: cfg,
    )
    monkeypatch.setattr("deeptutor.agents.base_agent.get_llm_config", lambda: cfg)


def test_agentic_chat_final_prompt_uses_selected_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRegistry:
        def build_prompt_text(self, *_args, **_kwargs) -> str:
            return "- tool"

    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_tool_registry",
        lambda: FakeRegistry(),
    )

    from deeptutor.core.context import UnifiedContext

    ctx = UnifiedContext()
    zh_prompt = AgenticChatPipeline(language="zh")._build_system_prompt([], ctx)
    en_prompt = AgenticChatPipeline(language="en")._build_system_prompt([], ctx)

    # Prompt blocks are phase-specific, but the shared language directive
    # still runs at the end, so per-language imperatives must surface.
    assert "请严格使用中文" in zh_prompt
    assert "Write ALL reader-facing text" in en_prompt
    # Persona phrasing differs by language so the prompts are not just
    # English text with a Chinese tail appended.
    assert "你是 DeepTutor" in zh_prompt
    assert "You are DeepTutor" in en_prompt


def test_mastery_plugin_system_prompt_uses_localized_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRegistry:
        def build_prompt_text(self, *_args, **_kwargs) -> str:
            return "- tool"

    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_tool_registry",
        lambda: FakeRegistry(),
    )

    from deeptutor.core.context import UnifiedContext

    ctx = UnifiedContext(metadata={"mastery_mode": True, "mastery_path_id": "p1"})
    zh_prompt = AgenticChatPipeline(language="zh")._build_system_prompt([], ctx)
    en_prompt = AgenticChatPipeline(language="en")._build_system_prompt([], ctx)

    assert "## mastery_tutor" in zh_prompt
    assert "精通导师模式" in zh_prompt
    assert "## mastery_tutor" in en_prompt
    assert "Mastery Tutor mode" in en_prompt


def test_ask_questions_plugin_system_prompt_uses_localized_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRegistry:
        def build_prompt_text(self, *_args, **_kwargs) -> str:
            return "- tool"

    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_tool_registry",
        lambda: FakeRegistry(),
    )

    from deeptutor.core.context import UnifiedContext

    ctx = UnifiedContext(metadata={"ask_questions_mode": True})
    zh_prompt = AgenticChatPipeline(language="zh")._build_system_prompt([], ctx)
    en_prompt = AgenticChatPipeline(language="en")._build_system_prompt([], ctx)

    assert "## ask_questions" in zh_prompt
    assert "主动提问模式" in zh_prompt
    assert "必须以一次 `ask_user` 调用开始" in zh_prompt
    assert "第 2、3、10 轮" in zh_prompt
    assert "此前所有对话" in zh_prompt
    assert "## ask_questions" in en_prompt
    assert "Ask Questions mode" in en_prompt
    assert "second, third, tenth" in en_prompt
    assert "calling `ask_user` exactly once" in en_prompt


def test_legacy_chat_agent_system_prompt_uses_selected_language() -> None:
    zh_messages = ChatAgent(language="zh", config={}).build_messages(
        message="解释梯度下降",
        history=[],
    )
    en_messages = ChatAgent(language="en", config={}).build_messages(
        message="Explain gradient descent",
        history=[],
    )

    assert "你是 DeepTutor" in zh_messages[0]["content"]
    assert "请严格使用中文" in zh_messages[0]["content"]
    assert "You are DeepTutor" in en_messages[0]["content"]
    assert "Write ALL reader-facing text" in en_messages[0]["content"]


def test_prompt_blocks_include_localized_optional_context() -> None:
    from deeptutor.core.context import UnifiedContext

    prompts = {
        "general": "通用",
        "runtime_policy": "策略",
        "loop": {
            "system": "循环",
            "user": "用户说：{user_message}",
            "finish_exhausted": "预算已用完，请直接回答。",
        },
    }
    ctx = UnifiedContext(
        user_message="解释光合作用",
        sidebar_context="[选中内容]\n把代码和静态数据加载进内存",
        persona_context="用苏格拉底式提问",
        memory_context="学生喜欢例子",
    )
    assembler = ChatPromptAssembler(prompts=prompts, language="zh")

    blocks = assembler.blocks(context=ctx, tool_manifest="", workspace_note="工作区可用")

    names = [block.name for block in blocks]
    assert names[:4] == ["general", "runtime_context", "runtime_policy", "loop"]
    assert "sidebar_tutor_context" in names
    assert "persona_style" in names
    assert "memory" in names
    assert "workspace" in names
    assert assembler.user_message(context=ctx) == "用户说：解释光合作用"
    assert assembler.finish_exhausted_instruction() == "预算已用完，请直接回答。"
    system_prompt = assembler.render(blocks)
    assert "## sidebar_tutor_context" in system_prompt
    assert "把代码和静态数据加载进内存" in system_prompt
