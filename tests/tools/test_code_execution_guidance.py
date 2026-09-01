from __future__ import annotations

from pathlib import Path

import yaml

from deeptutor.tools.builtin import CodeExecutionTool
from deeptutor.tools.prompting import load_prompt_hints


def test_code_execution_schema_and_hints_cover_file_generation() -> None:
    definition = CodeExecutionTool().get_definition()
    hint = load_prompt_hints("code_execution", language="en")
    exec_hint = load_prompt_hints("exec", language="en")

    assert "files generated" in definition.description
    assert "code-generated deliverables" in definition.description
    assert "creating a file" in hint.when_to_use
    assert "python -c" in hint.guideline
    assert "heredoc" in hint.guideline
    assert "code_execution" in exec_hint.guideline
    assert "Preserve explicit quantities and scope" in definition.description
    assert "never resubmit identical code" in hint.guideline


def test_code_execution_guidance_is_bilingual() -> None:
    scope_rules = {
        "en": "Preserve explicit quantities and scope",
        "zh": "完整保留明确的数量和范围",
    }
    retry_rules = {
        "en": "never resubmit identical code",
        "zh": "绝不原样重复提交代码",
    }

    for language in ("en", "zh"):
        hint = load_prompt_hints("code_execution", language=language)
        exec_hint = load_prompt_hints("exec", language=language)

        assert "Python" in hint.when_to_use
        assert "python -c" in hint.guideline
        assert "heredoc" in hint.guideline
        assert "code_execution" in exec_hint.guideline
        assert "python -c" in exec_hint.guideline
        assert "heredoc" in exec_hint.guideline
        assert scope_rules[language] in hint.guideline
        assert retry_rules[language] in hint.guideline


def test_chat_prompts_prefer_code_execution_for_python_files() -> None:
    root = Path(__file__).parents[2] / "deeptutor" / "agents" / "chat" / "prompts"
    missing_artifact_warnings = {
        "en": "without that list, do not claim a file was created",
        "zh": "没有这个清单就不要宣称已创建文件",
    }
    scope_rules = {
        "en": "Preserve explicit user quantities and other scope constraints exactly",
        "zh": "必须完整保留用户明确给出的数量和其他范围约束",
    }
    retry_rules = {
        "en": "never resubmit identical code",
        "zh": "绝不原样重复提交同一份代码",
    }

    for language in ("en", "zh"):
        data = yaml.safe_load((root / language / "agentic_chat.yaml").read_text())
        prompt = data["loop"]["system"]
        assert "code_execution" in prompt
        assert "python -c" in prompt
        assert "heredoc" in prompt
        assert missing_artifact_warnings[language] in prompt
        assert scope_rules[language] in prompt
        assert retry_rules[language] in prompt


def test_solve_prompts_route_python_files_to_code_execution() -> None:
    root = Path(__file__).parents[2] / "deeptutor" / "capabilities" / "solve" / "prompts"
    shell_only_guidance = {
        "en": "`exec` only for genuinely shell-only commands",
        "zh": "`exec` 只用于真正必须使用 shell 的命令",
    }

    for language in ("en", "zh"):
        prompt = (root / language / "system.md").read_text()
        assert "code_execution" in prompt
        assert "Python-generated files" in prompt or "用 Python 生成文件" in prompt
        assert shell_only_guidance[language] in prompt


def test_office_skills_use_code_execution_for_python_deliverables() -> None:
    root = Path(__file__).parents[2] / "deeptutor" / "skills" / "builtin"

    for skill in ("docx", "pdf", "pptx", "xlsx"):
        document = (root / skill / "SKILL.md").read_text()
        assert "code_execution" in document
        assert "python -c" in document
        assert "heredoc" in document


def test_pdf_skill_preserves_requested_scope_and_requires_changed_retries() -> None:
    root = Path(__file__).parents[2] / "deeptutor" / "skills" / "builtin"
    document = (root / "pdf" / "SKILL.md").read_text()

    assert "such as 500 words" in document
    assert "verify the count in the output before finishing" in document
    assert "do not retry identical code" in document
    assert "reduce the requested scope without asking" in document
