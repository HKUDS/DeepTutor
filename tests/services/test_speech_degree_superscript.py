"""A ``\\circ`` superscript is the degree sign and must be spoken as "degrees"."""

import pytest

from deeptutor.services.voice.speech_text import verbalize_latex_for_speech


def _spoken(text: str) -> str:
    return " ".join(verbalize_latex_for_speech(text).split())


@pytest.mark.parametrize(
    ("latex", "expected"),
    [
        (r"$90^\circ$", "90 degrees"),
        (r"$45^\circ$", "45 degrees"),
        (r"$T^{\circ}$", "T degrees"),
        (r"$x = 30^\circ$", "x = 30 degrees"),
    ],
)
def test_circ_superscript_speaks_as_degrees(latex: str, expected: str) -> None:
    assert _spoken(latex) == expected


def test_circ_as_composition_operator_is_unchanged() -> None:
    # Outside a superscript, ``\circ`` is function composition and must not
    # be rewritten to "degrees".
    assert _spoken(r"$f \circ g$") == "f compose g"
