"""Follow-up chips: the reactions offered under the latest answer."""

from __future__ import annotations

from deeptutor.services.chat_followups import _payload, _select
from deeptutor.services.chat_hints import _Material


def _material(answer: str) -> _Material:
    return _Material(
        transcript=[("user", "explain it"), ("assistant", answer)],
        transcript_length=2,
    )


def test_code_without_comments_offers_annotation() -> None:
    ids = _select(_material("Here:\n```python\nx = 1\nprint(x)\n```"))
    assert "comments" in ids


def test_failure_without_a_fix_offers_closure() -> None:
    assert "closure" in _select(_material("A common failure here is an error."))
    # Once the cause/fix is present, the loop is already closed.
    assert "closure" not in _select(_material("It fails; the cause is X; fix it by doing Y."))


def test_every_answer_offers_depth_dials_and_is_bounded() -> None:
    ids = _select(_material("X is Y."))
    assert ids[:2] == ["simpler", "deeper"]
    assert 0 < len(ids) <= 6
    assert len(ids) == len(set(ids))


def test_a_missing_summary_is_offered_but_not_when_present() -> None:
    assert "summarize" in _select(_material("Lots of detail and no wrap-up."))
    assert "summarize" not in _select(_material("In short: X is Y."))


def test_payload_is_localised_and_carries_the_prompt() -> None:
    zh = _payload("simpler", True)
    en = _payload("simpler", False)
    assert zh["id"] == en["id"] == "simpler"
    assert zh["label"] != en["label"]
    assert zh["prompt"] and en["prompt"]
    # An unknown id degrades to itself rather than raising.
    assert _payload("nope", False)["id"] == "nope"
