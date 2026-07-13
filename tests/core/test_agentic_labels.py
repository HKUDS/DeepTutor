from deeptutor.core.agentic.labels import classify_label, find_inline_labels

_ALLOWED = ("FINISH", "TOOL", "THINK", "PAUSE")


def test_classify_label_accepts_common_wrapper_variants() -> None:
    assert classify_label("`FINISH`\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )
    assert classify_label("```FINISH```\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )
    assert classify_label("FINISH：Done", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )


def test_classify_label_accepts_body_adjacent_to_wrapped_label() -> None:
    assert classify_label("``FINISH``你好！", allowed_labels=_ALLOWED) == (
        "FINISH",
        "你好！",
    )
    assert classify_label("``THINK``I need one private step.", allowed_labels=_ALLOWED) == (
        "THINK",
        "I need one private step.",
    )


def test_classify_label_waits_for_unambiguous_bare_label_until_final() -> None:
    assert classify_label("FINISH", allowed_labels=_ALLOWED) is None
    assert classify_label("FINISH", allowed_labels=_ALLOWED, final=True) == (
        "FINISH",
        "",
    )
    assert classify_label("FINISHED", allowed_labels=_ALLOWED, final=True) is None


def test_classify_label_does_not_accept_split_wrapped_label_too_early() -> None:
    assert classify_label("``FINISH`", allowed_labels=_ALLOWED) is None
    assert classify_label("``FINISH```", allowed_labels=_ALLOWED) is None
    assert classify_label("``FINISH``\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )


def test_find_inline_labels_detects_tolerated_label_variants() -> None:
    assert find_inline_labels(
        "draft\n`THINK`\nmore\n```TOOL```\nFINISH：again",
        allowed_labels=_ALLOWED,
    ) == ["THINK", "TOOL", "FINISH"]


def test_find_inline_labels_ignores_prose_mentions() -> None:
    assert (
        find_inline_labels(
            "I should use ``TOOL`` next, then finish with ``FINISH``.",
            allowed_labels=_ALLOWED,
        )
        == []
    )
