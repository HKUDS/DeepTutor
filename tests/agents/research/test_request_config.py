"""Tests for the research request-config helpers.

The legacy multi-agent prompt manifests (rephrase_agent.yaml,
decompose_agent.yaml, research_agent.yaml, note_agent.yaml,
reporting_agent.yaml) were deleted in the agentic-loop refactor. The
``sources`` knob was retired alongside them — tool composition now
goes through ``compose_enabled_tools`` like chat, driven by the user's
composer toggles plus the attached KB (auto-mounted as ``rag``). What
remains is coverage for the public ``request_config`` helpers that
drive runtime composition.
"""

from __future__ import annotations

from deeptutor.agents.research.request_config import (
    build_research_execution_policy,
    build_research_runtime_config,
    validate_research_request_config,
)


def test_validate_research_request_config_accepts_minimal_payload() -> None:
    request = validate_research_request_config(
        {
            "mode": "notes",
            "depth": "quick",
        }
    )

    assert request.mode == "notes"
    assert request.depth == "quick"


def test_build_research_execution_policy_maps_intent_to_internal_settings() -> None:
    request = validate_research_request_config(
        {
            "mode": "comparison",
            "depth": "deep",
        }
    )
    policy = build_research_execution_policy(request_config=request)

    assert policy["planning"]["rephrase"]["enabled"] is True
    assert policy["planning"]["decompose"]["mode"] == "manual"
    assert policy["researching"]["execution_mode"] == "parallel"
    # Source-derived enable_* flags were removed: tool composition is
    # delegated to the shared ``compose_enabled_tools`` policy at runtime.
    assert "enable_rag" not in policy["researching"]
    assert "enable_web_search" not in policy["researching"]
    assert "enable_paper_search" not in policy["researching"]
    assert "enable_run_code" not in policy["researching"]
    assert "enabled_tools" not in policy["researching"]
    assert policy["reporting"]["style"] == "comparison"
    assert policy["queue"]["max_length"] == 8


def test_build_research_runtime_config_carries_intent_without_sources() -> None:
    request = validate_research_request_config(
        {
            "mode": "learning_path",
            "depth": "standard",
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
        },
        request_config=request,
        kb_name="research-kb",
    )

    assert runtime["planning"]["decompose"]["mode"] == "auto"
    assert runtime["planning"]["decompose"]["auto_max_subtopics"] == 4
    assert runtime["researching"]["max_iterations"] == 3
    assert runtime["researching"]["execution_mode"] == "series"
    assert runtime["reporting"]["style"] == "learning_path"
    assert runtime["queue"]["max_length"] == 5
    assert runtime["rag"]["kb_name"] == "research-kb"
    assert runtime["intent"]["mode"] == "learning_path"
    assert runtime["intent"]["depth"] == "standard"
    assert "sources" not in runtime["intent"]
    assert "tools" not in runtime  # no source-derived tools overrides
