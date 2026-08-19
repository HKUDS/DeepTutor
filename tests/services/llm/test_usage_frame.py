"""``usage_frame`` is the one place that guesses a provider usage payload's shape.

Four readers used to re-derive that guess (#919 was one of them missing the
plain-dict case). These tests pin all three shapes plus the two API dialects.
"""

from __future__ import annotations

from deeptutor.services.llm.usage_frame import token_counts, usage_mapping


class _PydanticLike:
    def model_dump(self) -> dict[str, int]:
        return {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}


class _AttrsOnly:
    prompt_tokens = 11
    completion_tokens = 4
    total_tokens = 15


class _NeedsArgs:
    """A model_dump that cannot be called bare — must not blow up the caller."""

    prompt_tokens = 1
    completion_tokens = 2

    def model_dump(self, mode):  # noqa: D102 - deliberately arity-mismatched
        raise AssertionError("unreachable")


# ---- usage_mapping ---------------------------------------------------------


def test_mapping_passthrough() -> None:
    assert usage_mapping({"prompt_tokens": 1, "extra": "kept"}) == {
        "prompt_tokens": 1,
        "extra": "kept",
    }


def test_mapping_from_model_dump() -> None:
    assert usage_mapping(_PydanticLike())["total_tokens"] == 10


def test_mapping_from_attributes_reads_requested_keys_only() -> None:
    assert usage_mapping(_AttrsOnly()) == {
        "prompt_tokens": 11,
        "completion_tokens": 4,
        "total_tokens": 15,
    }


def test_mapping_of_none_is_empty() -> None:
    assert usage_mapping(None) == {}


def test_mapping_falls_back_when_model_dump_is_unusable() -> None:
    assert usage_mapping(_NeedsArgs()) == {"prompt_tokens": 1, "completion_tokens": 2}


# ---- token_counts ---------------------------------------------------------


def test_counts_from_plain_dict() -> None:
    # The shape DeepTutor's own TutorStreamChunk and native adapters emit.
    assert token_counts(
        {"prompt_tokens": 1200, "completion_tokens": 400, "total_tokens": 1600}
    ) == {
        "prompt_tokens": 1200,
        "completion_tokens": 400,
        "total_tokens": 1600,
    }


def test_counts_derive_total_when_absent() -> None:
    assert token_counts({"prompt_tokens": 5, "completion_tokens": 6})["total_tokens"] == 11


def test_counts_empty_frame_is_falsy_not_zero_filled() -> None:
    # Callers use truthiness to mean "this frame carried no usage report".
    assert token_counts(None) == {}
    assert token_counts({}) == {}
    assert token_counts({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}) == {}


def test_counts_tolerate_unparseable_values() -> None:
    assert token_counts({"prompt_tokens": "nope", "completion_tokens": 4})["prompt_tokens"] == 0


def test_counts_map_responses_api_dialect() -> None:
    responses_usage = {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42}
    assert token_counts(responses_usage, prompt="input_tokens", completion="output_tokens") == {
        "prompt_tokens": 30,
        "completion_tokens": 12,
        "total_tokens": 42,
    }


def test_counts_map_responses_api_dialect_from_attributes() -> None:
    obj = type("U", (), {"input_tokens": 8, "output_tokens": 2})()
    assert token_counts(obj, prompt="input_tokens", completion="output_tokens") == {
        "prompt_tokens": 8,
        "completion_tokens": 2,
        "total_tokens": 10,
    }
