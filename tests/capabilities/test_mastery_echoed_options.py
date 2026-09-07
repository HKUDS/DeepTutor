"""A restated option list is taken out of the question stem.

The answer card renders ``options`` as its own labelled, clickable list. A stem
that also spells them out therefore shows every choice twice — once as prose
nobody can click, once as the buttons — which is what a learner reported
seeing. The bodies are already held in ``options``, so this is redundancy and
is repaired instead of bounced back to the model.
"""

from __future__ import annotations

from deeptutor.capabilities.mastery.choices import strip_echoed_options

_REAL_OPTIONS = {
    "A": "`error_count: int`",
    "B": "`error_count: Annotated[int, operator.add]`",
    "C": "`error_count: Annotated[list[int], operator.add]`",
    "D": "`error_count: Annotated[int, add_messages]`",
}


def test_a_restated_list_is_removed_and_the_stem_survives() -> None:
    question = (
        "你的图里需要统计一个 `error_count` 字段：每次某个节点捕获到错误时，"
        "这个数字要累加上去。下面哪种字段定义能正确实现「数值累加」？ "
        "A：`error_count: int` B：`error_count: Annotated[int, operator.add]` "
        "C：`error_count: Annotated[list[int], operator.add]` "
        "D：`error_count: Annotated[int, add_messages]`"
    )

    stem, stripped = strip_echoed_options(question, _REAL_OPTIONS)

    assert stripped is True
    assert stem.endswith("下面哪种字段定义能正确实现「数值累加」？")
    for body in _REAL_OPTIONS.values():
        assert body not in stem


def test_a_bulleted_multiline_list_is_removed() -> None:
    question = "Which definition accumulates?\n\n- A. first\n- B. second\n- C. third"

    stem, stripped = strip_echoed_options(question, {"A": "first", "B": "second", "C": "third"})

    assert stripped is True
    assert stem == "Which definition accumulates?"


def test_a_single_quoted_option_is_left_alone() -> None:
    """A stem may legitimately name one option while asking about it."""
    question = "为什么 A：`int` 在这里不行？"

    stem, stripped = strip_echoed_options(question, {"A": "`int`", "B": "`Annotated[int, add]`"})

    assert stripped is False
    assert stem == question


def test_prose_reusing_option_words_is_not_a_list() -> None:
    """Matching requires the label *and* its own body, adjacent."""
    question = "operator.add 和 add_messages 有什么区别？"

    stem, stripped = strip_echoed_options(question, {"A": "operator.add", "B": "add_messages"})

    assert stripped is False
    assert stem == question


def test_a_stem_that_is_only_options_is_left_for_validation() -> None:
    """Emptying the question here would hide the real problem."""
    question = "A. first\nB. second"

    stem, stripped = strip_echoed_options(question, {"A": "first", "B": "second"})

    assert stripped is False
    assert stem == question


def test_fewer_than_two_options_is_never_a_list() -> None:
    assert strip_echoed_options("A. only", {"A": "only"}) == ("A. only", False)
    assert strip_echoed_options("anything", {}) == ("anything", False)


def test_labels_match_case_insensitively() -> None:
    question = "Pick one: a) alpha b) beta"

    stem, stripped = strip_echoed_options(question, {"A": "alpha", "B": "beta"})

    assert stripped is True
    assert stem == "Pick one:"
