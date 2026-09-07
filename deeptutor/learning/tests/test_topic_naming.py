"""A goal's name is a label, not a restatement of the goal."""

from __future__ import annotations

import pytest

from deeptutor.learning import topic_naming
from deeptutor.learning.topic_naming import (
    MAX_TITLE_CHARS,
    MAX_TITLE_CHARS_LATIN,
    _clean,
    suggest_topic_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("「时间序列神经网络」", "时间序列神经网络"),
        ('  "Transformer 入门"  ', "Transformer 入门"),
        # A trailing full stop is punctuation on a sentence; a name is not one.
        ("Time-series neural networks.", "Time-series neural networks"),
        ("向量空间与线性变换。", "向量空间与线性变换"),
    ],
)
def test_a_model_answer_is_reduced_to_the_name_itself(raw, expected):
    assert _clean(raw) == expected


def test_a_model_that_explained_itself_is_rejected_rather_than_trimmed():
    """Taking the first line would put "Here is a good name:" on the dashboard."""
    assert _clean("Here is a good name:\nRAG systems") == ""
    assert _clean("") == ""
    assert _clean("   ") == ""


def test_latin_titles_are_cut_on_a_word_boundary():
    """A character is not a unit of meaning: clipping 'networks' to 'netwo' is
    worse than losing the word."""
    long_title = "Everything about retrieval augmented generation and evaluation"
    fitted = _clean(long_title)
    assert len(fitted) <= MAX_TITLE_CHARS_LATIN
    assert not fitted.endswith(" ")
    assert long_title.startswith(fitted)
    assert fitted.split()[-1] in long_title.split()


def test_cjk_titles_use_the_narrower_budget():
    fitted = _clean("时" * 60)
    assert len(fitted) == MAX_TITLE_CHARS


@pytest.mark.asyncio
async def test_an_empty_goal_is_not_worth_an_llm_call(monkeypatch):
    def _boom(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("no call should be made for an empty goal")

    monkeypatch.setattr(topic_naming, "_render", _boom)
    assert await suggest_topic_name("   ") == ""


@pytest.mark.asyncio
async def test_a_failed_call_returns_empty_so_creation_can_still_proceed(monkeypatch):
    """The caller has a fallback; a goal that cannot be named must still be
    creatable."""

    async def _fail(*_args, **_kwargs):
        raise RuntimeError("provider is out of credits")

    monkeypatch.setattr("deeptutor.services.llm.complete", _fail)
    assert await suggest_topic_name("我想学线性代数", language="zh") == ""
