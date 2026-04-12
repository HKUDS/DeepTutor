from __future__ import annotations

import pytest

from deeptutor.agents.research.request_config import (
    build_research_execution_policy,
    build_research_runtime_config,
    validate_research_request_config,
)
from deeptutor.services.prompt import get_prompt_manager


from unittest.mock import patch

@pytest.fixture(autouse=True)
def mock_env_and_llm():
    with patch("deeptutor.services.prompt.get_prompt_manager"), \
         patch("deeptutor.services.llm.get_llm_config"):
        yield

def test_validate_research_request_config_allows_empty_sources() -> None:
    request = validate_research_request_config(
        {
            "mode": "notes",
            "depth": "quick",
            "sources": [],
        }
    )

    assert request.sources == []


def test_build_research_execution_policy_maps_intent_to_internal_settings() -> None:
    request = validate_research_request_config(
        {
            "mode": "comparison",
            "depth": "deep",
            "sources": ["kb", "papers"],
        }
    )
    policy = build_research_execution_policy(
        request_config=request,
        enabled_tools={"code_execution"},
    )

    assert policy["planning"]["rephrase"]["enabled"] is True
    assert policy["planning"]["decompose"]["mode"] == "manual"
    assert policy["researching"]["execution_mode"] == "parallel"
    assert policy["researching"]["enable_rag"] is True
    assert policy["researching"]["enable_web_search"] is False
    assert policy["researching"]["enable_paper_search"] is True
    assert policy["researching"]["enable_run_code"] is True
    assert policy["reporting"]["style"] == "comparison"
    assert "outline_contract" not in policy["reporting"]
    assert policy["queue"]["max_length"] == 8


def test_build_research_execution_policy_supports_llm_only_mode() -> None:
    request = validate_research_request_config(
        {
            "mode": "report",
            "depth": "standard",
            "sources": [],
        }
    )
    policy = build_research_execution_policy(
        request_config=request,
        enabled_tools=set(),
    )

    assert policy["researching"]["enable_rag"] is False
    assert policy["researching"]["enable_web_search"] is False
    assert policy["researching"]["enable_paper_search"] is False
    assert policy["researching"]["enable_run_code"] is False
    assert policy["researching"]["enabled_tools"] == []
    assert policy["intent"]["sources"] == []


def test_build_research_runtime_config_uses_intent_and_sources() -> None:
    request = validate_research_request_config(
        {
            "mode": "learning_path",
            "depth": "standard",
            "sources": ["web"],
        }
    )

    runtime = build_research_runtime_config(
        base_config={
            "research": {
                "researching": {
                    "note_agent_mode": "auto",
                    "tool_timeout": 60,
                    "tool_max_retries": 2,
                    "paper_search_years_limit": 3,
                },
                "rag": {"default_mode": "hybrid"},
            },
            "tools": {"web_search": {"enabled": True}},
        },
        request_config=request,
        enabled_tools=set(),
        kb_name="research-kb",
    )

    assert runtime["planning"]["decompose"]["mode"] == "auto"
    assert runtime["planning"]["decompose"]["auto_max_subtopics"] == 4
    assert runtime["researching"]["max_iterations"] == 3
    assert runtime["researching"]["execution_mode"] == "series"
    assert runtime["researching"]["enable_web_search"] is True
    assert runtime["researching"]["enable_rag"] is False
    assert runtime["reporting"]["style"] == "learning_path"
    assert "outline_contract" not in runtime["reporting"]
    assert runtime["queue"]["max_length"] == 5
    assert runtime["rag"]["kb_name"] == "research-kb"
    assert runtime["intent"] == {
        "mode": "learning_path",
        "depth": "standard",
        "sources": ["web"],
        "manual_subtopics": None,
        "manual_max_iterations": None,
        "confirmed_outline": None,
    }


def test_reporting_mode_contracts_live_in_prompt_files() -> None:
    prompts = get_prompt_manager().load_prompts(
        module_name="research",
        agent_name="reporting_agent",
        language="en",
    )

    mode_contracts = prompts["mode_contracts"]
    assert "comparison document" in mode_contracts["comparison_single_pass"]
    assert "revision notes" in mode_contracts["study_notes_single_pass"]
    assert "study plan" in mode_contracts["learning_path_single_pass"]


@pytest.mark.parametrize(
    ("agent_name", "language", "expected_keys"),
    [
        (
            "rephrase_agent",
            "en",
            [
                "study_notes_rephrase",
                "report_rephrase",
                "comparison_rephrase",
                "learning_path_rephrase",
            ],
        ),
        (
            "rephrase_agent",
            "zh",
            [
                "study_notes_rephrase",
                "report_rephrase",
                "comparison_rephrase",
                "learning_path_rephrase",
            ],
        ),
        (
            "decompose_agent",
            "en",
            [
                "study_notes_decompose",
                "report_decompose",
                "comparison_decompose",
                "learning_path_decompose",
            ],
        ),
        (
            "decompose_agent",
            "zh",
            [
                "study_notes_decompose",
                "report_decompose",
                "comparison_decompose",
                "learning_path_decompose",
            ],
        ),
        (
            "research_agent",
            "en",
            [
                "study_notes_research",
                "report_research",
                "comparison_research",
                "learning_path_research",
            ],
        ),
        (
            "research_agent",
            "zh",
            [
                "study_notes_research",
                "report_research",
                "comparison_research",
                "learning_path_research",
            ],
        ),
        (
            "note_agent",
            "en",
            [
                "study_notes_note",
                "report_note",
                "comparison_note",
                "learning_path_note",
            ],
        ),
        (
            "note_agent",
            "zh",
            [
                "study_notes_note",
                "report_note",
                "comparison_note",
                "learning_path_note",
            ],
        ),
        (
            "reporting_agent",
            "zh",
            [
                "study_notes_single_pass",
                "report_single_pass",
                "comparison_single_pass",
                "learning_path_single_pass",
            ],
        ),
    ],
)
def test_research_agent_mode_contracts_load_from_prompt_files(
    agent_name: str,
    language: str,
    expected_keys: list[str],
) -> None:
    prompts = get_prompt_manager().load_prompts(
        module_name="research",
        agent_name=agent_name,
        language=language,
    )

    mode_contracts = prompts["mode_contracts"]
    for key in expected_keys:
        assert key in mode_contracts
        assert isinstance(mode_contracts[key], str)
        assert mode_contracts[key].strip()


# ----------------------------------------------------------------
# Mode-specific process template tests (ReportingAgent)
# ----------------------------------------------------------------

_MODE_PROCESS_KEYS = [
    "generate_outline",
    "write_introduction",
    "write_section_body",
    "write_conclusion",
    "write_full_report",
]

_NON_REPORT_MODES = ["study_notes", "comparison", "learning_path"]


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("mode", _NON_REPORT_MODES)
def test_reporting_mode_process_templates_exist(language: str, mode: str) -> None:
    """Each non-report mode must have all 5 mode-specific process keys."""
    prompts = get_prompt_manager().load_prompts(
        module_name="research",
        agent_name="reporting_agent",
        language=language,
    )
    process = prompts["process"]
    for base_key in _MODE_PROCESS_KEYS:
        full_key = f"{base_key}_{mode}"
        assert full_key in process, f"Missing process.{full_key} in {language}/reporting_agent.yaml"
        assert isinstance(process[full_key], str)
        assert len(process[full_key].strip()) > 50, f"process.{full_key} is too short"


@pytest.mark.parametrize("language", ["en", "zh"])
def test_reporting_generic_process_templates_still_exist(language: str) -> None:
    """Generic (report-mode) process templates must still be present as fallback."""
    prompts = get_prompt_manager().load_prompts(
        module_name="research",
        agent_name="reporting_agent",
        language=language,
    )
    process = prompts["process"]
    for base_key in _MODE_PROCESS_KEYS:
        assert base_key in process, f"Missing generic process.{base_key}"


def _simulate_get_mode_process_prompt(
    prompts: dict, report_style: str, base_key: str, default: str = ""
) -> str:
    """Replicate the logic of ReportingAgent._get_mode_process_prompt without importing it."""
    def _get(section: str, key: str, dflt: str = "") -> str:
        try:
            return prompts[section][key]
        except (KeyError, TypeError):
            return dflt

    if report_style and report_style != "report":
        mode_key = f"{base_key}_{report_style}"
        mode_prompt = _get("process", mode_key, "")
        if mode_prompt:
            return mode_prompt
    return _get("process", base_key, default)


def test_get_mode_process_prompt_selects_mode_template() -> None:
    """Mode-specific template is preferred over generic for non-report modes."""
    prompts = get_prompt_manager().load_prompts(
        module_name="research",
        agent_name="reporting_agent",
        language="en",
    )

    mode_prompt = _simulate_get_mode_process_prompt(prompts, "study_notes", "generate_outline")
    generic_prompt = prompts["process"]["generate_outline"]

    assert mode_prompt != generic_prompt
    assert "study" in mode_prompt.lower()


def test_get_mode_process_prompt_falls_back_for_report() -> None:
    """For report mode, the generic template is used as fallback."""
    prompts = get_prompt_manager().load_prompts(
        module_name="research",
        agent_name="reporting_agent",
        language="en",
    )

    mode_prompt = _simulate_get_mode_process_prompt(prompts, "report", "generate_outline")
    generic_prompt = prompts["process"]["generate_outline"]

    assert mode_prompt == generic_prompt
