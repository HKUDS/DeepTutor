"""``^\\top`` and ``^\\intercal`` are transpose and must be spoken as such."""

import pytest

from deeptutor.services.voice.speech_text import verbalize_latex_for_speech


def _spoken(text: str) -> str:
    return " ".join(verbalize_latex_for_speech(text).split())


@pytest.mark.parametrize(
    ("latex", "expected"),
    [
        (r"$A^\top$", "A transpose"),
        (r"$A^{\top}$", "A transpose"),
        (r"$A^\intercal$", "A transpose"),
        (r"$\mathbf{x}^\top \mathbf{y}$", "x transpose y"),
        (r"$A^T$", "A transpose"),
    ],
)
def test_transpose_superscript_speaks_as_transpose(latex: str, expected: str) -> None:
    assert _spoken(latex) == expected
