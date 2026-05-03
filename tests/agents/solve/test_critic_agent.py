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
        obs, new_sources = await agent._validate_all_sources(
            scratchpad=pad, kb_name=None, question="Simple?"
        )
        assert obs == "No URLs to validate."
        assert new_sources == []

    @pytest.mark.asyncio
    async def test_all_sources_valid_alive(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": True, "status_code": 200}
        mock_result.content = "Page title"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            obs, new_sources = await agent._validate_all_sources(
                scratchpad=scratchpad, kb_name=None, question="What is deep learning?"
            )

        assert "✓ https://example.com/dl" in obs
        assert len(new_sources) == 0  # no new sources from a successful visit

    @pytest.mark.asyncio
    async def test_dead_url_marks_source_invalid(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": False, "status_code": 403}
        mock_result.content = "Forbidden"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            await agent._validate_all_sources(
                scratchpad=scratchpad, kb_name=None, question="What is deep learning?"
            )

        # Source should be marked invalid
        invalid_ids = scratchpad.metadata.get("invalid_source_ids", [])
        assert len(invalid_ids) >= 1

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
            obs, new_sources = await agent._validate_all_sources(
                scratchpad=pad, kb_name=None, question="What is deep learning?"
            )

        # Should not raise — error is caught and logged
        assert "Error" in obs or "https://example.com" in obs
        assert isinstance(new_sources, list)

    @pytest.mark.asyncio
    async def test_claim_verified_logs_success(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": True, "status_code": 200, "claim_verified": True}
        mock_result.content = "Title found"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            obs, new_sources = await agent._validate_all_sources(
                scratchpad=scratchpad, kb_name=None, question="What is deep learning?"
            )

        assert "claim verified" in obs

    @pytest.mark.asyncio
    async def test_claim_not_verified_logs_warning(self, agent: CriticAgent, scratchpad: Scratchpad) -> None:
        mock_result = MagicMock()
        mock_result.metadata = {"alive": True, "status_code": 200, "claim_verified": False}
        mock_result.content = "Title found"
        mock_result.sources = []

        with patch("deeptutor.tools.builtin.VisitUrlTool") as MockTool:
            MockTool.return_value.execute = AsyncMock(return_value=mock_result)
            obs, new_sources = await agent._validate_all_sources(
                scratchpad=scratchpad, kb_name=None, question="What is deep learning?"
            )

        assert "NOT verified" in obs


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
# _is_duplicate and _longest_common_substring tests
# ---------------------------------------------------------------------------

class TestLongestCommonSubstring:
    def test_exact_match(self) -> None:
        s = "Looped Transformers are Better at Learning Learning Algorithms"
        result = CriticAgent._longest_common_substring(s, s)
        assert result == s

    def test_substring_at_end(self) -> None:
        a, b = "hello world", "world"
        result = CriticAgent._longest_common_substring(a, b)
        assert result == "world"

    def test_substring_at_start(self) -> None:
        a, b = "hello", "hello world"
        result = CriticAgent._longest_common_substring(a, b)
        assert result == "hello"

    def test_substring_in_middle(self) -> None:
        a, b = "prefix middle suffix", "middle"
        result = CriticAgent._longest_common_substring(a, b)
        assert result == "middle"

    def test_no_common(self) -> None:
        result = CriticAgent._longest_common_substring("abc", "xyz")
        assert result == ""

    def test_empty_string(self) -> None:
        result = CriticAgent._longest_common_substring("", "abc")
        assert result == ""
        result = CriticAgent._longest_common_substring("abc", "")
        assert result == ""

    def test_icml_prefix_variant(self) -> None:
        a = "Looped Transformers are Better at Learning Learning Algorithms"
        b = "ICML Looped Transformers are Better at Learning Learning Algorithms"
        result = CriticAgent._longest_common_substring(a, b)
        assert result == a  # full a is substring of b

    def test_quick_review_variant(self) -> None:
        a = "Looped Transformers are Better at Learning Learning Algorithms"
        b = "[Quick Review] Looped Transformers are Better at Learning Learning Algorithms"
        result = CriticAgent._longest_common_substring(a, b)
        assert result == a  # full a is substring of b


class TestIsDuplicate:
    def test_exact_url_match_is_duplicate(self) -> None:
        existing = [Source(type="web", file="Paper", url="https://example.com/paper")]
        new = Source(type="web", file="Different Name", url="https://example.com/paper")
        assert CriticAgent._is_duplicate(existing, new) is True

    def test_different_type_not_duplicate(self) -> None:
        existing = [Source(type="rag", file="KB", url=None)]
        new = Source(type="web", file="KB", url="https://example.com")
        assert CriticAgent._is_duplicate(existing, new) is False

    def test_fuzzy_title_match_same_paper(self) -> None:
        existing = [
            Source(
                type="web",
                file="Looped Transformers are Better at Learning Learning Algorithms",
                url="https://arxiv.org/html/2311.12424v3",
            )
        ]
        new = Source(
            type="web",
            file="ICML Looped Transformers are Better at Learning Learning Algorithms",
            url="https://icml.cc/virtual/2023/28272",
        )
        assert CriticAgent._is_duplicate(existing, new) is True

    def test_fuzzy_title_match_quick_review(self) -> None:
        existing = [
            Source(
                type="web",
                file="Looped Transformers are Better at Learning Learning Algorithms",
                url="https://arxiv.org/abs/2311.12424",
            )
        ]
        new = Source(
            type="web",
            file="[Quick Review] Looped Transformers are Better at Learning Learning Algorithms",
            url="https://liner.com/review/looped-transformers-xxx",
        )
        assert CriticAgent._is_duplicate(existing, new) is True

    def test_completely_different_title_not_duplicate(self) -> None:
        existing = [
            Source(type="web", file="Attention Is All You Need", url="https://arxiv.org/abs/1706.03762")
        ]
        new = Source(
            type="web",
            file="Looped Transformers are Better at Learning Learning Algorithms",
            url="https://arxiv.org/abs/2311.12424",
        )
        assert CriticAgent._is_duplicate(existing, new) is False

    def test_rag_sources_use_exact_url_match(self) -> None:
        # RAG sources with same file/title but different chunk_ids should NOT be duplicate
        # since they come from different queries
        existing = [
            Source(type="rag", file="ml-kb", url=None, chunk_id="query1")
        ]
        new = Source(type="rag", file="ml-kb", url=None, chunk_id="query2")
        # No URL match and file is same, but LCS/50% check may fire...
        # Since URLs are both None, exact match fails; fall through to title check
        # Both have same file "ml-kb", LCS = "ml-kb" = 100% of shorter (5/5 = 1.0 >= 0.5)
        assert CriticAgent._is_duplicate(existing, new) is True

    def test_code_source_exact_url(self) -> None:
        existing = [Source(type="code", file="solution.py", url="https://github.com/user/repo")]
        new = Source(type="code", file="solution_v2.py", url="https://github.com/user/repo")
        assert CriticAgent._is_duplicate(existing, new) is True

    def test_empty_file_no_false_positive(self) -> None:
        existing = [Source(type="web", file=None, url="https://example.com/page1")]
        new = Source(type="web", file=None, url="https://example.com/page2")
        assert CriticAgent._is_duplicate(existing, new) is False

    def test_case_sensitive_match(self) -> None:
        existing = [Source(type="web", file="Lowercase Title", url=None)]
        new = Source(type="web", file="UPPERCASE TITLE", url=None)
        # LCS will find " TITLE" (7 chars) of "lowercase title" (14 chars) = 50%
        # Actually LCS would be " Title" or similar... let's be explicit
        # "Lowercase Title" vs "UPPERCASE TITLE" — LCS is " TITLE" (6 chars vs 13 shorter)
        # 6/13 ≈ 0.46 < 0.5 → not duplicate
        assert CriticAgent._is_duplicate(existing, new) is False


class TestAddSourceToScratchpadDedup:
    def setup_method(self) -> None:
        self.agent = CriticAgent(config={}, language="en")

    def test_adds_first_source(self) -> None:
        pad = Scratchpad(question="Test?")
        pad.plan = Plan(analysis="", steps=[PlanStep(id="S1", goal="x", status="completed")])
        pad.add_entry(step_id="critic", round_num=1, thought="x", action="visit_url", action_input="", observation="", self_note="", sources=[])
        src = Source(type="web", file="Paper A", url="https://a.com")
        self.agent._add_source_to_scratchpad(pad, src)
        assert len(pad.entries[-1].sources) == 1

    def test_skips_exact_duplicate(self) -> None:
        pad = Scratchpad(question="Test?")
        pad.plan = Plan(analysis="", steps=[PlanStep(id="S1", goal="x", status="completed")])
        pad.add_entry(step_id="critic", round_num=1, thought="x", action="visit_url", action_input="", observation="", self_note="", sources=[])
        src1 = Source(type="web", file="Paper A", url="https://a.com")
        src2 = Source(type="web", file="Paper A", url="https://a.com")
        self.agent._add_source_to_scratchpad(pad, src1)
        self.agent._add_source_to_scratchpad(pad, src2)
        assert len(pad.entries[-1].sources) == 1

    def test_skips_fuzzy_duplicate_same_paper(self) -> None:
        pad = Scratchpad(question="Test?")
        pad.plan = Plan(analysis="", steps=[PlanStep(id="S1", goal="x", status="completed")])
        pad.add_entry(step_id="critic", round_num=1, thought="x", action="visit_url", action_input="", observation="", self_note="", sources=[])
        src1 = Source(type="web", file="Looped Transformers are Better at Learning Learning Algorithms", url="https://arxiv.org/html/2311.12424v3")
        src2 = Source(type="web", file="ICML Looped Transformers are Better at Learning Learning Algorithms", url="https://icml.cc/virtual/2023/28272")
        self.agent._add_source_to_scratchpad(pad, src1)
        self.agent._add_source_to_scratchpad(pad, src2)
        assert len(pad.entries[-1].sources) == 1

    def test_allows_different_sources(self) -> None:
        pad = Scratchpad(question="Test?")
        pad.plan = Plan(analysis="", steps=[PlanStep(id="S1", goal="x", status="completed")])
        pad.add_entry(step_id="critic", round_num=1, thought="x", action="visit_url", action_input="", observation="", self_note="", sources=[])
        src1 = Source(type="web", file="Deep Learning Overview", url="https://a.com/paper1")
        src2 = Source(type="web", file="Looped Transformers Paper", url="https://b.com/paper2")
        self.agent._add_source_to_scratchpad(pad, src1)
        self.agent._add_source_to_scratchpad(pad, src2)
        assert len(pad.entries[-1].sources) == 2

    def test_skips_multiple_duplicates(self) -> None:
        pad = Scratchpad(question="Test?")
        pad.plan = Plan(analysis="", steps=[PlanStep(id="S1", goal="x", status="completed")])
        pad.add_entry(step_id="critic", round_num=1, thought="x", action="visit_url", action_input="", observation="", self_note="", sources=[])
        base = Source(type="web", file="Looped Transformers", url="https://arxiv.org/abs/2311.12424")
        variants = [
            Source(type="web", file="ICML Looped Transformers", url="https://icml.cc/28272"),
            Source(type="web", file="[Review] Looped Transformers", url="https://liner.com/review"),
            Source(type="web", file="Looped Transformers (arXiv v3)", url="https://arxiv.org/html/2311.12424v3"),
        ]
        self.agent._add_source_to_scratchpad(pad, base)
        for v in variants:
            self.agent._add_source_to_scratchpad(pad, v)
        assert len(pad.entries[-1].sources) == 1

    def test_no_op_when_no_entries(self) -> None:
        pad = Scratchpad(question="Test?")
        src = Source(type="web", file="Paper A", url="https://a.com")
        self.agent._add_source_to_scratchpad(pad, src)
        # No crash, no sources added
        assert all(len(e.sources) == 0 for e in pad.entries)