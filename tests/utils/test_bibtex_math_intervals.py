"""Parentheses inside braced BibTeX values are ordinary title/abstract text."""

import pytest

from deeptutor.utils.bibtex_converter import bibtex_to_markdown


@pytest.mark.parametrize(("opener", "closer"), [("{", "}"), ("(", ")")])
@pytest.mark.parametrize("field", ["title", "abstract"])
@pytest.mark.parametrize("interval", ["[0,1)", "(0,1]"])
def test_keep_bibtex_reference_with_half_open_interval(
    opener: str,
    closer: str,
    field: str,
    interval: str,
) -> None:
    value = f"Convergence on {interval}"
    title = "" if field == "title" else "title={Research}, "
    text = (
        f"@article{opener}interval, {title}{field}={{{value}}}, year={{2026}}{closer}"
        "\n@article{following, title={Following reference}, year={2027}}"
    )

    result = bibtex_to_markdown(text)

    assert "Total entries: 2" in result
    assert "**Citation key:** `interval`" in result
    assert value in result
    assert "**Year:** 2026" in result
    assert "## 2. Following reference" in result
