"""The exec prompt must not teach one operating system's shell on another."""

from __future__ import annotations

from deeptutor.tools.exec_tool import ExecTool


def test_exec_prompt_does_not_recommend_posix_filters_as_portable_commands() -> None:
    for language in ("en", "zh"):
        hints = ExecTool().get_prompt_hints(language=language)
        rendered = "\n".join((hints.input_format, hints.guideline, hints.note))
        for fragment in ("head", "grep", "tail"):
            assert fragment not in rendered


def test_exec_prompt_requires_real_access_error_before_claiming_denial() -> None:
    zh = ExecTool().get_prompt_hints(language="zh")
    en = ExecTool().get_prompt_hints(language="en")

    assert "不要把命令语法或依赖错误说成沙箱无权访问" in zh.note
    assert "Do not describe syntax or dependency failures as sandbox denial" in en.note
