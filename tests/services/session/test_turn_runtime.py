"""Tests for TurnRuntimeManager helper functions and lightweight behaviour."""

from __future__ import annotations

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.turn_runtime import (
    _artifact_attachments,
    _clip_text,
    _extract_followup_question_context,
    _extract_memory_references,
    _extract_persist_user_message,
    _format_followup_question_context,
    _narration_marker_call_id,
    _should_capture_assistant_content,
)

# ---------------------------------------------------------------------------
# _should_capture_assistant_content
# ---------------------------------------------------------------------------


class TestShouldCaptureAssistantContent:
    def test_content_without_call_id_is_captured(self) -> None:
        event = StreamEvent(type=StreamEventType.CONTENT, content="hello")
        assert _should_capture_assistant_content(event) is True

    def test_content_with_final_response_kind_is_captured(self) -> None:
        event = StreamEvent(
            type=StreamEventType.CONTENT,
            content="answer",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        )
        assert _should_capture_assistant_content(event) is True

    def test_content_with_non_final_call_kind_not_captured(self) -> None:
        event = StreamEvent(
            type=StreamEventType.CONTENT,
            content="internal",
            metadata={"call_id": "c1", "call_kind": "llm_reasoning"},
        )
        assert _should_capture_assistant_content(event) is False

    def test_agent_loop_round_content_is_captured(self) -> None:
        # The single-loop chat agent streams the finish round's answer as
        # ``content`` with ``agent_loop_round``; it must reach the persisted
        # answer (regression: was dropped, so the bubble cleared on reload).
        event = StreamEvent(
            type=StreamEventType.CONTENT,
            content="the answer",
            metadata={"call_id": "c1", "call_kind": "agent_loop_round"},
        )
        assert _should_capture_assistant_content(event) is True

    def test_non_content_event_not_captured(self) -> None:
        event = StreamEvent(type=StreamEventType.THINKING, content="hmm")
        assert _should_capture_assistant_content(event) is False

    def test_tool_call_not_captured(self) -> None:
        event = StreamEvent(type=StreamEventType.TOOL_CALL, content="web_search")
        assert _should_capture_assistant_content(event) is False


class TestNarrationMarkerCallId:
    def test_narration_marker_returns_call_id(self) -> None:
        event = StreamEvent(
            type=StreamEventType.PROGRESS,
            metadata={
                "call_id": "round-1",
                "trace_kind": "call_status",
                "call_state": "complete",
                "call_role": "narration",
            },
        )
        assert _narration_marker_call_id(event) == "round-1"

    def test_finish_marker_is_not_narration(self) -> None:
        event = StreamEvent(
            type=StreamEventType.PROGRESS,
            metadata={
                "call_id": "round-2",
                "trace_kind": "call_status",
                "call_state": "complete",
                "call_role": "finish",
            },
        )
        assert _narration_marker_call_id(event) is None

    def test_running_status_is_not_narration(self) -> None:
        event = StreamEvent(
            type=StreamEventType.PROGRESS,
            metadata={
                "call_id": "round-1",
                "trace_kind": "call_status",
                "call_state": "running",
                "call_role": "narration",
            },
        )
        assert _narration_marker_call_id(event) is None


class TestArtifactAttachments:
    def _sources_event(self, sources: list[dict]) -> StreamEvent:
        return StreamEvent(type=StreamEventType.SOURCES, metadata={"sources": sources})

    def test_artifact_source_becomes_generated_attachment(self) -> None:
        event = self._sources_event(
            [
                {
                    "type": "artifact",
                    "filename": "report.pdf",
                    "url": "/api/outputs/workspace/chat/chat/t1/exec/report.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 2048,
                }
            ]
        )
        atts = _artifact_attachments(event)
        assert len(atts) == 1
        a = atts[0]
        assert a["type"] == "document"
        assert a["filename"] == "report.pdf"
        assert a["url"].endswith("report.pdf")
        assert a["mime_type"] == "application/pdf"
        assert a["generated"] is True

    def test_image_artifact_typed_as_image(self) -> None:
        event = self._sources_event(
            [
                {
                    "type": "artifact",
                    "filename": "chart.png",
                    "url": "/api/outputs/x/chart.png",
                    "mime_type": "image/png",
                }
            ]
        )
        assert _artifact_attachments(event)[0]["type"] == "image"

    def test_non_artifact_sources_ignored(self) -> None:
        event = self._sources_event([{"type": "rag", "query": "q", "kb_name": "kb"}])
        assert _artifact_attachments(event) == []

    def test_tool_result_artifacts_extracted(self) -> None:
        # tool_result events carry artifacts the moment exec finishes — the
        # durable source for cancelled turns (the aggregate SOURCES event
        # only fires when the loop completes).
        event = StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            content="Exit code: 0",
            metadata={
                "tool_metadata": {
                    "exit_code": 0,
                    "artifacts": [
                        {
                            "filename": "notes.pdf",
                            "url": "/api/outputs/workspace/chat/chat/t2/exec/notes.pdf",
                            "mime_type": "application/pdf",
                            "size_bytes": 1024,
                        }
                    ],
                }
            },
        )
        atts = _artifact_attachments(event)
        assert len(atts) == 1
        assert atts[0]["filename"] == "notes.pdf"
        assert atts[0]["generated"] is True

    def test_tool_result_without_artifacts_ignored(self) -> None:
        event = StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            content="rag result",
            metadata={"tool_metadata": {"kb_name": "kb"}},
        )
        assert _artifact_attachments(event) == []

    def test_non_sources_event_ignored(self) -> None:
        event = StreamEvent(type=StreamEventType.CONTENT, content="hello")
        assert _artifact_attachments(event) == []

    def test_artifact_without_url_skipped(self) -> None:
        event = self._sources_event([{"type": "artifact", "filename": "x.pdf"}])
        assert _artifact_attachments(event) == []


# ---------------------------------------------------------------------------
# _clip_text
# ---------------------------------------------------------------------------


class TestClipText:
    def test_short_text_unchanged(self) -> None:
        assert _clip_text("hello", limit=100) == "hello"

    def test_long_text_truncated(self) -> None:
        text = "x" * 5000
        result = _clip_text(text, limit=100)
        assert len(result) < 200
        assert "[truncated]" in result

    def test_empty_string(self) -> None:
        assert _clip_text("") == ""

    def test_none_becomes_empty(self) -> None:
        assert _clip_text(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _extract_memory_references
# ---------------------------------------------------------------------------


class TestExtractMemoryReferences:
    def test_extracts_valid_memory_files_in_order(self) -> None:
        payload = {"memory_references": ["profile", "summary"]}

        assert _extract_memory_references(payload) == ["profile", "summary"]

    def test_filters_unknown_and_duplicate_memory_files(self) -> None:
        payload = {"memory_references": ["summary", "unknown", "summary", "profile"]}

        assert _extract_memory_references(payload) == ["summary", "profile"]

    def test_non_list_memory_references_are_ignored(self) -> None:
        assert _extract_memory_references({"memory_references": "summary"}) == []


# ---------------------------------------------------------------------------
# _extract_followup_question_context
# ---------------------------------------------------------------------------


class TestExtractFollowupQuestionContext:
    def test_none_config(self) -> None:
        assert _extract_followup_question_context(None) is None

    def test_missing_key(self) -> None:
        assert _extract_followup_question_context({}) is None

    def test_non_dict_value(self) -> None:
        assert _extract_followup_question_context({"followup_question_context": "string"}) is None

    def test_missing_question(self) -> None:
        assert (
            _extract_followup_question_context({"followup_question_context": {"question_id": "q1"}})
            is None
        )

    def test_valid_context_extracted(self) -> None:
        config = {
            "followup_question_context": {
                "question": "What is AI?",
                "question_id": "q1",
                "question_type": "mcq",
                "options": {"A": "Choice A", "B": "Choice B"},
                "correct_answer": "A",
                "explanation": "AI is...",
                "difficulty": "easy",
                "user_answer": "B",
                "is_correct": False,
            }
        }
        result = _extract_followup_question_context(config)
        assert result is not None
        assert result["question"] == "What is AI?"
        assert result["question_id"] == "q1"
        assert result["options"]["A"] == "Choice A"
        assert result["is_correct"] is False
        assert "followup_question_context" not in config  # popped

    def test_options_normalized(self) -> None:
        config = {
            "followup_question_context": {
                "question": "Q",
                "options": {"a": "lower", "B": "upper", "c": ""},
            }
        }
        result = _extract_followup_question_context(config)
        assert "A" in result["options"]
        assert "B" in result["options"]
        assert "C" not in result["options"]  # empty value excluded


# ---------------------------------------------------------------------------
# _extract_persist_user_message
# ---------------------------------------------------------------------------


class TestExtractPersistUserMessage:
    def test_default_is_true(self) -> None:
        assert _extract_persist_user_message({}) is True

    def test_none_config_is_true(self) -> None:
        assert _extract_persist_user_message(None) is True

    def test_false_bool(self) -> None:
        config = {"_persist_user_message": False}
        assert _extract_persist_user_message(config) is False
        assert "_persist_user_message" not in config  # popped

    def test_false_string(self) -> None:
        assert _extract_persist_user_message({"_persist_user_message": "false"}) is False

    def test_zero_string(self) -> None:
        assert _extract_persist_user_message({"_persist_user_message": "0"}) is False

    def test_no_string(self) -> None:
        assert _extract_persist_user_message({"_persist_user_message": "no"}) is False

    def test_true_string(self) -> None:
        assert _extract_persist_user_message({"_persist_user_message": "true"}) is True


# ---------------------------------------------------------------------------
# _format_followup_question_context
# ---------------------------------------------------------------------------


class TestFormatFollowupQuestionContext:
    def _base_context(self) -> dict:
        return {
            "question_id": "q1",
            "parent_quiz_session_id": "qs1",
            "question_type": "mcq",
            "difficulty": "medium",
            "concentration": "math",
            "question": "What is 2+2?",
            "options": {"A": "3", "B": "4"},
            "user_answer": "A",
            "is_correct": False,
            "correct_answer": "B",
            "explanation": "2+2=4",
            "knowledge_context": "",
        }

    def test_english_format(self) -> None:
        text = _format_followup_question_context(self._base_context(), language="en")
        assert "You are handling follow-up questions" in text
        assert "What is 2+2?" in text
        assert "A. 3" in text
        assert "B. 4" in text
        assert "incorrect" in text

    def test_chinese_format(self) -> None:
        text = _format_followup_question_context(self._base_context(), language="zh")
        assert "你正在处理一道测验题的后续追问" in text
        assert "What is 2+2?" in text

    def test_correct_answer_shows_correct(self) -> None:
        ctx = self._base_context()
        ctx["is_correct"] = True
        text = _format_followup_question_context(ctx, language="en")
        assert "correct" in text.lower()

    def test_unknown_correctness(self) -> None:
        ctx = self._base_context()
        ctx["is_correct"] = None
        text = _format_followup_question_context(ctx, language="en")
        assert "unknown" in text.lower()

    def test_knowledge_context_included(self) -> None:
        ctx = self._base_context()
        ctx["knowledge_context"] = "Some KB knowledge"
        text = _format_followup_question_context(ctx, language="en")
        assert "Some KB knowledge" in text

    def test_no_options(self) -> None:
        ctx = self._base_context()
        ctx["options"] = {}
        text = _format_followup_question_context(ctx, language="en")
        assert "Options:" not in text
