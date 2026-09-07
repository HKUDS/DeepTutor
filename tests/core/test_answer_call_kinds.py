"""The reply-bearing ``call_kind`` list is duplicated; hold the copies together.

Which rounds' ``content`` events make up the reply is decided twice: once in
``deeptutor.core.trace.ANSWER_BEARING_CALL_KINDS`` and once in
``shouldAppendEventContent`` (``web/lib/stream.ts``), because the client filters
the stream as it arrives and cannot import Python.

A drift between them fails silently and in the worst possible way: the text
streams, the trace shows it, and the message body drops it. Nothing raises, no
test that stubs one side notices, and the turn looks like the model returned
nothing.
"""

from __future__ import annotations

from pathlib import Path
import re

from deeptutor.core.trace import ANSWER_BEARING_CALL_KINDS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLIENT_STREAM_TS = _REPO_ROOT / "web" / "lib" / "stream.ts"
_AGENT_LOOP_PY = _REPO_ROOT / "deeptutor" / "agents" / "loop" / "agent_loop.py"


def _client_answer_call_kinds() -> set[str]:
    """The kinds ``shouldAppendEventContent`` admits into the answer."""
    source = _CLIENT_STREAM_TS.read_text(encoding="utf-8")
    start = source.index("export function shouldAppendEventContent")
    end = source.index("\n}", start)
    return set(re.findall(r'meta\.call_kind === "([a-z_]+)"', source[start:end]))


def test_client_and_backend_agree_on_which_rounds_carry_the_answer() -> None:
    assert _client_answer_call_kinds() == set(ANSWER_BEARING_CALL_KINDS)


def test_the_chat_loop_only_streams_answers_under_declared_kinds() -> None:
    """Every ``call_kind`` the chat loop labels its own rounds with is declared.

    The loop is the one place that streams a user-facing reply through this
    filter, so a kind it introduces without declaring here would have its text
    dropped from the message body.
    """
    source = _AGENT_LOOP_PY.read_text(encoding="utf-8")
    used = set(re.findall(r'call_kind="([a-z_]+)"', source))
    assert used, "expected the chat loop to label its rounds"
    assert used <= set(ANSWER_BEARING_CALL_KINDS), sorted(used - ANSWER_BEARING_CALL_KINDS)
