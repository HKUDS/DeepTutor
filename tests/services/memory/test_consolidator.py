from __future__ import annotations

from deeptutor.services.memory.consolidator import (
    _filter_banned,
    _has_banned,
    _parse_ops_response,
)
from deeptutor.services.memory.ops import AddOp, DeleteOp, EditOp


def test_has_banned_catches_english_absolutes() -> None:
    assert _has_banned("user deeply understands")
    assert _has_banned("Mastered the chain rule")
    assert _has_banned("always picks examples first")


def test_has_banned_catches_chinese_absolutes() -> None:
    assert _has_banned("完全理解 ε-δ")
    assert _has_banned("总是从极限切入")
    assert _has_banned("用户彻底掌握了")


def test_has_banned_allows_cjk_quoted_phrase() -> None:
    # When wrapped in 「」 the phrase is a verbatim user quote.
    assert not _has_banned("用户原话「彻底搞懂」是指掌握了符号")


def test_has_banned_allows_double_quoted_phrase() -> None:
    assert not _has_banned('user said "deeply" — context-specific')


def test_has_banned_passes_neutral_text() -> None:
    assert not _has_banned("Uses geometric intuition for limits")
    assert not _has_banned("在 5 次 chat 互动中，呈现对极限的几何直觉")


def test_filter_banned_drops_violating_ops_only() -> None:
    ok_op = AddOp(section="S", text="uses Anki", refs=["chat:01HZK4AAAAAAAAAAAAAAAAAAAA"])
    bad_op = AddOp(
        section="S",
        text="deeply understands FSRS",
        refs=["chat:01HZK4BBBBBBBBBBBBBBBBBBBB"],
    )
    edit_bad = EditOp(
        target_id="m_01HZK4ABCDEFGHJKMNPQRSTVWX",
        new_text="mastered set theory",
        new_refs=["chat:01HZK4CCCCCCCCCCCCCCCCCCCC"],
    )
    delete_neutral = DeleteOp(
        target_id="m_01HZK5ABCDEFGHJKMNPQRSTVWX",
        reason="stale",
    )

    kept = _filter_banned([ok_op, bad_op, edit_bad, delete_neutral])
    assert kept == [ok_op, delete_neutral]


def test_parse_ops_strips_code_fences() -> None:
    raw = '```json\n{"ops": [{"op": "add", "section": "S", "text": "ok", "refs": ["chat:01HZK4AAAAAAAAAAAAAAAAAAAA"]}]}\n```'
    ops = _parse_ops_response(raw)
    assert len(ops) == 1
    assert isinstance(ops[0], AddOp)
    assert ops[0].text == "ok"


def test_parse_ops_handles_prose_prefix() -> None:
    raw = 'Here is my answer:\n{"ops": []}'
    assert _parse_ops_response(raw) == []


def test_parse_ops_returns_empty_on_garbage() -> None:
    assert _parse_ops_response("not json at all") == []
    assert _parse_ops_response('{"not_ops": []}') == []
