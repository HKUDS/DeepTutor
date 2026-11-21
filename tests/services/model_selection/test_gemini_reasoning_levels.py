"""Reasoning levels offered per Gemini family.

The selector and LightRAG validation both read ``supported_reasoning_efforts``,
so a level listed here is a level DeepTutor will send. ``gemini-3.8-flash``
rejects ``"minimal"`` with ``Thinking level MINIMAL is not supported for this
model`` (#2702), which makes the whole ``gemini-3`` prefix too coarse a key.
"""

from __future__ import annotations

from deeptutor.services.model_selection.reasoning import supported_reasoning_efforts


def test_flash_38_does_not_offer_minimal() -> None:
    assert supported_reasoning_efforts("gemini", "gemini-3.8-flash") == [
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("google", "models/gemini-3.8-flash") == [
        "low",
        "medium",
        "high",
    ]


def test_neighbouring_gemini_families_keep_their_own_floor() -> None:
    assert supported_reasoning_efforts("gemini", "gemini-3.6-flash") == [
        "minimal",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("gemini", "gemini-2.5-pro") == [
        "minimal",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("gemini", "gemini-2.5-flash") == [
        "none",
        "low",
        "medium",
        "high",
    ]


def test_custom_endpoint_aimed_at_the_model_inherits_the_rule() -> None:
    assert supported_reasoning_efforts("custom", "gemini-3.8-flash") == [
        "low",
        "medium",
        "high",
    ]
