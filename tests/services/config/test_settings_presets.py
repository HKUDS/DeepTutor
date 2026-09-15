from __future__ import annotations

from deeptutor.services.config.settings_presets import (
    SETTINGS_PRESETS_SCHEMA_VERSION,
    get_settings_preset,
    list_settings_presets,
)


def test_the_settings_preset_catalog_is_stable_and_value_free() -> None:
    presets = list_settings_presets()

    assert [preset["id"] for preset in presets] == [
        "basic_text",
        "local_multimodal",
        "university_study",
        "full_generation",
    ]
    forbidden = ("api_key", "base_url", "password", "secret", "localhost")
    for preset in presets:
        rendered = repr(preset).lower()
        assert not any(value in rendered for value in forbidden)
    assert all(preset["parser"] for preset in presets)


def test_a_preset_has_the_draft_payloads_the_apply_flow_already_writes() -> None:
    preset = get_settings_preset("university_study")
    assert preset is not None

    draft = preset.draft_extensions()

    assert draft["document_parsing"] == {"engine": "markitdown"}
    assert draft["enabled_tools"] == {
        "enabled_tools": ["brainstorm", "web_search", "paper_search", "reason"]
    }


def test_unknown_presets_are_rejected_without_inventing_a_default() -> None:
    assert get_settings_preset("do-everything") is None
    assert SETTINGS_PRESETS_SCHEMA_VERSION == "deeptutor.settings-presets/v1"
