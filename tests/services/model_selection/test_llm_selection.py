from deeptutor.services.model_selection import (
    LLMSelection,
    apply_llm_selection_to_catalog,
    list_llm_options,
)


def _catalog():
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "p1",
                "active_model_id": "m1",
                "profiles": [
                    {
                        "id": "p1",
                        "name": "OpenRouter",
                        "binding": "openrouter",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "secret",
                        "api_version": "",
                        "extra_headers": {"x-secret": "nope"},
                        "models": [
                            {
                                "id": "m1",
                                "name": "Gemini Flash",
                                "model": "google/gemini-3-flash-preview",
                                "context_window": "1000000",
                            },
                            {
                                "id": "m2",
                                "name": "GPT Mini",
                                "model": "openai/gpt-4o-mini",
                            },
                        ],
                    },
                    {
                        "id": "p2",
                        "name": "Local",
                        "binding": "ollama",
                        "base_url": "http://localhost:11434/v1",
                        "api_key": "",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [{"id": "m3", "name": "Llama", "model": "llama3.2"}],
                    },
                ],
            },
            "embedding": {"active_profile_id": None, "active_model_id": None, "profiles": []},
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


def test_list_llm_options_is_redacted_and_marks_active_default():
    payload = list_llm_options(_catalog())
    assert payload["active"] == {"profile_id": "p1", "model_id": "m1"}
    assert [o["model_id"] for o in payload["options"]] == ["m1", "m2", "m3"]
    assert payload["options"][0]["is_active_default"] is True
    assert payload["options"][0]["context_window"] == 1000000
    assert "api_key" not in payload["options"][0]
    assert "base_url" not in payload["options"][0]
    assert "extra_headers" not in payload["options"][0]


def test_apply_llm_selection_to_catalog_returns_copy_with_selected_active_ids():
    selected = apply_llm_selection_to_catalog(
        _catalog(), LLMSelection(profile_id="p2", model_id="m3")
    )
    assert selected["services"]["llm"]["active_profile_id"] == "p2"
    assert selected["services"]["llm"]["active_model_id"] == "m3"


def test_apply_llm_selection_does_not_mutate_source_catalog():
    catalog = _catalog()
    apply_llm_selection_to_catalog(catalog, LLMSelection(profile_id="p2", model_id="m3"))
    assert catalog["services"]["llm"]["active_profile_id"] == "p1"
    assert catalog["services"]["llm"]["active_model_id"] == "m1"


def test_apply_llm_selection_rejects_model_not_in_profile():
    try:
        apply_llm_selection_to_catalog(_catalog(), LLMSelection(profile_id="p2", model_id="m1"))
    except ValueError as exc:
        assert "Invalid LLM selection" in str(exc)
    else:
        raise AssertionError("expected invalid selection to fail")


def test_llm_selection_from_payload_accepts_valid_reasoning_effort():
    selection = LLMSelection.from_payload(
        {"profile_id": "p1", "model_id": "m1", "reasoning_effort": "High"}
    )
    assert selection.reasoning_effort == "high"


def test_llm_selection_from_payload_rejects_unsupported_reasoning_effort():
    try:
        LLMSelection.from_payload(
            {"profile_id": "p1", "model_id": "m1", "reasoning_effort": "ultra"}
        )
    except ValueError as exc:
        assert "reasoning_effort" in str(exc)
    else:
        raise AssertionError("expected invalid reasoning_effort to fail")


def test_llm_selection_from_payload_without_reasoning_effort_defaults_to_none():
    selection = LLMSelection.from_payload({"profile_id": "p1", "model_id": "m1"})
    assert selection.reasoning_effort is None


def test_llm_selection_to_dict_round_trips_reasoning_effort():
    selection = LLMSelection(profile_id="p1", model_id="m1", reasoning_effort="xhigh")
    payload = selection.to_dict()
    assert payload["reasoning_effort"] == "xhigh"
    restored = LLMSelection.from_payload(payload)
    assert restored == selection


def test_llm_selection_to_dict_omits_reasoning_effort_when_unset():
    selection = LLMSelection(profile_id="p1", model_id="m1")
    assert "reasoning_effort" not in selection.to_dict()
