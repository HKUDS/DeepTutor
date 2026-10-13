from copy import deepcopy
import json

from deeptutor.capabilities.mastery.history import share_mastery_history
from deeptutor.services.session.model_history import _MASTERY_SNAPSHOT_NOTICE, normalize_model_turn


def exchange(call_id, name, payload):
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": '{"reason":"learner requested a change"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]


def large_state():
    return {
        "name": "Course",
        "modules": [
            {"id": "m1", "objective": "Learner confused A with B. " * 90},
            {"id": "m2", "objective": "Explain using the successful example. " * 90},
        ],
    }


def expand_shared(messages):
    """Every reference must resolve directly to a full inline value."""
    payloads = {}
    for message in messages:
        if message.get("role") == "tool":
            try:
                payloads[("tool_call_id", message["tool_call_id"])] = json.loads(message["content"])
            except ValueError:
                pass
        if message.get("_context_snapshot") == "mastery_status_snapshot":
            payloads[("snapshot", "mastery_status_snapshot")] = json.loads(
                message["content"][len(_MASTERY_SNAPSHOT_NOTICE) :]
            )

    def expand(value):
        if isinstance(value, dict):
            if set(value) == {"$mastery_same_value"}:
                ref = value["$mastery_same_value"]
                kind = "snapshot" if "snapshot" in ref else "tool_call_id"
                target = payloads[(kind, ref[kind])]
                for part in ref["pointer"].split("/")[1:]:
                    key = part.replace("~1", "/").replace("~0", "~")
                    target = target[int(key)] if isinstance(target, list) else target[key]
                assert "$mastery_same_value" not in json.dumps(target)
                return target
            return {key: expand(child) for key, child in value.items()}
        if isinstance(value, list):
            return [expand(child) for child in value]
        return value

    return {key: expand(value) for key, value in payloads.items()}


def test_exact_reconstruction_preserves_unique_old_state_and_all_dialogue():
    original_map = large_state()
    revised_map = deepcopy(original_map)
    revised_map["modules"][0]["objective"] = "An earlier misconception was corrected. " * 90
    messages = [
        {"role": "user", "content": "I still confuse A and B; that explanation did not help."},
        *exchange("build", "mastery_build", {"map": original_map, "status": "built"}),
        *exchange("revise", "mastery_revise", {"map": revised_map, "progress_reset": ["m1"]}),
        *exchange("status", "mastery_status", {"map": revised_map, "path_id": "p"}),
        {"role": "assistant", "content": "Here is the explanation that helped you."},
    ]
    before = deepcopy(messages)
    expected = expand_shared(before)
    share_mastery_history(messages, len(messages))
    assert expand_shared(messages) == expected
    assert len(json.dumps(messages)) < len(json.dumps(before)) * 0.65
    assert [m for m in messages if m["role"] != "tool"] == [
        m for m in before if m["role"] != "tool"
    ]
    assert normalize_model_turn({"version": 1, "messages": messages}) is not None
    assert json.loads(messages[4]["content"])["progress_reset"] == ["m1"]


def test_current_snapshot_and_current_tool_results_are_full_anchors_only():
    payload = {"path_id": "p", "map": large_state()}
    messages = exchange("old", "mastery_status", payload)
    boundary = len(messages)
    messages += [
        {
            "role": "user",
            "content": _MASTERY_SNAPSHOT_NOTICE + json.dumps(payload),
            "_context_snapshot": "mastery_status_snapshot",
        },
        {"role": "user", "content": "Actual question"},
        *exchange("current", "mastery_status", payload),
    ]
    original = deepcopy(messages)
    share_mastery_history(messages, boundary)
    assert messages[boundary:] == original[boundary:]
    assert expand_shared(messages) == expand_shared(original)
    assert "$mastery_same_value" in messages[1]["content"]


def test_sources_grades_answers_unknown_fields_and_tools_are_not_projected():
    evidence = {"map": large_state(), "source_quotes": "Keep exact source words. " * 90}
    messages = [
        *exchange("rag", "rag", evidence),
        *exchange("answer", "ask_user", evidence),
        *exchange("grade", "mastery_grade", evidence),
        *exchange("state", "mastery_status", evidence),
        *exchange("state2", "mastery_status", evidence),
    ]
    original = deepcopy(messages)
    share_mastery_history(messages, len(messages))
    assert messages[:6] == original[:6]
    assert json.loads(messages[7]["content"])["source_quotes"] == evidence["source_quotes"]


def test_ambiguous_call_ids_and_malformed_state_are_left_untouched():
    messages = [
        *exchange("duplicate", "mastery_status", {"map": large_state()}),
        *exchange("duplicate", "mastery_status", {"map": large_state()}),
        *exchange("broken", "mastery_status", {"map": large_state()}),
    ]
    messages[-1]["content"] = '{"map": malformed}'
    original = deepcopy(messages)
    share_mastery_history(messages, len(messages))
    assert messages == original


def test_no_reference_chains_and_json_pointer_special_keys():
    payload = {"map": {"a/b~c": large_state()}}
    messages = [m for i in range(4) for m in exchange(f"s{i}", "mastery_status", payload)]
    original = deepcopy(messages)
    share_mastery_history(messages, len(messages))
    assert expand_shared(messages) == expand_shared(original)
    assert messages[-1] == original[-1]
    once = deepcopy(messages)
    share_mastery_history(messages, len(messages))
    assert messages == once


def test_similar_but_different_values_are_not_merged():
    messages = [
        *exchange("a", "mastery_profile", {"learner_profile": {"difficulty": "A" * 900}}),
        *exchange("b", "mastery_profile", {"learner_profile": {"difficulty": "B" * 900}}),
    ]
    original = deepcopy(messages)
    share_mastery_history(messages, len(messages))
    assert messages == original


def test_json_pointer_escaping_resolves_partial_sharing():
    common = {"detail": "Keep this exact explanation. " * 100}
    first = {"map": {"a/b~c": common, "revision_note": "before"}}
    second = {"map": {"a/b~c": common, "revision_note": "after"}}
    messages = exchange("first", "mastery_status", first) + exchange(
        "second", "mastery_status", second
    )
    original = deepcopy(messages)
    share_mastery_history(messages, len(messages))
    assert "/map/a~1b~0c" in messages[1]["content"]
    assert expand_shared(messages) == expand_shared(original)


def test_current_round_projection_is_disposable_and_preserves_changed_state():
    from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline

    pipeline = MasteryLoopPipeline.__new__(MasteryLoopPipeline)
    state = large_state()
    changed = deepcopy(state)
    changed["modules"][0]["objective"] = "A distinct new objective. " * 90
    messages = (
        exchange("before", "mastery_status", {"map": state})
        + exchange("same", "mastery_status", {"map": state})
        + exchange("changed", "mastery_status", {"map": changed})
    )
    original = deepcopy(messages)
    projected = pipeline.project_model_request(messages)
    assert messages == original
    assert expand_shared(projected) == expand_shared(original)
    assert "$mastery_same_value" in projected[1]["content"]
    assert projected[-1] == original[-1]
