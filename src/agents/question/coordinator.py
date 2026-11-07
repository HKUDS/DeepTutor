#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Refactored Question Coordinator

Two-loop architecture:
1) Idea loop (IdeaAgent <-> Evaluator) for topic-driven templates
2) Generation loop (Generator <-> Validator) for final Q-A pairs

All intermediate artifacts are saved to a per-batch directory.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.agents.question.agents.evaluator import Evaluator
from src.agents.question.agents.generator import Generator
from src.agents.question.agents.idea_agent import IdeaAgent
from src.agents.question.agents.validator import Validator
from src.agents.question.models import QAPair, QuestionTemplate
from src.logging import Logger, get_logger
from src.services.config import load_config_with_main
from src.tools.question.pdf_parser import parse_pdf_with_mineru
from src.tools.question.question_extractor import extract_questions_from_paper


class AgentCoordinator:
    """
    Orchestrates both input paths:
    - generate_from_topic: user_topic + preference
    - generate_from_exam: exam paper parse/extract -> templates

    All intermediate files (templates, traces, per-question results) are
    persisted to self._batch_dir for debugging and reproducibility.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        kb_name: str | None = None,
        output_dir: str | None = None,
        language: str = "en",
        tool_flags_override: dict[str, bool] | None = None,
        enable_idea_rag: bool = True,
    ) -> None:
        self.kb_name = kb_name
        self.output_dir = output_dir
        self.language = language
        self._api_key = api_key
        self._base_url = base_url
        self._api_version = api_version
        self._ws_callback: Callable | None = None
        self._batch_dir: Path | None = None
        self.enable_idea_rag = enable_idea_rag

        self.config = load_config_with_main("question_config.yaml", project_root)

        log_dir = self.config.get("paths", {}).get("user_log_dir") or self.config.get(
            "logging", {}
        ).get("log_dir")
        self.logger: Logger = get_logger("QuestionCoordinator", log_dir=log_dir)

        question_cfg = self.config.get("question", {})
        self.rag_mode = question_cfg.get("rag_mode", "naive")
        self.max_parallel_questions = question_cfg.get("max_parallel_questions", 1)
        self.idea_cfg = question_cfg.get("idea_loop", {})
        self.generation_cfg = question_cfg.get("generation", {})
        default_tool_flags = self.generation_cfg.get(
            "tools",
            {"web_search": True, "rag_tool": True, "write_code": True},
        )
        self.tool_flags = (
            tool_flags_override
            if isinstance(tool_flags_override, dict)
            else default_tool_flags
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_ws_callback(self, callback: Callable) -> None:
        self._ws_callback = callback

    def get_batch_dir(self) -> Path | None:
        """Return the current batch directory (available after generation starts)."""
        return self._batch_dir

    # ------------------------------------------------------------------
    # Batch directory & artifact persistence
    # ------------------------------------------------------------------

    def _init_batch_dir(self) -> Path | None:
        """Create a timestamped batch directory for this generation run."""
        if not self.output_dir:
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = Path(self.output_dir) / f"batch_{ts}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        self._batch_dir = batch_dir
        return batch_dir

    def _save_artifact(self, filename: str, data: Any) -> None:
        """Save an intermediate artifact to the batch directory."""
        if not self._batch_dir:
            return
        try:
            filepath = self._batch_dir / filename
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            self.logger.debug(f"Failed to save artifact {filename}: {exc}")

    # ------------------------------------------------------------------
    # WebSocket helpers
    # ------------------------------------------------------------------

    async def _send_ws_update(self, update_type: str, data: dict[str, Any]) -> None:
        if self._ws_callback:
            try:
                await self._ws_callback({"type": update_type, **data})
            except Exception as exc:
                self.logger.debug(f"WS update failed: {exc}")

    # ------------------------------------------------------------------
    # Agent factories
    # ------------------------------------------------------------------

    def _create_idea_agent(self) -> IdeaAgent:
        return IdeaAgent(
            kb_name=self.kb_name,
            rag_mode=self.rag_mode,
            enable_rag=self.enable_idea_rag,
            language=self.language,
            api_key=self._api_key,
            base_url=self._base_url,
            api_version=self._api_version,
        )

    def _create_evaluator(self) -> Evaluator:
        return Evaluator(
            language=self.language,
            api_key=self._api_key,
            base_url=self._base_url,
            api_version=self._api_version,
        )

    def _create_generator(self) -> Generator:
        return Generator(
            kb_name=self.kb_name,
            rag_mode=self.rag_mode,
            language=self.language,
            tool_flags=self.tool_flags,
            api_key=self._api_key,
            base_url=self._base_url,
            api_version=self._api_version,
        )

    def _create_validator(self) -> Validator:
        return Validator(
            language=self.language,
            tool_flags=self.tool_flags,
            api_key=self._api_key,
            base_url=self._base_url,
            api_version=self._api_version,
        )

    # ------------------------------------------------------------------
    # Path 1: Topic -> Idea Loop -> Generation Loop
    # ------------------------------------------------------------------

    async def generate_from_topic(
        self,
        user_topic: str,
        preference: str,
        num_questions: int,
        difficulty: str = "",
        question_type: str = "",
    ) -> dict[str, Any]:
        self._init_batch_dir()

        await self._send_ws_update(
            "progress",
            {"stage": "idea_loop", "status": "running", "current_round": 0, "max_rounds": 0},
        )

        templates, idea_trace = await self._idea_loop(
            user_topic=user_topic,
            preference=preference,
            num_questions=num_questions,
            difficulty=difficulty,
            question_type=question_type,
        )

        # Save intermediate artifacts
        self._save_artifact("templates.json", [t.__dict__ for t in templates])
        self._save_artifact("idea_trace.json", idea_trace)

        await self._send_ws_update(
            "templates_ready",
            {
                "stage": "templates_ready",
                "templates": [t.__dict__ for t in templates],
                "count": len(templates),
            },
        )

        qa_pairs = await self._generation_loop(
            templates=templates,
            user_topic=user_topic,
            preference=preference,
        )

        summary = self._build_summary(
            source="topic",
            requested=num_questions,
            templates=templates,
            qa_pairs=qa_pairs,
            trace=idea_trace,
        )
        self._save_artifact("summary.json", summary)

        await self._publish_question_complete_event(
            mode="topic",
            user_topic=user_topic,
            templates=templates,
            qa_pairs=qa_pairs,
        )
        return summary

    # ------------------------------------------------------------------
    # Path 2: Exam Paper -> Parse -> Templates -> Generation Loop
    # ------------------------------------------------------------------

    async def generate_from_exam(
        self,
        exam_paper_path: str,
        max_questions: int,
        paper_mode: str = "upload",
    ) -> dict[str, Any]:
        self._init_batch_dir()

        templates, parse_trace = await self._parse_exam_to_templates(
            exam_paper_path=exam_paper_path,
            max_questions=max_questions,
            paper_mode=paper_mode,
        )

        # Save intermediate artifacts
        self._save_artifact("templates.json", [t.__dict__ for t in templates])
        self._save_artifact("parse_trace.json", parse_trace)

        await self._send_ws_update(
            "templates_ready",
            {
                "stage": "templates_ready",
                "templates": [t.__dict__ for t in templates],
                "count": len(templates),
            },
        )

        qa_pairs = await self._generation_loop(
            templates=templates,
            user_topic="",
            preference="",
        )

        summary = self._build_summary(
            source="exam",
            requested=max_questions,
            templates=templates,
            qa_pairs=qa_pairs,
            trace=parse_trace,
        )
        self._save_artifact("summary.json", summary)

        await self._publish_question_complete_event(
            mode="exam",
            user_topic="",
            templates=templates,
            qa_pairs=qa_pairs,
        )
        return summary

    # ------------------------------------------------------------------
    # Idea Loop
    # ------------------------------------------------------------------

    async def _idea_loop(
        self,
        user_topic: str,
        preference: str,
        num_questions: int,
        difficulty: str = "",
        question_type: str = "",
    ) -> tuple[list[QuestionTemplate], dict[str, Any]]:
        max_rounds = int(self.idea_cfg.get("max_rounds", 3))
        ideas_per_round = int(self.idea_cfg.get("ideas_per_round", max(3, num_questions)))

        idea_agent = self._create_idea_agent()
        evaluator = self._create_evaluator()
        idea_memory_context = await self._get_idea_memory_context(user_topic)
        evaluator_memory_context = await self._get_evaluator_memory_context(user_topic)
        idea_preference = self._merge_preference(preference, idea_memory_context)
        evaluator_preference = self._merge_preference(idea_preference, evaluator_memory_context)

        feedback = ""
        trace_rounds: list[dict[str, Any]] = []
        selected_templates: list[QuestionTemplate] = []
        normalized_difficulty = difficulty.strip().lower()
        normalized_question_type = question_type.strip().lower()
        target_difficulty = (
            normalized_difficulty
            if normalized_difficulty and normalized_difficulty != "auto"
            else ""
        )
        target_question_type = (
            normalized_question_type
            if normalized_question_type and normalized_question_type != "auto"
            else ""
        )

        for round_idx in range(1, max_rounds + 1):
            await self._send_ws_update(
                "progress",
                {
                    "stage": "idea_loop",
                    "status": "running",
                    "current_round": round_idx,
                    "max_rounds": max_rounds,
                },
            )

            idea_result = await idea_agent.process(
                user_topic=user_topic,
                preference=idea_preference,
                evaluator_feedback=feedback,
                num_ideas=ideas_per_round,
                target_difficulty=target_difficulty,
                target_question_type=target_question_type,
            )
            ideas = idea_result.get("ideas", [])

            eval_result = await evaluator.process(
                user_topic=user_topic,
                preference=evaluator_preference,
                ideas=ideas,
                top_k=num_questions,
                current_round=round_idx,
                max_rounds=max_rounds,
                target_difficulty=target_difficulty,
                target_question_type=target_question_type,
            )

            feedback = eval_result.get("feedback", "")
            selected_templates = eval_result.get("templates", [])
            continue_loop = eval_result.get("continue_loop", False)

            round_trace = {
                "round": round_idx,
                "ideas": ideas,
                "selected_ideas": eval_result.get("selected_ideas", []),
                "feedback": feedback,
                "continue_loop": continue_loop,
                "queries": idea_result.get("queries", []),
            }
            trace_rounds.append(round_trace)

            # Save per-round trace
            self._save_artifact(f"idea_round_{round_idx}.json", round_trace)

            await self._send_ws_update(
                "idea_round",
                {
                    "round": round_idx,
                    "ideas": ideas,
                    "selected_ideas": eval_result.get("selected_ideas", []),
                    "continue_loop": continue_loop,
                    "feedback": feedback,
                },
            )

            if not continue_loop:
                break

        if not selected_templates:
            selected_templates = [
                QuestionTemplate(
                    question_id=f"q_{i+1}",
                    concentration=f"{user_topic} - aspect {i+1}",
                    question_type="written",
                    difficulty="medium",
                    source="custom",
                )
                for i in range(num_questions)
            ]

        return selected_templates[:num_questions], {
            "rounds": trace_rounds,
            "max_rounds": max_rounds,
        }

    # ------------------------------------------------------------------
    # Generation Loop (with exception safety)
    # ------------------------------------------------------------------

    async def _generation_loop(
        self,
        templates: list[QuestionTemplate],
        user_topic: str,
        preference: str,
    ) -> list[dict[str, Any]]:
        max_retries = int(self.generation_cfg.get("max_retries", 2))
        generator = self._create_generator()
        validator = self._create_validator()

        results: list[dict[str, Any]] = []
        total = len(templates)

        for idx, template in enumerate(templates, 1):
            await self._send_ws_update(
                "progress",
                {
                    "stage": "generating",
                    "current": idx - 1,
                    "total": total,
                    "question_id": template.question_id,
                },
            )

            feedback = ""
            attempts: list[dict[str, Any]] = []
            final_qa: QAPair | None = None
            final_validation: dict[str, Any] = {}

            for attempt in range(1, max_retries + 2):
                await self._send_ws_update(
                    "question_update",
                    {
                        "question_id": template.question_id,
                        "status": "generating",
                        "attempt": attempt,
                        "max_attempts": max_retries + 1,
                    },
                )

                try:
                    template_preference = preference
                    generator_memory_context = await self._get_generator_memory_context(
                        template.concentration
                    )
                    template_preference = self._merge_preference(
                        template_preference,
                        generator_memory_context,
                    )
                    qa_pair = await generator.process(
                        template=template,
                        user_topic=user_topic,
                        preference=template_preference,
                        validator_feedback=feedback,
                    )
                    validation = await validator.process(
                        template=template, qa_pair=qa_pair
                    )

                    attempts.append(
                        {
                            "attempt": attempt,
                            "qa_pair": qa_pair.__dict__,
                            "validation": validation,
                        }
                    )

                    await self._send_ws_update(
                        "validating",
                        {
                            "question_id": template.question_id,
                            "attempt": attempt,
                            "validation": validation,
                        },
                    )

                    if validation.get("approved"):
                        final_qa = qa_pair
                        final_validation = validation
                        break
                    feedback = validation.get("feedback", "")

                except Exception as exc:
                    self.logger.warning(
                        f"Attempt {attempt} failed for {template.question_id}: {exc}"
                    )
                    attempts.append(
                        {
                            "attempt": attempt,
                            "error": str(exc),
                        }
                    )
                    feedback = f"Previous attempt raised an error: {exc}"

            # Reconstruct final_qa from last successful attempt if not approved
            if final_qa is None:
                for att in reversed(attempts):
                    if "qa_pair" in att:
                        try:
                            final_qa = QAPair(
                                **{
                                    k: v
                                    for k, v in att["qa_pair"].items()
                                    if k
                                    in {
                                        "question_id",
                                        "question",
                                        "correct_answer",
                                        "explanation",
                                        "question_type",
                                        "options",
                                        "concentration",
                                        "difficulty",
                                        "validation",
                                        "metadata",
                                    }
                                }
                            )
                            final_validation = att.get("validation", {})
                        except Exception:
                            pass
                        break

            # If ALL attempts failed with exceptions, create a placeholder
            if final_qa is None:
                final_qa = QAPair(
                    question_id=template.question_id,
                    question=f"[Generation failed] {template.concentration}",
                    correct_answer="N/A",
                    explanation="All generation attempts failed.",
                    question_type=template.question_type,
                    concentration=template.concentration,
                    difficulty=template.difficulty,
                )
                final_validation = {
                    "decision": "reject",
                    "approved": False,
                    "feedback": "All generation attempts failed with errors.",
                    "issues": [str(a.get("error", "unknown")) for a in attempts if "error" in a],
                }

            final_qa.validation = final_validation
            result = {
                "template": template.__dict__,
                "qa_pair": final_qa.__dict__,
                "attempts": attempts,
                "success": bool(final_validation.get("approved")),
            }
            results.append(result)

            # Save per-question artifact
            self._save_artifact(
                f"{template.question_id}_result.json", result
            )

            await self._send_ws_update(
                "result",
                {
                    "question_id": template.question_id,
                    "index": idx - 1,
                    "question": final_qa.__dict__,
                    "validation": final_validation,
                    "attempts": len(attempts),
                },
            )

            await self._send_ws_update(
                "progress",
                {
                    "stage": "generating",
                    "current": idx,
                    "total": total,
                    "question_id": template.question_id,
                },
            )

        await self._send_ws_update(
            "progress",
            {"stage": "complete", "completed": len(results), "total": total},
        )
        return results

    # ------------------------------------------------------------------
    # Exam paper parsing
    # ------------------------------------------------------------------

    async def _parse_exam_to_templates(
        self,
        exam_paper_path: str,
        max_questions: int,
        paper_mode: str,
    ) -> tuple[list[QuestionTemplate], dict[str, Any]]:
        await self._send_ws_update("progress", {"stage": "parsing", "status": "running"})

        paper_path = Path(exam_paper_path)
        output_base = (
            Path(self.output_dir)
            if self.output_dir
            else (project_root / "data" / "user" / "question" / "mimic_papers")
        )
        output_base.mkdir(parents=True, exist_ok=True)

        working_dir: Path
        if paper_mode == "parsed":
            working_dir = paper_path
        else:
            parse_success = parse_pdf_with_mineru(str(paper_path), str(output_base))
            if not parse_success:
                raise RuntimeError("Failed to parse exam paper with MinerU")
            subdirs = sorted(
                [d for d in output_base.iterdir() if d.is_dir()],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            if not subdirs:
                raise RuntimeError("No parsed exam directory found after MinerU parsing")
            working_dir = subdirs[0]

        await self._send_ws_update(
            "progress",
            {"stage": "extracting", "status": "running", "paper_dir": str(working_dir)},
        )

        json_files = list(working_dir.glob("*_questions.json"))
        if not json_files:
            extract_success = extract_questions_from_paper(
                str(working_dir), output_dir=None
            )
            if not extract_success:
                raise RuntimeError("Failed to extract questions from parsed exam")
            json_files = list(working_dir.glob("*_questions.json"))
        if not json_files:
            raise RuntimeError("Question extraction output not found")

        with open(json_files[0], encoding="utf-8") as f:
            payload = json.load(f)
        questions = payload.get("questions", [])
        if max_questions > 0:
            questions = questions[:max_questions]

        templates: list[QuestionTemplate] = []
        for i, item in enumerate(questions, 1):
            if not isinstance(item, dict):
                continue
            q_text = str(item.get("question_text", "")).strip()
            if not q_text:
                continue
            templates.append(
                QuestionTemplate(
                    question_id=f"q_{i}",
                    concentration=q_text[:240],
                    question_type=str(item.get("question_type", "written")).lower(),
                    difficulty="medium",
                    source="mimic",
                    reference_question=q_text,
                    reference_answer=str(item.get("answer", "")).strip() or None,
                    metadata={
                        "question_number": item.get("question_number", str(i)),
                        "images": item.get("images", []),
                    },
                )
            )

        await self._send_ws_update(
            "progress",
            {"stage": "extracting", "status": "complete", "templates": len(templates)},
        )
        return templates, {
            "paper_dir": str(working_dir),
            "question_file": str(json_files[0]),
            "template_count": len(templates),
        }

    # ------------------------------------------------------------------
    # Summary & Events
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        source: str,
        requested: int,
        templates: list[QuestionTemplate],
        qa_pairs: list[dict[str, Any]],
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        completed = sum(1 for item in qa_pairs if item.get("success"))
        failed = len(qa_pairs) - completed
        return {
            "success": failed == 0 and completed > 0,
            "source": source,
            "requested": requested,
            "template_count": len(templates),
            "completed": completed,
            "failed": failed,
            "templates": [t.__dict__ for t in templates],
            "results": qa_pairs,
            "trace": trace,
            "batch_dir": str(self._batch_dir) if self._batch_dir else None,
        }

    async def _publish_question_complete_event(
        self,
        mode: str,
        user_topic: str,
        templates: list[QuestionTemplate],
        qa_pairs: list[dict[str, Any]],
    ) -> None:
        try:
            from src.core.event_bus import Event, EventType, get_event_bus

            question_summaries = [
                {
                    "type": item.get("qa_pair", {}).get("question_type", "unknown"),
                    "question": item.get("qa_pair", {}).get("question", "")[:200],
                }
                for item in qa_pairs[:3]
            ]

            # Collect actually used tools from results
            tools_used = set()
            for item in qa_pairs:
                plan = item.get("qa_pair", {}).get("metadata", {}).get("tool_plan", {})
                if plan.get("use_rag"):
                    tools_used.add("rag_tool")
                if plan.get("use_web"):
                    tools_used.add("web_search")
                if plan.get("use_code"):
                    tools_used.add("write_code")

            event = Event(
                type=EventType.QUESTION_COMPLETE,
                task_id=f"question_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                user_input=json.dumps(
                    {
                        "topic": user_topic,
                        "mode": mode,
                        "template_count": len(templates),
                    },
                    ensure_ascii=False,
                ),
                agent_output=json.dumps(question_summaries, ensure_ascii=False),
                tools_used=list(tools_used),
                success=any(item.get("success") for item in qa_pairs),
                metadata={
                    "mode": mode,
                    "num_questions": len(qa_pairs),
                    "batch_dir": str(self._batch_dir) if self._batch_dir else "",
                    "user_topic": user_topic,
                },
            )
            await get_event_bus().publish(event)
        except Exception as exc:
            self.logger.debug(f"Failed to publish QUESTION_COMPLETE event: {exc}")

    async def _get_idea_memory_context(self, topic: str) -> str:
        from src.personalization.memory_reader import get_memory_reader_instance

        reader = get_memory_reader_instance()
        if not reader:
            return ""
        try:
            return await reader.get_idea_context(topic)
        except Exception:
            return ""

    async def _get_evaluator_memory_context(self, topic: str) -> str:
        from src.personalization.memory_reader import get_memory_reader_instance

        reader = get_memory_reader_instance()
        if not reader:
            return ""
        try:
            return await reader.get_evaluator_context(topic)
        except Exception:
            return ""

    async def _get_generator_memory_context(self, concentration: str) -> str:
        from src.personalization.memory_reader import get_memory_reader_instance

        reader = get_memory_reader_instance()
        if not reader:
            return ""
        try:
            return await reader.get_generator_context(concentration)
        except Exception:
            return ""

    @staticmethod
    def _merge_preference(user_pref: str, memory_context: str) -> str:
        pref = (user_pref or "").strip()
        mem = (memory_context or "").strip()
        if pref and mem:
            return f"{pref}\n\n[Memory Context]\n{mem}"
        if mem:
            return f"[Memory Context]\n{mem}"
        return pref
