"""Equivalent TeX limit placements must have the same spoken meaning."""

import pytest

from deeptutor.services.voice.speech_text import verbalize_latex_for_speech


@pytest.mark.parametrize(
    ("command", "lower", "upper", "body", "expected"),
    [
        ("sum", "i=1", "n", "i", "sum from i = 1 to n i"),
        ("prod", "j=0", "m", "a_j", "product from j = 0 to m a sub j"),
        ("int", "a", "b", "f(x) dx", "integral from a to b f(x) dx"),
        ("oint", "a", "b", "f(z) dz", "contour integral from a to b f(z) dz"),
    ],
)
@pytest.mark.parametrize(
    "directive",
    ["", r"\limits", r"\nolimits", r"\displaylimits", r"\limits \nolimits \displaylimits"],
)
@pytest.mark.parametrize("upper_first", [False, True])
def test_speak_limits_independently_of_tex_placement(
    command: str,
    lower: str,
    upper: str,
    body: str,
    expected: str,
    directive: str,
    upper_first: bool,
) -> None:
    bounds = f"^{{{upper}}}_{{{lower}}}" if upper_first else f"_{{{lower}}}^{{{upper}}}"
    text = f"$\\{command}{directive}{bounds} {body}$"

    assert " ".join(verbalize_latex_for_speech(text).split()) == expected
