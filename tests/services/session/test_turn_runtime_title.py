from __future__ import annotations

from deeptutor.services.session.turn_runtime import _sanitize_session_title


def test_sanitize_session_title_removes_reasoning_block() -> None:
    raw = "<think>\nNeed a concise title.\n</think>\n标题：AgenticRAG 定义"

    assert _sanitize_session_title(raw) == "AgenticRAG 定义"


def test_sanitize_session_title_falls_back_when_only_reasoning_remains() -> None:
    raw = "<think>\nStill deciding on the title."

    assert _sanitize_session_title(raw) == ""


def test_provider_errors_do_not_become_session_titles() -> None:
    """``llm_stream`` surfaces a provider failure as streamed content.

    A bad key therefore yields a short, well-formed string that the sanitizer
    happily trims and stores as the conversation's name, where it stays forever
    and follows the session into every list that shows it. Routing these to the
    existing "no title" fallback is what makes that impossible.
    """
    from deeptutor.services.session.turn_runtime import _looks_like_error_payload

    assert _looks_like_error_payload(
        "Error: {'message': 'Authentication Fails, Your api key: *** is invalid'}"
    )
    assert _looks_like_error_payload('{"error": {"code": 401}}')
    assert _looks_like_error_payload("错误：调用失败")
    assert _looks_like_error_payload("Traceback (most recent call last):")


def test_real_titles_survive_the_error_guard() -> None:
    """A false positive silently replaces a good title with a truncated question."""
    from deeptutor.services.session.turn_runtime import _looks_like_error_payload

    for title in (
        "操作系统概述",
        "Deadlock detection basics",
        "Error handling in Rust",
        "错误处理的三种模式",
        "",
    ):
        assert not _looks_like_error_payload(title), title
