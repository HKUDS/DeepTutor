"""IM tool hints must not leak engine-injected housekeeping args.

`output_dir`/`workdir` and friends are internal paths the engine injects, not
user intent: on a chat surface they render as noise (and leak deployment
layout). Hints skip them, and when nothing user-meaningful remains the call
renders without empty parentheses.
"""

from deeptutor.services.partners.runtime import _format_tool_hint


def test_hint_skips_injected_housekeeping_args() -> None:
    hint = _format_tool_hint(
        "web_search",
        {
            "query": "丈夫acton",
            "output_dir": "/app/data/partners/partner-1/workspace/outputs/chat/x",
        },
    )
    assert "output_dir" not in hint
    assert "/app/data" not in hint
    assert "web_search" in hint
    assert "query=" in hint


def test_hint_skips_all_internal_path_keys() -> None:
    hint = _format_tool_hint(
        "exec",
        {"code": "print(1)", "output_path": "/tmp/x", "workdir": "/app", "cwd": "/app"},
    )
    assert "output_path" not in hint
    assert "workdir" not in hint
    assert "cwd" not in hint
    assert hint == "⚙ exec(code='print(1)')"


def test_hint_without_rendered_args_omits_parentheses() -> None:
    hint = _format_tool_hint("exec", {"output_dir": "/app/data/x"})
    assert hint == "⚙ exec"
    assert "()" not in hint


def test_hint_still_skips_underscore_args() -> None:
    hint = _format_tool_hint("rag", {"kb_name": "初中语文", "_internal": "x"})
    assert "_internal" not in hint
    assert "kb_name" in hint


def test_hint_truncates_long_values() -> None:
    hint = _format_tool_hint("web_search", {"query": "q" * 200})
    assert len(hint) <= 120
    assert "…" in hint


def test_hint_handles_non_dict_args() -> None:
    assert _format_tool_hint("question_bank", None) == "⚙ question_bank"
    assert _format_tool_hint("question_bank", []) == "⚙ question_bank"
