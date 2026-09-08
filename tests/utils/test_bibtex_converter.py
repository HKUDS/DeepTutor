from __future__ import annotations

from deeptutor.utils.bibtex_converter import bibtex_to_markdown


SAMPLE_BIBTEX = r"""
@article{vaswani2017attention,
  author = {Vaswani, Ashish and Shazeer, Noam},
  title = {Attention Is All You Need},
  journal = {Advances in Neural Information Processing Systems},
  year = {2017},
  doi = {10.5555/3295222},
  abstract = {The dominant sequence transduction models are based on complex recurrent networks.}
}

@inproceedings{devlin2019bert,
  author = {Devlin, Jacob and Chang, Ming-Wei},
  title = {BERT: Pre-training of Deep Bidirectional Transformers},
  booktitle = {NAACL},
  year = {2019}
}
"""


def test_bibtex_to_markdown_extracts_entries() -> None:
    result = bibtex_to_markdown(SAMPLE_BIBTEX, "references")
    assert "Total entries: 2" in result
    assert "Attention Is All You Need" in result
    assert "BERT" in result
    assert "Vaswani" in result
    assert "Journal Article" in result
    assert "Conference Paper" in result
    assert "10.5555/3295222" in result


def test_bibtex_to_markdown_passthrough_for_non_bibtex() -> None:
    result = bibtex_to_markdown("not bibtex at all")
    assert result == "not bibtex at all"
