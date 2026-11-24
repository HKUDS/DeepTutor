"""Catalog plumbing for the ordered fallback chain (#2693 P3 backend)."""

from __future__ import annotations

from deeptutor.api.routers.settings import _preserve_llm_fallbacks
from deeptutor.services.config.model_catalog import (
    ModelCatalogService,
    _normalized_fallbacks,
)


def test_well_formed_entries_survive_and_duplicates_collapse() -> None:
    assert _normalized_fallbacks(
        [
            {"profile_id": "backup", "model_id": "m2"},
            {"profile_id": "backup", "model_id": "m2"},
            {"profile_id": " backup ", "model_id": " m3 "},
            {"profile_id": "", "model_id": "m4"},
            {"model_id": "m5"},
            "nonsense",
            None,
        ]
    ) == [
        {"profile_id": "backup", "model_id": "m2"},
        {"profile_id": "backup", "model_id": "m3"},
    ]


def test_entries_are_bounded_and_non_list_values_are_ignored() -> None:
    many = [{"profile_id": f"p{i}", "model_id": "m"} for i in range(10)]

    assert len(_normalized_fallbacks(many)) == 4
    assert _normalized_fallbacks({"profile_id": "x", "model_id": "y"}) == []
    assert _normalized_fallbacks(None) == []


def test_catalog_save_keeps_the_chain(tmp_path) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    catalog = service.load()
    catalog["services"]["llm"]["fallbacks"] = [{"profile_id": "backup", "model_id": "m2"}]

    saved = service.save(catalog)

    assert saved["services"]["llm"]["fallbacks"] == [{"profile_id": "backup", "model_id": "m2"}]


def test_catalog_save_drops_malformed_entries(tmp_path) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    catalog = service.load()
    catalog["services"]["llm"]["fallbacks"] = [{"profile_id": "backup"}, "junk"]

    saved = service.save(catalog)

    assert saved["services"]["llm"]["fallbacks"] == []


def test_apply_without_the_key_keeps_the_existing_chain() -> None:
    current = {"services": {"llm": {"fallbacks": [{"profile_id": "backup", "model_id": "m2"}]}}}

    merged = _preserve_llm_fallbacks("llm", {"active_profile_id": "p"}, current)

    # The settings UI does not edit the chain; applying a provider must not
    # delete a chain the operator configured by hand.
    assert merged["fallbacks"] == [{"profile_id": "backup", "model_id": "m2"}]
    assert merged["active_profile_id"] == "p"


def test_apply_with_the_key_replaces_the_chain() -> None:
    current = {"services": {"llm": {"fallbacks": [{"profile_id": "old", "model_id": "m"}]}}}

    merged = _preserve_llm_fallbacks(
        "llm", {"fallbacks": [{"profile_id": "new", "model_id": "m2"}]}, current
    )

    assert merged["fallbacks"] == [{"profile_id": "new", "model_id": "m2"}]


def test_other_services_are_untouched() -> None:
    incoming = {"active_profile_id": "p"}

    assert _preserve_llm_fallbacks("embedding", incoming, {"services": {}}) == incoming
