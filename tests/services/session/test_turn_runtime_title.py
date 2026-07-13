from __future__ import annotations

from deeptutor.services.session.turn_runtime import _sanitize_session_title


def test_sanitize_session_title_removes_reasoning_block() -> None:
    raw = "<think>\nNeed a concise title.\n</think>\n标题：AgenticRAG 定义"

    assert _sanitize_session_title(raw) == "AgenticRAG 定义"


def test_sanitize_session_title_falls_back_when_only_reasoning_remains() -> None:
    raw = "<think>\nStill deciding on the title."

    assert _sanitize_session_title(raw) == ""
