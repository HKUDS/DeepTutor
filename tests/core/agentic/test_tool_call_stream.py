"""Streaming tool-call accumulation (issue #937).

A router in front of an OpenAI-compatible provider re-sent the *complete*
``id`` on every delta chunk instead of only on the first. The chat loop
appended it, so the id grew one copy per chunk — the reporter observed 551,
754, 870, 1566, 9715, 17864 and 47241 characters — and once past the
provider's own 64-character ceiling every round died with HTTP 400
``Invalid 'messages[i].tool_calls[0].id': string too long``. The forced-finish
call died the same way, so the turn surfaced as "I could not produce a useful
response from the model output."

What is pinned here is the per-field rule, because the fields disagree:
``id`` and ``name`` arrive whole and must be assigned, ``arguments`` arrives
in fragments and must be concatenated. Both directions matter — assigning
``arguments`` would silently truncate every call to its last chunk.
"""

from __future__ import annotations

from deeptutor.core.agentic.tool_call_stream import ToolCallAccumulator


class _Fn:
    def __init__(self, name: str | None = None, arguments: str | None = None) -> None:
        self.name = name
        self.arguments = arguments


class _Delta:
    """One ``delta.tool_calls`` entry as the OpenAI SDK shapes it."""

    def __init__(
        self,
        index: int = 0,
        id: str | None = None,
        name: str | None = None,
        arguments: str | None = None,
    ) -> None:
        self.index = index
        self.id = id
        self.function = _Fn(name, arguments)


def test_gateway_repeating_id_and_name_per_chunk_stays_within_api_limits() -> None:
    """The #937 provider: every chunk carries the whole id and name."""
    acc = ToolCallAccumulator()
    for fragment in ('{"topic"', ': "tuple', ' unpacking"}'):
        acc.feed(_Delta(id="call_9x2f", name="mastery_quiz", arguments=fragment))

    (call,) = acc.collected()
    assert call["id"] == "call_9x2f"
    assert len(call["id"]) <= 64
    # The append also corrupted the name into an unresolvable
    # ``mastery_quizmastery_quizmastery_quiz``.
    assert call["name"] == "mastery_quiz"
    assert call["arguments"] == '{"topic": "tuple unpacking"}'


def test_spec_compliant_stream_concatenates_only_arguments() -> None:
    """The ordinary shape: id and name once, arguments in fragments."""
    acc = ToolCallAccumulator()
    acc.feed(_Delta(id="call_1", name="rag_search", arguments='{"q":'))
    acc.feed(_Delta(arguments='"decorators"'))
    acc.feed(_Delta(arguments="}"))

    assert acc.collected() == [
        {"id": "call_1", "name": "rag_search", "arguments": '{"q":"decorators"}'}
    ]


def test_parallel_calls_stay_separated_by_index() -> None:
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=0, id="call_a", name="rag_search", arguments='{"q":"a"}'))
    acc.feed(_Delta(index=1, id="call_b", name="web_search", arguments='{"q":'))
    acc.feed(_Delta(index=1, arguments='"b"}'))

    assert acc.collected() == [
        {"id": "call_a", "name": "rag_search", "arguments": '{"q":"a"}'},
        {"id": "call_b", "name": "web_search", "arguments": '{"q":"b"}'},
    ]


def test_feed_bills_name_and_arguments_but_not_the_id() -> None:
    """Callers add the return value to the provider's output-char total."""
    acc = ToolCallAccumulator()
    assert acc.feed(_Delta(id="call_long_identifier", name="ab", arguments="cde")) == 5
    assert acc.feed(_Delta(index=0)) == 0


def test_argumentless_call_still_dispatches_valid_json() -> None:
    acc = ToolCallAccumulator()
    acc.feed(_Delta(id="call_1", name="mastery_status"))

    assert acc.collected() == [{"id": "call_1", "name": "mastery_status", "arguments": "{}"}]


def test_call_without_a_provider_id_gets_a_positional_one() -> None:
    """The result message needs an id to correlate against."""
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=2, name="rag_search", arguments="{}"))

    assert acc.collected() == [{"id": "call_2", "name": "rag_search", "arguments": "{}"}]


def test_arguments_without_a_name_are_not_dispatchable() -> None:
    acc = ToolCallAccumulator()
    acc.feed(_Delta(id="call_1", arguments='{"q":"x"}'))

    assert acc.collected() == []
    # ``ordered`` is the unfiltered view the labeled-step runner reports on.
    assert acc.ordered() == [{"id": "call_1", "name": "", "arguments": '{"q":"x"}'}]


def test_absent_index_is_coerced_so_parts_stay_sortable() -> None:
    """A provider that omits ``index`` used to seed a ``None`` dict key,
    which made the final ``sorted()`` raise once any real index appeared."""
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=None, id="call_1", name="rag_search", arguments="{}"))  # type: ignore[arg-type]
    acc.feed(_Delta(index=1, id="call_2", name="web_search", arguments="{}"))

    assert [call["id"] for call in acc.collected()] == ["call_1", "call_2"]
