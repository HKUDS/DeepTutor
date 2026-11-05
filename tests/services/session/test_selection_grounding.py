import pytest

from deeptutor.services.session._turn_runtime_shared import _selection_is_grounded


def test_selection_grounding_plain_text():
    source = "This is a simple plain text paragraph."
    assert _selection_is_grounded(source, "simple plain text")
    assert not _selection_is_grounded(source, "fabricated sentence")


def test_selection_grounding_table_row():
    source = "| 参数 | 值 |\n| --- | --- |\n| 阈值 | 0.5 |\n| 步长 | 0.01 |"
    assert _selection_is_grounded(source, "阈值 0.5")
    assert _selection_is_grounded(source, "步长 0.01")
    assert not _selection_is_grounded(source, "阈值 1.0")


def test_selection_grounding_list_and_bold():
    source = "1. **先建模**\n2. 再绑定\n3. 最后渲染"
    assert _selection_is_grounded(source, "先建模 再绑定")
    assert _selection_is_grounded(source, "先建模")
    assert not _selection_is_grounded(source, "先绑定 再建模")


def test_selection_grounding_blockquote_and_code():
    source = "> Note that `_selection_is_grounded` verifies authoritative content."
    assert _selection_is_grounded(
        source, "Note that _selection_is_grounded verifies authoritative content."
    )
    assert not _selection_is_grounded(source, "Note that non_existent_func verifies")


def test_selection_grounding_empty_or_whitespace():
    assert not _selection_is_grounded("", "something")
    assert not _selection_is_grounded("something", "")


@pytest.mark.parametrize(
    ("source", "selected"),
    [
        ("**Step 2.** Take action", "Step 9. Take action"),
        ("**a - b**", "a + b"),
        ("`my_variable_name`", "myvariablename"),
        ("**a | b**", "a b"),
        ("$x*y*z$", "$xyz$"),
        ("**Hello** world", "**Hello** + world"),
    ],
)
def test_rendered_selection_cannot_erase_semantic_differences(source, selected):
    assert not _selection_is_grounded(source, selected)


def test_rendered_links_and_math_preserve_visible_text():
    assert _selection_is_grounded("See [the guide](https://example.com) now", "the guide now")
    assert _selection_is_grounded("**Use** $x*y*z$", "Use $x*y*z$")
