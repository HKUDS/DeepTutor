"""Unit tests for ``ask_user`` payload building.

Covers the v3 schema (option = ``{label, description}``, ``header``,
``multi_select``), the v2 plain-string-options shape, and the legacy
single-question shorthand which auto-wraps into a one-element list.
"""

from __future__ import annotations

from deeptutor.tools.ask_user import (
    MAX_HEADER_CHARS,
    MAX_OPTION_CHARS,
    MAX_OPTION_DESC_CHARS,
    MAX_OPTIONS,
    MAX_QUESTION_CHARS,
    MAX_QUESTIONS,
    build_ask_user_payload,
)


def _labels(question) -> tuple[str, ...]:
    return tuple(o.label for o in question.options)


# ----------------------------- legacy shape -----------------------------


def test_legacy_rejects_empty_question() -> None:
    payload, err = build_ask_user_payload(question="   ")
    assert payload is None
    assert err and "prompt" in err


def test_legacy_question_only_wraps_to_single() -> None:
    payload, err = build_ask_user_payload(question="What's your level?")
    assert err is None
    assert payload is not None
    assert len(payload.questions) == 1
    only = payload.questions[0]
    assert only.id == "q1"
    assert only.prompt == "What's your level?"
    assert only.options == ()
    assert only.allow_free_text is True
    assert only.multi_select is False
    assert only.header is None


def test_legacy_options_strip_and_dedupe() -> None:
    payload, err = build_ask_user_payload(
        question="Pick",
        options=["  A  ", "B", "A", "", "C"],
    )
    assert err is None
    assert payload is not None
    assert _labels(payload.questions[0]) == ("A", "B", "C")


def test_legacy_caps_option_count() -> None:
    payload, _ = build_ask_user_payload(
        question="Pick",
        options=[f"opt-{i}" for i in range(MAX_OPTIONS + 5)],
    )
    assert payload is not None
    assert len(payload.questions[0].options) == MAX_OPTIONS


def test_legacy_clips_oversized_question() -> None:
    payload, _ = build_ask_user_payload(question="q" * (MAX_QUESTION_CHARS + 50))
    assert payload is not None
    prompt = payload.questions[0].prompt
    assert prompt.endswith("…")
    assert len(prompt) <= MAX_QUESTION_CHARS + 1


def test_legacy_clips_oversized_option() -> None:
    payload, _ = build_ask_user_payload(
        question="q",
        options=["x" * (MAX_OPTION_CHARS + 100)],
    )
    assert payload is not None
    assert payload.questions[0].options[0].label.endswith("…")


def test_legacy_rejects_non_list_options() -> None:
    payload, err = build_ask_user_payload(question="q", options="not-a-list")
    assert payload is None
    assert err and "array" in err


# ------------------------------- v2 shape -------------------------------


def test_v2_multiple_questions_assigned_default_ids() -> None:
    payload, err = build_ask_user_payload(
        questions=[
            {"prompt": "scope?"},
            {"prompt": "depth?"},
            {"prompt": "format?"},
        ]
    )
    assert err is None
    assert payload is not None
    assert payload.question_ids == ("q1", "q2", "q3")


def test_v2_respects_explicit_ids() -> None:
    payload, _ = build_ask_user_payload(
        questions=[
            {"id": "scope", "prompt": "A"},
            {"id": "depth", "prompt": "B"},
        ]
    )
    assert payload is not None
    assert payload.question_ids == ("scope", "depth")


def test_v2_disambiguates_duplicate_ids() -> None:
    payload, _ = build_ask_user_payload(
        questions=[
            {"id": "x", "prompt": "A"},
            {"id": "x", "prompt": "B"},
        ]
    )
    assert payload is not None
    assert payload.question_ids == ("x", "x_2")


def test_v2_caps_question_count() -> None:
    payload, _ = build_ask_user_payload(
        questions=[{"prompt": f"q{i}"} for i in range(MAX_QUESTIONS + 4)]
    )
    assert payload is not None
    assert len(payload.questions) == MAX_QUESTIONS


def test_v2_intro_included_and_clipped() -> None:
    payload, _ = build_ask_user_payload(
        questions=[{"prompt": "hi"}],
        intro="To tailor the research:",
    )
    assert payload is not None
    assert payload.intro == "To tailor the research:"


def test_v2_empty_intro_becomes_none() -> None:
    payload, _ = build_ask_user_payload(
        questions=[{"prompt": "hi"}],
        intro="   ",
    )
    assert payload is not None
    assert payload.intro is None


def test_v2_rejects_non_object_question() -> None:
    payload, err = build_ask_user_payload(questions=["bare string"])
    assert payload is None
    assert err and "object" in err


def test_v2_rejects_empty_questions_list() -> None:
    payload, err = build_ask_user_payload(questions=[])
    assert payload is None
    assert err and "at least one" in err


def test_v2_rejects_non_array_questions() -> None:
    payload, err = build_ask_user_payload(questions={"prompt": "x"})
    assert payload is None
    assert err and "array" in err


def test_v2_accepts_question_alias_for_prompt() -> None:
    """LLMs sometimes use ``question`` instead of ``prompt`` inside a v2 item."""
    payload, err = build_ask_user_payload(questions=[{"question": "what?", "options": ["a", "b"]}])
    assert err is None
    assert payload is not None
    assert payload.questions[0].prompt == "what?"
    assert _labels(payload.questions[0]) == ("a", "b")


def test_v2_allow_free_text_default_true() -> None:
    payload, _ = build_ask_user_payload(questions=[{"prompt": "x"}])
    assert payload is not None
    assert payload.questions[0].allow_free_text is True


def test_v2_allow_free_text_can_be_disabled() -> None:
    payload, _ = build_ask_user_payload(
        questions=[{"prompt": "x", "options": ["a"], "allow_free_text": False}]
    )
    assert payload is not None
    assert payload.questions[0].allow_free_text is False


def test_v2_placeholder_stored() -> None:
    payload, _ = build_ask_user_payload(questions=[{"prompt": "x", "placeholder": "type here"}])
    assert payload is not None
    assert payload.questions[0].placeholder == "type here"


# ----------------------- v3 additions (Claude parity) ---------------------


def test_v3_object_options_with_description() -> None:
    payload, err = build_ask_user_payload(
        questions=[
            {
                "prompt": "Audience?",
                "options": [
                    {"label": "Execs (Recommended)", "description": "Conclusion-first"},
                    {"label": "Engineers", "description": "Technical detail"},
                ],
            }
        ]
    )
    assert err is None
    assert payload is not None
    opts = payload.questions[0].options
    assert opts[0].label == "Execs (Recommended)"
    assert opts[0].description == "Conclusion-first"
    assert opts[1].description == "Technical detail"


def test_v3_mixed_string_and_object_options() -> None:
    payload, _ = build_ask_user_payload(
        questions=[{"prompt": "x", "options": ["plain", {"label": "rich", "description": "d"}]}]
    )
    assert payload is not None
    opts = payload.questions[0].options
    assert opts[0].label == "plain"
    assert opts[0].description is None
    assert opts[1].label == "rich"


def test_v3_option_description_clipped() -> None:
    payload, _ = build_ask_user_payload(
        questions=[
            {
                "prompt": "x",
                "options": [{"label": "a", "description": "d" * (MAX_OPTION_DESC_CHARS + 50)}],
            }
        ]
    )
    assert payload is not None
    desc = payload.questions[0].options[0].description
    assert desc is not None
    assert desc.endswith("…")
    assert len(desc) <= MAX_OPTION_DESC_CHARS + 1


def test_v3_header_stored_and_truncated() -> None:
    payload, _ = build_ask_user_payload(
        questions=[
            {"prompt": "x", "header": "Scope"},
            {"prompt": "y", "header": "H" * (MAX_HEADER_CHARS + 10)},
        ]
    )
    assert payload is not None
    assert payload.questions[0].header == "Scope"
    assert len(payload.questions[1].header or "") == MAX_HEADER_CHARS


def test_v3_multi_select_parsed_with_camel_alias() -> None:
    payload, _ = build_ask_user_payload(
        questions=[
            {"prompt": "a", "multi_select": True},
            {"prompt": "b", "multiSelect": True},
            {"prompt": "c"},
        ]
    )
    assert payload is not None
    assert payload.questions[0].multi_select is True
    assert payload.questions[1].multi_select is True
    assert payload.questions[2].multi_select is False


def test_v3_drops_model_supplied_other_option() -> None:
    payload, _ = build_ask_user_payload(
        questions=[{"prompt": "x", "options": ["A", "Other", "其他", "B"]}]
    )
    assert payload is not None
    assert _labels(payload.questions[0]) == ("A", "B")


def test_v3_keeps_other_option_when_free_text_disabled() -> None:
    """Without the automatic free-text row there is no duplicate to drop."""
    payload, _ = build_ask_user_payload(
        questions=[{"prompt": "x", "options": ["A", "Other"], "allow_free_text": False}]
    )
    assert payload is not None
    assert _labels(payload.questions[0]) == ("A", "Other")


# ------------------------- frontend contract shape ------------------------


def test_to_dict_shape_is_v3_for_frontend() -> None:
    payload, _ = build_ask_user_payload(
        questions=[
            {
                "id": "scope",
                "prompt": "Q1",
                "header": "Scope",
                "options": [{"label": "a", "description": "why a"}],
            },
            {"id": "depth", "prompt": "Q2", "multi_select": True},
        ],
        intro="hi",
    )
    assert payload is not None
    assert payload.to_dict() == {
        "intro": "hi",
        "questions": [
            {
                "id": "scope",
                "prompt": "Q1",
                "header": "Scope",
                "multi_select": False,
                "options": [{"label": "a", "description": "why a"}],
                "allow_free_text": True,
                "placeholder": None,
            },
            {
                "id": "depth",
                "prompt": "Q2",
                "header": None,
                "multi_select": True,
                "options": [],
                "allow_free_text": True,
                "placeholder": None,
            },
        ],
    }


def test_to_dict_legacy_path_also_emits_v3() -> None:
    payload, _ = build_ask_user_payload(question="hi", options=["a", "b"])
    assert payload is not None
    d = payload.to_dict()
    assert d["intro"] is None
    assert len(d["questions"]) == 1
    assert d["questions"][0]["prompt"] == "hi"
    assert d["questions"][0]["options"] == [
        {"label": "a", "description": None},
        {"label": "b", "description": None},
    ]
