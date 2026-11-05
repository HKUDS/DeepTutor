"""An escaped percent (``\\%``) inside math must survive as spoken "percent"."""

import pytest

from deeptutor.services.voice.speech_text import verbalize_latex_for_speech


def _spoken(text: str) -> str:
    return " ".join(verbalize_latex_for_speech(text).split())


@pytest.mark.parametrize(
    ("latex", "expected"),
    [
        (r"$10\%$", "10 percent"),
        (r"$x = 50\%$", "x = 50 percent"),
        (r"$3.5\%$", "3.5 percent"),
    ],
)
def test_escaped_percent_is_spoken(latex: str, expected: str) -> None:
    assert _spoken(latex) == expected
