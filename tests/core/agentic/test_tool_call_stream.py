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

from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from deeptutor.runtime.agentic.tool_call_stream import ToolCallAccumulator


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


def test_unindexed_parallel_calls_stay_separate() -> None:
    """#2482: Gemini streams parallel calls with no ``index`` at all.

    Coercing the absent index to 0 folded every call into one part, so the
    ids overwrote each other and the arguments concatenated into invalid
    JSON. Each fresh id has to open its own part instead.
    """
    acc = ToolCallAccumulator()
    for suffix in ("alpha", "beta", "gamma"):
        acc.feed(
            _Delta(
                index=None, id=f"call_{suffix}", name="rag_search", arguments=f'{{"q":"{suffix}"}}'
            )  # type: ignore[arg-type]
        )

    assert acc.collected() == [
        {"id": "call_alpha", "name": "rag_search", "arguments": '{"q":"alpha"}'},
        {"id": "call_beta", "name": "rag_search", "arguments": '{"q":"beta"}'},
        {"id": "call_gamma", "name": "rag_search", "arguments": '{"q":"gamma"}'},
    ]


def test_fragment_without_index_or_id_continues_the_last_addressed_call() -> None:
    """Only a fresh id opens a part; an anonymous fragment resumes."""
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=None, id="call_a", name="rag_search", arguments='{"q":'))  # type: ignore[arg-type]
    acc.feed(_Delta(index=None, arguments='"x"}'))  # type: ignore[arg-type]
    acc.feed(_Delta(index=None, id="call_b", name="web_search", arguments="{}"))  # type: ignore[arg-type]

    assert acc.collected() == [
        {"id": "call_a", "name": "rag_search", "arguments": '{"q":"x"}'},
        {"id": "call_b", "name": "web_search", "arguments": "{}"},
    ]


def test_explicit_index_zero_is_not_the_first_unindexed_call() -> None:
    """A provider that omits ``index`` and one that sends ``index=0`` must not
    share a part, or the two calls merge again through the back door."""
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=None, id="call_unindexed", name="rag_search", arguments="{}"))  # type: ignore[arg-type]
    acc.feed(_Delta(index=0, id="call_zero", name="web_search", arguments="{}"))

    assert acc.collected() == [
        {"id": "call_unindexed", "name": "rag_search", "arguments": "{}"},
        {"id": "call_zero", "name": "web_search", "arguments": "{}"},
    ]


def test_part_at_without_an_index_is_the_part_just_fed() -> None:
    """Callers that preview a call as it streams should not re-derive the
    slot: the accumulator already resolved it (#2482)."""
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=None, id="call_a", name="ask_user", arguments='{"q":'))  # type: ignore[arg-type]
    assert acc.part_at()["arguments"] == '{"q":'  # type: ignore[index]

    acc.feed(_Delta(index=None, id="call_b", name="rag_search", arguments="{}"))  # type: ignore[arg-type]
    assert acc.part_at()["id"] == "call_b"  # type: ignore[index]
    # Explicit lookups still work for the callers that keep a provider index.
    acc.feed(_Delta(index=4, name="web_search", arguments="{}"))
    assert acc.part_at(4)["name"] == "web_search"  # type: ignore[index]


def test_calls_report_in_arrival_order_not_provider_index_order() -> None:
    """Out-of-order indices are what the wire delivered; re-sorting them
    would hand the dispatcher a different order than the model chose."""
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=1, id="call_b", name="web_search", arguments="{}"))
    acc.feed(_Delta(index=0, id="call_a", name="rag_search", arguments="{}"))

    assert [call["id"] for call in acc.collected()] == ["call_b", "call_a"]
    assert [part["id"] for part in acc.ordered()] == ["call_b", "call_a"]


def test_gemini_thought_signature_survives_stream_accumulation() -> None:
    """Gemini 3 rejects the next tool round unless its opaque extension is
    replayed on the same function-call part (#1181)."""
    delta = ChoiceDeltaToolCall.model_validate(
        {
            "index": 0,
            "id": "function-call-1",
            "type": "function",
            "function": {"name": "mastery_status", "arguments": "{}"},
            "extra_content": {"google": {"thought_signature": "signature-from-gemini"}},
        }
    )
    acc = ToolCallAccumulator()
    acc.feed(delta)

    assert acc.collected() == [
        {
            "id": "function-call-1",
            "name": "mastery_status",
            "arguments": "{}",
            "extra_content": {"google": {"thought_signature": "signature-from-gemini"}},
        }
    ]
