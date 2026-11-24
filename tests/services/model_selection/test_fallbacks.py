"""Read-only fallback roster used by the provider-failure copy (#2693 P0)."""

from __future__ import annotations

from deeptutor.services.model_selection.fallbacks import (
    MAX_FALLBACKS,
    configured_fallbacks,
    fallback_count,
)


def _catalog(entries) -> dict:
    return {"services": {"llm": {"fallbacks": entries}}}


def test_missing_key_means_no_fallbacks() -> None:
    assert configured_fallbacks({}) == []
    assert configured_fallbacks({"services": {}}) == []
    assert configured_fallbacks({"services": {"llm": {}}}) == []
    assert fallback_count({}) == 0


def test_reads_profile_and_model_pairs_in_order() -> None:
    entries = [
        {"profile_id": "local-vllm", "model_id": "qwen3-32b"},
        {"profile_id": "deepseek", "model_id": "deepseek-chat"},
    ]

    assert configured_fallbacks(_catalog(entries)) == entries
    assert fallback_count(_catalog(entries)) == 2


def test_drops_malformed_and_duplicate_entries() -> None:
    entries = [
        {"profile_id": "local-vllm", "model_id": "qwen3-32b"},
        {"profile_id": "local-vllm", "model_id": "qwen3-32b"},
        {"profile_id": "", "model_id": "x"},
        {"profile_id": "x"},
        "not-a-dict",
        None,
        {"profile_id": "  deepseek  ", "model_id": "  deepseek-chat  "},
    ]

    assert configured_fallbacks(_catalog(entries)) == [
        {"profile_id": "local-vllm", "model_id": "qwen3-32b"},
        {"profile_id": "deepseek", "model_id": "deepseek-chat"},
    ]


def test_bounded_to_the_planned_chain_cap() -> None:
    entries = [{"profile_id": f"p{i}", "model_id": f"m{i}"} for i in range(MAX_FALLBACKS + 3)]

    assert len(configured_fallbacks(_catalog(entries))) == MAX_FALLBACKS


def test_non_list_value_is_ignored() -> None:
    # A hand-edited file can hold anything; an error path must not care.
    assert configured_fallbacks(_catalog({"profile_id": "x"})) == []
    assert configured_fallbacks(_catalog("nonsense")) == []


def test_unreadable_catalog_degrades_to_zero(monkeypatch) -> None:
    import deeptutor.services.model_selection.fallbacks as fallbacks

    class _Broken:
        def load(self):
            raise RuntimeError("catalog is not initialised")

    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service",
        lambda: _Broken(),
    )

    assert fallbacks.configured_fallbacks() == []
