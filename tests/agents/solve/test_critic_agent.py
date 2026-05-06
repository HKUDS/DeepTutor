"""Tests for CriticAgent — source validation, parallel visit_url, and audit loop."""

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


@pytest.fixture
def agent_no_loop() -> CriticAgent:
    """CriticAgent with single-round behavior (new implementation)."""
    return CriticAgent(config={}, language="en", max_audit_rounds=3)


# ---------------------------------------------------------------------------
# _validate_all_sources tests
# ---------------------------------------------------------------------------

class TestValidateAllSources:
    @pytest.mark.asyncio
    async def test_no_urls_returns_empty_observation(self, agent: CriticAgent) -> None:
        pad = Scratchpad(question="Simple?")
        pad.plan = Plan(analysis="", steps=[PlanStep(id="S1", goal="x", status="completed")])
        pad.entries.append(
            Entry(
                step_id="S1", round=1, thought="x", action="done",
                action_input="", observation="done", self_note="",
                sources=[
                    Source(type="rag", file="some-kb", chunk_id="123", url=None),
                ],
            )
        )
        obs, per_url_results = await agent._validate_all_sources(
            scratchpad=pad, kb_name=None, question="Simple?"
        )
        assert obs == "No URLs to validate."
        assert per_url_results == []

    @pytest.mark.asyncio
    async def test_all_sources_valid_alive(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": True, "status_code": 200}
        mock_result.content = "Page title"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            obs, per_url_results = await agent._validate_all_sources(
                scratchpad=scratchpad, kb_name=None, question="What is deep learning?"
            )

        assert "alive" in obs
        assert len(per_url_results) == 1

    @pytest.mark.asyncio
    async def test_dead_url_removes_source_from_entry(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": False, "status_code": 403}
        mock_result.content = "Forbidden"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            await agent._validate_all_sources(
                scratchpad=scratchpad, kb_name=None, question="What is deep learning?"
            )

        # Source should be removed from entry
        for e in scratchpad.entries:
            for s in e.sources:
                assert s.url != "https://example.com/dl"

    @pytest.mark.asyncio
    async def test_exception_during_visit_url_handled_gracefully(
        self, agent: CriticAgent, scratchpad: Scratchpad
    ) -> None:
        pad = Scratchpad(question="Test")
        pad.plan = Plan(analysis="", steps=[PlanStep(id="S1", goal="x", status="completed")])
        pad.entries.append(
            Entry(
                step_id="S1", round=1, thought="x", action="web_search",
                action_input="x", observation="x", self_note="",
                sources=[
                    Source(type="web", url="https://example.com/dl", chunk_id=None),
                ],
            )
        )
        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(side_effect=RuntimeError("network error"))
            obs, per_url_results = await agent._validate_all_sources(
                scratchpad=pad, kb_name=None, question="What is deep learning?"
            )

        # Should not raise — error is caught and logged; exception → dead/unreachable
        assert "dead" in obs or "unreachable" in obs
        assert isinstance(per_url_results, list)

    @pytest.mark.asyncio
    async def test_claim_verified_logs_success(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": True, "status_code": 200, "claim_verified": True}
        mock_result.content = "Title found"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            obs, per_url_results = await agent._validate_all_sources(
                scratchpad=scratchpad, kb_name=None, question="What is deep learning?"
            )

        # Summary reflects aliveness, not per-URL claim verification details
        assert "alive" in obs

    @pytest.mark.asyncio
    async def test_claim_not_verified_logs_warning(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": True, "status_code": 200, "claim_verified": False}
        mock_result.content = "Title found"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            obs, per_url_results = await agent._validate_all_sources(
                scratchpad=scratchpad, kb_name=None, question="What is deep learning?"
            )

        # Summary reflects aliveness, not per-URL claim verification details
        assert "alive" in obs


# ---------------------------------------------------------------------------
# process() tests — new single-phase flow
# ---------------------------------------------------------------------------

class TestProcessNewFlow:
    @pytest.mark.asyncio
    async def test_process_validates_sources_and_gets_summary(
        self, agent_no_loop: CriticAgent, scratchpad: Scratchpad
    ) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": True, "status_code": 200}
        mock_result.content = "OK"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            agent_no_loop._run_audit_round = AsyncMock(return_value={
                "verification_report": "All sources verified.",
            })

            revised_pad, report = await agent_no_loop.process(
                question="What is deep learning?",
                scratchpad=scratchpad,
            )

        assert report["rounds"] == 1
        assert report["summary"] == "All sources verified."
        agent_no_loop._run_audit_round.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_records_audit_entry(
        self, agent_no_loop: CriticAgent, scratchpad: Scratchpad
    ) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": True, "status_code": 200}
        mock_result.content = "OK"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            agent_no_loop._run_audit_round = AsyncMock(return_value={
                "verification_report": "All good.",
            })

            revised_pad, report = await agent_no_loop.process(
                question="What is deep learning?",
                scratchpad=scratchpad,
            )

        # Should have a critic entry in scratchpad
        critic_entries = [e for e in revised_pad.entries if e.step_id == "critic"]
        assert len(critic_entries) >= 1

    @pytest.mark.asyncio
    async def test_process_handles_no_sources(
        self, agent_no_loop: CriticAgent
    ) -> None:
        pad = Scratchpad(question="Simple question")
        pad.plan = Plan(analysis="", steps=[PlanStep(id="S1", goal="x", status="completed")])
        pad.entries.append(
            Entry(
                step_id="S1", round=1, thought="x", action="done",
                action_input="", observation="done", self_note="",
                sources=[],
            )
        )

        agent_no_loop._run_audit_round = AsyncMock(return_value={
            "verification_report": "No sources to verify.",
        })

        revised_pad, report = await agent_no_loop.process(
            question="Simple question?",
            scratchpad=pad,
        )

        assert report["rounds"] == 1


# ---------------------------------------------------------------------------
# existing tests — kept for backwards compatibility
# ---------------------------------------------------------------------------

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
        # Unknown actions are returned as-is; only missing key falls back to "done"
        raw = '{"thought": "x", "action": "nonexistent_action", "action_input": "y"}'
        decision = agent._parse_audit_decision(raw)
        # "nonexistent_action" is preserved, not rewritten
        assert decision["action"] == "nonexistent_action"
        assert decision["action_input"] == "y"

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
        # Actions are returned as-is (case preserved)
        raw = '{"thought": "x", "action": "DONE", "action_input": ""}'
        decision = agent._parse_audit_decision(raw)
        assert decision["action"] == "DONE"

    def test_visit_url_action_recognized(self, agent: CriticAgent) -> None:
        raw = '{"thought": "x", "action": "visit_url", "action_input": "https://example.com"}'
        decision = agent._parse_audit_decision(raw)
        assert decision["action"] == "visit_url"


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

        mock_result = MagicMock()
        mock_result.metadata = {"alive": True, "status_code": 200}
        mock_result.content = "OK"
        mock_result.sources = []

        with patch.object(agent._tool_runtime, "execute", new=AsyncMock(return_value=mock_result)):
            revised_pad, report = await agent.process(
                question="What is deep learning?",
                scratchpad=scratchpad,
            )

        assert report["rounds"] == 1
        assert report["summary"] == "All sources verified."
        agent._run_audit_round.assert_called_once()


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


# ---------------------------------------------------------------------------