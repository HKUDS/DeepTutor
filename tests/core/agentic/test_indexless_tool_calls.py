"""Regression coverage for missing streamed tool-call indices (#2482)."""

from types import SimpleNamespace

import pytest

from deeptutor.runtime.agentic.tool_call_stream import ToolCallAccumulator


def delta(index=None, id=None, name=None, arguments=None, extra_content=None):
    return SimpleNamespace(
        index=index,
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
        extra_content=extra_content,
    )


def test_unindexed_calls_with_distinct_ids_are_not_merged():
    acc = ToolCallAccumulator()
    acc.feed(delta(id="a", name="rag", arguments='{"query":"alpha"}'))
    acc.feed(delta(id="b", name="rag", arguments='{"query":"beta"}'))
    assert acc.collected() == [
        {"id": "a", "name": "rag", "arguments": '{"query":"alpha"}'},
        {"id": "b", "name": "rag", "arguments": '{"query":"beta"}'},
    ]


def test_preview_resolves_last_call_without_overwriting_wire_index_zero():
    acc = ToolCallAccumulator()
    acc.feed(delta(index=0, id="wire", name="rag", arguments="{}"))
    acc.feed(delta(id="indexless", name="rag", arguments="{}"))
    assert acc.part_at(0)["id"] == "wire"
    assert acc.last_part()["id"] == "indexless"


def test_concatenated_complete_objects_fail_closed():
    acc = ToolCallAccumulator()
    acc.feed(delta(id="a", name="rag", arguments='{"query":"alpha"}'))
    acc.feed(delta(arguments=' {"query":"beta"}'))
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()


@pytest.mark.parametrize(
    "arguments",
    [
        '{"query":"alpha"}{"query":"beta"',
        '{"query":"alpha"}  {"query":',
        '```json\n{"query":"alpha"}\n```\n```json\n{"query":"beta"',
    ],
)
def test_complete_document_followed_by_truncated_object_fails_closed(arguments):
    acc = ToolCallAccumulator()
    acc.feed(delta(id="a", name="rag", arguments=arguments))
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()


@pytest.mark.parametrize(
    "arguments",
    [
        '```json\n{"q":111}\n```\n```json\n{"q":222}\n```',
        '{"q":111,"q":222}',
        '```json\n{"q":111,"q":222,}\n```',
        '{"nested":{"q":111,"q":222}}',
        '[{"q":111},{"q":222}]',
        'first {"q":111,} then {"q":222,}',
    ],
)
def test_ambiguous_json_wrappers_duplicates_and_arrays_fail_closed(arguments):
    acc = ToolCallAccumulator()
    acc.feed(delta(id="a", name="rag", arguments=arguments))
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()


def test_normal_json_code_string_and_fragmented_json_are_preserved():
    import json

    arguments = json.dumps({"code": '```json\n{"q":111}{"q":222}\n```', "nested": {"q": 1}})
    acc = ToolCallAccumulator()
    for index, fragment in enumerate((arguments[:11], arguments[11:30], arguments[30:])):
        acc.feed(delta(id="a", name="rag" if index == 0 else None, arguments=fragment))
    assert acc.collected()[0]["arguments"] == arguments


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ('{"query":"incomplete', {"query": "incomplete"}),
        ('{"query":"brace } { and escaped \\" text', {"query": 'brace } { and escaped " text'}),
        ('{"nested":{"query":"alpha"}', {"nested": {"query": "alpha"}}),
        (
            '{"nested":[{"value":"}{"}],"text":"{\\"q\\": 1}"}',
            {"nested": [{"value": "}{"}], "text": '{"q": 1}'},
        ),
    ],
)
def test_single_truncated_or_valid_nested_arguments_remain_recoverable(arguments, expected):
    from deeptutor.utils.json_parser import parse_json_response

    acc = ToolCallAccumulator()
    acc.feed(delta(id="a", name="rag", arguments=arguments))
    call = acc.collected()[0]
    assert call["arguments"] == arguments
    assert parse_json_response(call["arguments"]) == expected


def test_repeated_id_and_single_idless_fragments():
    acc = ToolCallAccumulator()
    acc.feed(delta(id="a", name="rag", arguments='{"query":'))
    acc.feed(delta(id="a", arguments='"alpha"'))
    acc.feed(delta(arguments="}"))
    assert acc.collected()[0]["arguments"] == '{"query":"alpha"}'


def test_unindexed_interleaved_ids_with_signatures():
    acc = ToolCallAccumulator()
    signatures = [
        {"google": {"thought_signature": "one"}},
        {"google": {"thought_signature": "two"}},
    ]
    acc.feed(delta(id="a", name="rag", arguments='{"q":', extra_content=signatures[0]))
    acc.feed(delta(id="b", name="rag", arguments='{"q":', extra_content=signatures[1]))
    acc.feed(delta(id="a", arguments='"a"}'))
    acc.feed(delta(id="b", arguments='"b"}'))
    calls = acc.collected()
    assert [c["arguments"] for c in calls] == ['{"q":"a"}', '{"q":"b"}']
    assert [c["extra_content"] for c in calls] == signatures


def test_ambiguous_anonymous_continuation_poisons_batch():
    acc = ToolCallAccumulator()
    acc.feed(delta(id="a", name="rag", arguments='{"q":'))
    acc.feed(delta(id="b", name="rag", arguments='{"q":'))
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.feed(delta(arguments='"x"}'))
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()
    assert acc.last_part() is None


@pytest.mark.parametrize(
    "second",
    [
        delta(index=0, id="b"),
        delta(index=1, id="a"),
        delta(index=0, id="a", name="different"),
        delta(index=0, id="a", extra_content={"google": {"thought_signature": "different"}}),
    ],
)
def test_conflicting_identity_or_metadata_poisons_batch(second):
    acc = ToolCallAccumulator()
    acc.feed(
        delta(
            index=0,
            id="a",
            name="rag",
            arguments="{}",
            extra_content={"google": {"thought_signature": "one"}},
        )
    )
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.feed(second)
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()


def test_mixed_index_and_unindexed_preserves_arrival_and_ids():
    acc = ToolCallAccumulator()
    acc.feed(delta(index=7, id="a", name="rag", arguments="{}"))
    acc.feed(delta(id="b", name="rag", arguments="{}"))
    acc.feed(delta(index=0, id="c", name="rag", arguments="{}"))
    assert [c["id"] for c in acc.collected()] == ["a", "b", "c"]


def test_mixed_stream_keeps_arrival_order_after_late_index_binding():
    acc = ToolCallAccumulator()
    acc.feed(delta(id="a", name="rag", arguments='{"q":'))
    acc.feed(delta(index=0, id="b", name="rag", arguments="{}"))
    acc.feed(delta(index=7, id="a", arguments='"a"}'))
    assert [c["id"] for c in acc.collected()] == ["a", "b"]


def test_preview_fallback_id_cannot_be_reassigned_or_collide():
    acc = ToolCallAccumulator()
    acc.feed(delta(index=0, name="ask_user", arguments='{"question":"Choose?"}'))
    assert acc.last_part()["id"] == ""
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.feed(delta(index=1, id="call_0", name="rag", arguments="{}"))
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()


def test_valid_embedded_json_text_and_single_malformed_input_unchanged():
    acc = ToolCallAccumulator()
    acc.feed(delta(index=0, id="a", name="rag", arguments='{"query":"{}{}"}'))
    acc.feed(delta(index=1, id="b", name="rag", arguments='{"query":"incomplete'))
    assert [c["arguments"] for c in acc.collected()] == ['{"query":"{}{}"}', '{"query":"incomplete']


def test_late_id_before_preview_is_allowed():
    acc = ToolCallAccumulator()
    acc.feed(delta(index=0, name="ask_user", arguments="{"))
    assert acc.last_part()["id"] == ""
    acc.feed(delta(index=0, id="provider", arguments='"question":"Choose?"}'))
    assert acc.collected()[0]["id"] == "provider"


def test_reserved_preview_identity_does_not_reparse_each_later_fragment(monkeypatch):
    from deeptutor.tools import ask_user

    original = ask_user.build_ask_user_preview
    parsed = []

    def track(arguments):
        parsed.append(arguments)
        return original(arguments)

    monkeypatch.setattr(ask_user, "build_ask_user_preview", track)
    acc = ToolCallAccumulator()
    acc.feed(delta(index=0, name="ask_user", arguments='{"question":"Choose?"'))
    acc.last_part()
    assert acc.last_preview_id() == "call_0"
    for fragment in (',"options":', '["one",', '"two"]}'):
        acc.feed(delta(index=0, arguments=fragment))
        acc.last_part()
    assert len(parsed) == 1


def test_late_id_after_visible_preview_fails_closed():
    acc = ToolCallAccumulator()
    acc.feed(delta(index=0, name="ask_user", arguments='{"question":"Choose?"}'))
    assert acc.last_part()["id"] == ""
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.feed(delta(index=0, id="provider"))
    with pytest.raises(ValueError, match="Ambiguous"):
        acc.collected()


def test_synthetic_fallback_does_not_collide_with_provider_id():
    acc = ToolCallAccumulator()
    acc.feed(delta(index=0, name="rag", arguments="{}"))
    acc.feed(delta(index=1, id="call_0", name="rag", arguments="{}"))
    calls = acc.collected()
    assert calls[1]["id"] == "call_0"
    assert calls[0]["id"] != calls[1]["id"]
