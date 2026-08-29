"""Language resolution for automatic book creation."""

from __future__ import annotations

import pytest

from deeptutor.book.language import resolve_book_language


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        ("Please create a Fourier book in Japanese", "ja"),
        ("Write about Japanese history in Spanish", "es"),
        ("请用日语整理机器学习入门内容", "ja"),
        ("日本語で書いてください", "ja"),
        ("한국어로 정리해 주세요", "ko"),
        ("Сделай книгу по алгоритмам", "ru"),
        ("帮我整理机器学习入门内容", "zh"),
        ("Please create a book about Japanese history", "en"),
    ],
)
def test_auto_uses_high_confidence_language_signals(intent: str, expected: str) -> None:
    assert (
        resolve_book_language(
            user_intent=intent,
            requested_language="auto",
            fallback_language="en",
        )
        == expected
    )


def test_auto_falls_back_to_the_interface_language() -> None:
    assert (
        resolve_book_language(
            user_intent="Create a book about distributed systems",
            requested_language="auto",
            fallback_language="zh",
        )
        == "zh"
    )


def test_explicit_language_selection_wins_over_intent_signals() -> None:
    assert (
        resolve_book_language(
            user_intent="请用日语整理内容",
            requested_language="zh",
            fallback_language="en",
        )
        == "zh"
    )


def test_traditional_chinese_requests_resolve_to_the_regional_code() -> None:
    assert (
        resolve_book_language(
            user_intent="請用繁體中文寫一本演算法書",
            requested_language="auto",
            fallback_language="en",
        )
        == "zh-tw"
    )
