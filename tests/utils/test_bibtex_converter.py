from __future__ import annotations

from deeptutor.utils.bibtex_converter import bibtex_to_markdown

SAMPLE_BIBTEX = r"""
@string{venue = {Advances}}

@article{vaswani2017attention,
  author = {Vaswani, Ashish and Shazeer, Noam},
  title = {Attention {Is} All You Need},
  journal = {Advances in Neural Information Processing Systems},
  year = {2017},
  doi = {10.5555/3295222},
  abstract = {The dominant models use recurrent networks.}
}

@inproceedings{devlin2019bert,
  author = {Devlin, Jacob and Chang, Ming-Wei},
  title = {"BERT": Pre-training of Deep Bidirectional Transformers},
  booktitle = {NAACL},
  year = 2019
}
"""


def test_bibtex_to_markdown_extracts_structured_entries() -> None:
    result = bibtex_to_markdown(SAMPLE_BIBTEX, "references")

    assert "Total entries: 2" in result
    assert "## 1. Attention Is All You Need" in result
    assert "**Authors:** Ashish Vaswani, Noam Shazeer" in result
    assert "**Type:** Journal Article" in result
    assert "10.5555/3295222" in result
    assert "The dominant models use recurrent networks." in result
    assert "@string" not in result
    assert '## 2. "BERT": Pre-training' in result
    assert "**Type:** Conference Paper" in result


def test_bibtex_to_markdown_keeps_value_with_nested_braces_intact() -> None:
    text = r"""
    @article{nested,
      title = {A {Nested {Title}} Here},
      year = {2020}
    }
    """

    result = bibtex_to_markdown(text)

    assert "A Nested Title Here" in result
    assert "2020" in result


def test_bibtex_to_markdown_skips_entry_with_unterminated_value() -> None:
    text = """
    @article{valid,
      title = {Valid Entry},
      year = {2020}
    }

    @article{broken,
      title = {Unterminated
    """

    result = bibtex_to_markdown(text)

    assert "Valid Entry" in result
    assert "broken" not in result


def test_bibtex_to_markdown_passes_non_bibtex_through() -> None:
    assert bibtex_to_markdown("not a bibliography") == "not a bibliography"
