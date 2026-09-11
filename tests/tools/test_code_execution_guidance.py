from __future__ import annotations

from pathlib import Path

import yaml

from deeptutor.tools.exec_tool import ExecTool
from deeptutor.tools.prompting import load_prompt_hints
from deeptutor.tools.workspace import WorkspacePresentTool


def test_exec_schema_is_the_single_source_and_shell_execution_surface() -> None:
    definition = ExecTool().get_definition()
    schema = definition.to_openai_schema()["function"]["parameters"]

    assert schema["required"] == ["code"]
    assert set(schema["properties"]) == {"code", "language", "stdin", "timeout"}
    assert schema["properties"]["language"]["default"] == "python"
    assert schema["properties"]["language"]["enum"] == ["python", "c", "cpp", "shell"]
    assert "command" not in schema["properties"]


def test_unified_exec_guidance_is_bilingual() -> None:
    for language in ("en", "zh"):
        exec_hint = load_prompt_hints("exec", language=language)

        assert "python -c" in exec_hint.guideline
        assert "heredoc" in exec_hint.guideline
        assert "code_execution" not in exec_hint.guideline
        assert "shell" in exec_hint.input_format
        assert "DEEPTUTOR_WORKSPACE_ROOT" not in exec_hint.guideline
        assert "workspace_present" not in exec_hint.guideline


def test_chat_prompts_delegate_tool_syntax_to_tool_guidance() -> None:
    root = Path(__file__).parents[2] / "deeptutor" / "agents" / "chat" / "prompts"
    scope_rules = {
        "en": "Preserve explicit user quantities and other scope constraints exactly",
        "zh": "必须完整保留用户明确给出的数量和其他范围约束",
    }
    retry_rules = {
        "en": "never resubmit an identical failing call",
        "zh": "绝不原样重复提交同一个失败调用",
    }

    for language in ("en", "zh"):
        data = yaml.safe_load((root / language / "agentic_chat.yaml").read_text())
        prompt = data["loop"]["system"]
        assert "code_execution" not in prompt
        assert "language: python" not in prompt
        assert "language: shell" not in prompt
        assert "python -c" not in prompt
        assert "heredoc" not in prompt
        assert "tool-specific guidance" in prompt or "工具专属说明" in prompt
        assert scope_rules[language] in prompt
        assert retry_rules[language] in prompt


def test_solve_prompts_delegate_tool_routing_to_shared_guidance() -> None:
    root = Path(__file__).parents[2] / "deeptutor" / "capabilities" / "solve" / "prompts"

    for language in ("en", "zh"):
        prompt = (root / language / "system.md").read_text()
        assert "code_execution" not in prompt
        assert "language: python" not in prompt
        assert "language: shell" not in prompt
        assert "tool-specific guidance" in prompt or "工具专属说明" in prompt


def test_office_skills_use_unified_exec_for_python_deliverables() -> None:
    root = Path(__file__).parents[2] / "deeptutor" / "skills" / "builtin"

    for skill in ("docx", "pdf", "pptx", "xlsx"):
        document = (root / skill / "SKILL.md").read_text()
        assert "code_execution" not in document
        assert "`exec`" in document
        assert "language: python" in document
        assert "**User workspace**" in document
        assert "DEEPTUTOR_WORKSPACE_ROOT" not in document
        assert "python -c" not in document
        assert "heredoc" not in document


def test_pdf_skill_preserves_requested_scope_and_requires_changed_retries() -> None:
    root = Path(__file__).parents[2] / "deeptutor" / "skills" / "builtin"
    document = (root / "pdf" / "SKILL.md").read_text()

    assert "such as 500 words" in document
    assert "verify the count in the output before finishing" in document
    assert "do not retry identical code" in document
    assert "reduce the requested scope without asking" in document
    assert "pandas" not in document
    assert "from openpyxl import Workbook" in document


def test_workspace_present_exposes_only_meaningful_item_fields() -> None:
    schema = WorkspacePresentTool().get_definition().to_openai_schema()["function"]["parameters"]
    item_properties = schema["properties"]["items"]["items"]["properties"]

    assert set(item_properties) == {"path", "title", "caption"}
