"""Tests for CriticAgent — parsing, invalid_sources handling, and audit loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deeptutor.agents.solve.agents.critic_agent import CriticAgent
from deeptutor.agents.solve.memory.scratchpad import (
    Entry,
    Plan,
    PlanStep,
    Scratchpad,
    Source,
)


@pytest.fixture
def scratchpad() -> Scratchpad:
    pad = Scratchpad(question="What is deep learning?")
    pad.plan = Plan(
        analysis="Test",
        steps=[
            PlanStep(id="S1", goal="Define deep learning", status="completed"),
        ],
    )
    pad.entries.append(
        Entry(
            step_id="S1",
            round=1,
            thought="Search for definition",
            action="web_search",
            action_input="deep learning definition",
            observation="Deep learning is a subset of ML...",
            self_note="Deep learning is a subset of ML",
            sources=[
                Source(type="web", url="https://example.com/dl", chunk_id=None),
            ],
        )
    )
    return pad


@pytest.fixture
def agent() -> CriticAgent:
    return CriticAgent(config={}, language="en", max_audit_rounds=2)


class TestParseAuditDecision:
    def test_parses_valid_json_response(self, agent: CriticAgent) -> None:
        raw = '''
        {
          "thought": "I should verify the URL",
          "action": "visit_url",
          "action_input": "https://example.com/dl",
          "self_note": "URL verified as alive",
          "verification_report": "URL is alive",
          "updated_notes": {"S1": "Confirmed deep learning is a subset of ML"},
          "invalid_sources": [{"source_id": "web-1", "url": "https://fake.invalid"}]
        }
        '''
        decision = agent._parse_audit_decision(raw)

        assert decision["action"] == "visit_url"
        assert decision["action_input"] == "https://example.com/dl"
        assert decision["self_note"] == "URL verified as alive"
        assert decision["verification_report"] == "URL is alive"
        assert decision["updated_notes"] == {"S1": "Confirmed deep learning is a subset of ML"}
        assert decision["invalid_sources"] == [{"source_id": "web-1", "url": "https://fake.invalid"}]

    def test_unknown_action_defaults_to_done(self, agent: CriticAgent) -> None:
        raw = '{"thought": "x", "action": "nonexistent_action", "action_input": "y"}'
        decision = agent._parse_audit_decision(raw)
        assert decision["action"] == "done"

    def test_missing_fields_use_defaults(self, agent: CriticAgent) -> None:
        raw = '{"thought": "test"}'
        decision = agent._parse_audit_decision(raw)

        assert decision["action"] == "done"
        assert decision["self_note"] == ""
        assert decision["verification_report"] == ""
        assert decision["updated_notes"] == {}
        assert decision["invalid_sources"] == []

    def test_invalid_json_returns_defaults(self, agent: CriticAgent) -> None:
        decision = agent._parse_audit_decision("not valid json at all")
        assert decision["action"] == "done"
        assert "parse" in decision["self_note"].lower()

    def test_case_insensitive_action_parsing(self, agent: CriticAgent) -> None:
        raw = '{"thought": "x", "action": "DONE", "action_input": ""}'
        decision = agent._parse_audit_decision(raw)
        assert decision["action"] == "done"

    def test_visit_url_action_recognized(self, agent: CriticAgent) -> None:
        raw = '{"thought": "x", "action": "visit_url", "action_input": "https://example.com"}'
        decision = agent._parse_audit_decision(raw)
        assert decision["action"] == "visit_url"


class TestMarkSourceInvalid:
    def test_mark_source_invalid_adds_to_metadata(self, scratchpad: Scratchpad) -> None:
        scratchpad.mark_source_invalid("web-1")
        assert "web-1" in scratchpad.metadata["invalid_source_ids"]

    def test_mark_invalid_twice_is_idempotent(self, scratchpad: Scratchpad) -> None:
        scratchpad.mark_source_invalid("web-1")
        scratchpad.mark_source_invalid("web-1")
        assert scratchpad.metadata["invalid_source_ids"].count("web-1") == 1


class TestAuditLoop:
    @pytest.mark.asyncio
    async def test_done_action_exits_early(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        agent._run_audit_round = AsyncMock(return_value={
            "thought": "All verified",
            "action": "done",
            "action_input": "",
            "self_note": "Done.",
            "verification_report": "All sources verified.",
            "updated_notes": {},
        })

        revised_pad, report = await agent.process(
            question="What is deep learning?",
            scratchpad=scratchpad,
        )

        assert report["rounds"] == 1
        assert report["summary"] == "All sources verified."
        # Done action means no tool execution
        agent._run_audit_round.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_rounds_respected(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        call_count = 0

        async def mock_round(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "thought": "More verification needed",
                "action": "visit_url",
                "action_input": "https://example.com",
                "self_note": "Checking...",
                "verification_report": "",
                "updated_notes": {},
            }

        with patch.object(agent, "_execute_audit_tool", new=AsyncMock(return_value=("alive", []))):
            agent._run_audit_round = mock_round
            _, report = await agent.process(
                question="What is deep learning?",
                scratchpad=scratchpad,
            )

        assert call_count == agent._max_audit_rounds

    @pytest.mark.asyncio
    async def test_invalid_sources_are_marked_on_scratchpad(
        self, agent: CriticAgent, scratchpad: Scratchpad
    ) -> None:
        round_results = []

        async def mock_round(*args, **kwargs):
            result = {
                "thought": "Found a bad URL",
                "action": "done",
                "action_input": "",
                "self_note": "Done auditing.",
                "verification_report": "One source invalid.",
                "updated_notes": {},
                "invalid_sources": [{"source_id": "web-1"}],
            }
            round_results.append(result)
            return result

        agent._run_audit_round = mock_round
        revised_pad, report = await agent.process(
            question="What is deep learning?",
            scratchpad=scratchpad,
        )

        assert "web-1" in revised_pad.metadata["invalid_source_ids"]

    @pytest.mark.asyncio
    async def test_visit_url_result_updates_sources(
        self, agent: CriticAgent, scratchpad: Scratchpad
    ) -> None:
        call_count = 0

        async def mock_round(*args, **kwargs):
            return {
                "thought": "Visiting URL",
                "action": "visit_url",
                "action_input": "https://example.com",
                "self_note": "Checking...",
                "verification_report": "",
                "updated_notes": {},
            }

        async def mock_tool(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return ("alive", [Source(type="web", url="https://example.com")])

        agent._run_audit_round = mock_round
        agent._execute_audit_tool = mock_tool
        agent._max_audit_rounds = 1  # ensure exactly one round

        revised_pad, report = await agent.process(
            question="What is deep learning?",
            scratchpad=scratchpad,
        )

        assert call_count == 1, "visit_url tool should have been called once"


class TestInvalidSourcesProcessing:
    def test_string_source_id_in_invalid_sources_list(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        decision = {
            "thought": "bad url",
            "action": "done",
            "action_input": "",
            "self_note": "",
            "verification_report": "",
            "updated_notes": {},
            "invalid_sources": ["web-1", "rag-2"],
        }

        for item in decision["invalid_sources"]:
            src_id = item if isinstance(item, str) else item.get("source_id")
            url = item.get("url") if isinstance(item, dict) else None
            if src_id:
                scratchpad.mark_source_invalid(src_id)
            elif url:
                src_id = scratchpad.find_source_id_by_url(url)
                if src_id:
                    scratchpad.mark_source_invalid(src_id)

        assert "web-1" in scratchpad.metadata["invalid_source_ids"]
        assert "rag-2" in scratchpad.metadata["invalid_source_ids"]

    def test_dict_source_id_in_invalid_sources_list(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        decision = {
            "invalid_sources": [{"source_id": "web-1", "url": "https://fake.example"}],
        }

        item = decision["invalid_sources"][0]
        src_id = item if isinstance(item, str) else item.get("source_id")
        assert src_id == "web-1"


class TestBuildReasonContext:
    def test_includes_question_and_plan(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        context = agent._build_reason_context("What is deep learning?", scratchpad)
        assert "What is deep learning?" in context
        assert "S1" in context

    def test_includes_completed_step_notes(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        context = agent._build_reason_context("What is deep learning?", scratchpad)
        assert "Deep learning is a subset of ML" in context


class TestFormatSources:
    def test_empty_sources_returns_placeholder(self, agent: CriticAgent) -> None:
        result = agent._format_sources([])
        assert result == "(no sources)"

    def test_formats_sources_with_id_type_and_label(self, agent: CriticAgent) -> None:
        sources = [
            {"id": "web-1", "type": "web", "url": "https://example.com", "file": None, "chunk_id": None},
            {"id": "rag-1", "type": "rag", "file": "ml-kb", "url": None, "chunk_id": "types"},
        ]
        result = agent._format_sources(sources)
        assert "web-1" in result
        assert "rag-1" in result
        assert "https://example.com" in result
        assert "ml-kb" in result
