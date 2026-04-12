"""Goal mode orchestration."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import io
import re
from pathlib import Path
from typing import Any

from deeptutor.agents.goal.exercise_adapter import ExerciseAdapter
from deeptutor.agents.goal.exam_miner import ExamMiner
from deeptutor.agents.goal.extractor import KnowledgeExtractor
from deeptutor.agents.goal.graph_builder import GraphBuilder
from deeptutor.agents.goal.models import (
    DayPlanDetail,
    DayPlanTimeBlock,
    Feedback,
    GoalArtifacts,
    GoalConfig,
    GoalSession,
    Plan,
    PlanArtifacts,
    PlanDay,
    SessionStatus,
    Task,
    TaskKind,
    TaskStatus,
)
from deeptutor.agents.goal.planner import Planner
from deeptutor.agents.goal.scheduler import Scheduler
from deeptutor.agents.goal.storage import GoalStorage
from deeptutor.agents.goal.utils import build_session_id, future_dates
from deeptutor.agents.goal.weight_model import WeightModel
from deeptutor.agents.guide.agents.interactive_agent import InteractiveAgent
from deeptutor.services.config import parse_language
from deeptutor.services.llm import complete as llm_complete
from deeptutor.services.llm import get_llm_config


class GoalOrchestrator:
    """Coordinate session creation, planning, feedback, and practice generation."""

    def __init__(
        self,
        storage: GoalStorage | None = None,
        extractor: KnowledgeExtractor | None = None,
        graph_builder: GraphBuilder | None = None,
        weight_model: WeightModel | None = None,
        planner: Planner | None = None,
        scheduler: Scheduler | None = None,
        exercise_adapter: ExerciseAdapter | None = None,
        exam_miner: ExamMiner | None = None,
    ):
        self.storage = storage or GoalStorage()
        self.extractor = extractor or KnowledgeExtractor()
        self.graph_builder = graph_builder or GraphBuilder()
        self.weight_model = weight_model or WeightModel()
        self.planner = planner or Planner()
        self.scheduler = scheduler or Scheduler()
        self.exercise_adapter = exercise_adapter or ExerciseAdapter()
        self.exam_miner = exam_miner or ExamMiner()
        self._feedback_store: dict[str, list[Feedback]] = defaultdict(list)

    async def create_session(self, kb_name: str, goal_config: GoalConfig) -> GoalSession:
        sequence = 1
        while (self.storage.base_dir / build_session_id(sequence=sequence) / "session.json").exists():
            sequence += 1
        session_id = build_session_id(sequence=sequence)
        session = GoalSession(
            session_id=session_id,
            kb_name=kb_name,
            goal_config=goal_config.model_copy(update={"kb_name": kb_name}),
            artifacts=GoalArtifacts(root_dir=f"data/user/goal/{session_id}"),
        )
        self.storage.save_session(session)
        self.storage.append_event(
            session_id,
            {"ts": datetime.now().isoformat(), "type": "stage", "stage": "created", "progress": 1.0},
        )
        return session

    async def run_plan(self, session_id: str) -> Plan:
        session = self.storage.load_session(session_id)
        self.storage.append_event(session_id, self._stage_event("extract", 0.1))
        extraction_scope = session.goal_config.scope.model_dump(mode="json")
        extraction_scope["goal_statement"] = session.goal_config.goal_statement
        drafts = await self.extractor.extract(session.kb_name, extraction_scope)

        self.storage.append_event(session_id, self._stage_event("graph", 0.4))
        nodes, edges = self.graph_builder.build(drafts)
        scored_nodes = self.weight_model.score(nodes, edges, session.goal_config)

        self.storage.append_event(session_id, self._stage_event("plan", 0.7))
        tasks = self.planner.plan(scored_nodes, edges, session.goal_config)
        days = self._build_days(session.goal_config.daily_minutes, session.goal_config.remaining_days, tasks)

        plan = Plan(
            plan_id=f"plan_{session.plan_version + 1:03d}",
            session_id=session.session_id,
            kb_name=session.kb_name,
            plan_version=session.plan_version + 1,
            knowledge_nodes=scored_nodes,
            knowledge_edges=edges,
            days=days,
            tasks=tasks,
            artifacts=PlanArtifacts(root_dir=session.artifacts.root_dir),
        )
        self.storage.save_graph(session_id, scored_nodes, edges)
        self.storage.save_plan(plan)

        session.plan_id = plan.plan_id
        session.plan_version = plan.plan_version
        session.status = SessionStatus.READY
        session.artifacts.plan_json = plan.artifacts.plan_json
        session.artifacts.graph_json = plan.artifacts.graph_json
        self.storage.save_session(session)
        self.storage.append_event(session_id, self._stage_event("complete", 1.0))
        return plan

    async def submit_feedback(self, session_id: str, feedback: Feedback) -> dict:
        self._feedback_store[session_id].append(feedback)
        try:
            plan = self.storage.load_plan(session_id)
            for task in plan.tasks:
                if task.task_id != feedback.task_id:
                    continue
                if feedback.completion.value == "done":
                    task.status = TaskStatus.DONE
                elif feedback.completion.value == "skipped":
                    task.status = TaskStatus.SKIPPED
                else:
                    task.status = TaskStatus.PENDING
                break
            self.storage.save_plan(plan)
        except FileNotFoundError:
            # Feedback can still be accepted before any plan is generated.
            pass
        self.storage.append_event(
            session_id,
            {"ts": datetime.now().isoformat(), "type": "feedback", "task_id": feedback.task_id},
        )
        return {"accepted": True, "next_action": "none"}

    async def replan(self, session_id: str, reason: str | None = None) -> Plan:
        plan = self.storage.load_plan(session_id)
        feedback_batch = self._feedback_store.get(session_id, [])
        new_plan, diff = self.scheduler.replan(plan, feedback_batch)
        self.storage.save_plan(new_plan)

        session = self.storage.load_session(session_id)
        session.plan_version = new_plan.plan_version
        session.metrics.replan_count += 1
        self.storage.save_session(session)
        self.storage.append_event(
            session_id,
            {"ts": datetime.now().isoformat(), "type": "replan", "reason": reason, "diff": diff},
        )
        return new_plan

    async def generate_practice(self, session_id: str, task_id: str, count: int = 3) -> dict:
        plan = self.storage.load_plan(session_id)
        task = next((item for item in plan.tasks if item.task_id == task_id), None)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if task.practice_spec is not None:
            task.practice_spec.count = count
        practice_dir = self.storage.get_session_dir(session_id) / "practice"
        return await self.exercise_adapter.generate_for_task(task, plan.kb_name, practice_dir)

    async def analyze_exam_materials(
        self,
        session_id: str,
        *,
        pasted_text: str = "",
        uploads: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        session = self.storage.load_session(session_id)
        uploads = uploads or []
        file_texts: list[dict[str, str]] = []
        image_files: list[dict[str, Any]] = []

        for item in uploads:
            name = str(item.get("name", "upload")).strip() or "upload"
            content_type = str(item.get("content_type", "") or "").lower()
            data = item.get("data")
            if not isinstance(data, (bytes, bytearray)):
                continue
            payload = bytes(data)
            if content_type.startswith("image/"):
                image_files.append({"name": name, "content_type": content_type, "data": payload})
                continue
            extracted = self._extract_text_from_upload(name, content_type, payload)
            if extracted:
                file_texts.append({"source": name, "text": extracted})

        analysis = await self.exam_miner.analyze(
            pasted_text=pasted_text,
            file_texts=file_texts,
            image_files=image_files,
            language=parse_language(session.goal_config.preferences.language),
        )

        session_dir = self.storage.get_session_dir(session_id)
        artifact_dir = session_dir / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "exam_analysis_latest.json"
        artifact_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "session_id": session_id,
            "analysis": analysis,
            "artifact_path": str(artifact_path),
        }

    async def generate_day_interactive_page(
        self,
        session_id: str,
        day_index: int,
        force: bool = False,
    ) -> dict:
        detail = self.get_day_plan_detail(session_id, day_index)
        plan = self.storage.load_plan(session_id)
        session = self.storage.load_session(session_id)
        session_dir = self.storage.get_session_dir(session_id)
        target_path = session_dir / "artifacts" / f"day_{day_index:02d}_interactive.html"

        if target_path.exists() and not force:
            return {
                "session_id": session_id,
                "day_index": day_index,
                "path": str(target_path),
                "cached": True,
                "html": target_path.read_text(encoding="utf-8"),
            }

        topics = [
            task.title.replace("Learn ", "").replace("Practice ", "").replace("Review ", "").replace("学习 ", "").replace("练习 ", "").replace("复习 ", "")
            for task in plan.tasks
            if task.day_index == day_index
        ][:4]
        title = f"Day {day_index} Interactive Lesson: {', '.join(topics) if topics else 'Review and Reinforcement'}"
        language = parse_language(session.goal_config.preferences.language)
        blueprint = await self._generate_interactive_blueprint(detail, session.goal_config, language)
        knowledge = {
            "knowledge_title": title,
            "knowledge_summary": self._build_interactive_summary(detail, session.goal_config, blueprint),
            "user_difficulty": "; ".join(detail.pitfalls[:3]) if detail.pitfalls else "Learning pacing and transfer can become imbalanced.",
            "generation_requirements": self._build_interactive_generation_requirements(detail, session.goal_config),
            "content_blueprint": self._format_interactive_blueprint(blueprint),
        }

        llm_config = get_llm_config()
        interactive_agent = InteractiveAgent(
            api_key=llm_config.api_key,
            base_url=llm_config.effective_url or llm_config.base_url or "",
            api_version=getattr(llm_config, "api_version", None),
            language=language,
            binding=getattr(llm_config, "binding", "openai"),
        )

        result = await interactive_agent.process(knowledge=knowledge)
        html = str(result.get("html") or "").strip()
        if not html:
            raise ValueError(result.get("error", "Failed to generate interactive page"))

        target_path.write_text(html, encoding="utf-8")
        return {
            "session_id": session_id,
            "day_index": day_index,
            "path": str(target_path),
            "cached": False,
            "html": html,
        }

    async def answer_day_interactive_question(
        self,
        session_id: str,
        day_index: int,
        question: str,
    ) -> dict:
        if not question.strip():
            raise ValueError("Question cannot be empty")

        detail = self.get_day_plan_detail(session_id, day_index)
        session = self.storage.load_session(session_id)
        session_dir = self.storage.get_session_dir(session_id)
        lesson_path = session_dir / "artifacts" / f"day_{day_index:02d}_interactive.html"
        lesson_text = ""
        if lesson_path.exists():
            lesson_text = self._extract_text_from_html(lesson_path.read_text(encoding="utf-8"))[:6000]

        context = self._build_interactive_summary(detail, session.goal_config)
        system_prompt = (
            "You are an exam-focused learning tutor. "
            "Prioritize knowledge structure, high-yield points, common mistakes, and fast decision methods. "
            "Keep answers concise, professional, and actionable."
        )
        user_prompt = (
            f"[Today's lesson knowledge structure]\n{context}\n\n"
            f"[Lesson excerpt]\n{lesson_text or 'No lesson excerpt available.'}\n\n"
            f"[User question]\n{question.strip()}\n\n"
            "Answer in English and end with 1-2 immediately actionable practice suggestions."
        )
        answer = await llm_complete(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.3,
            max_tokens=900,
        )
        return {
            "session_id": session_id,
            "day_index": day_index,
            "question": question.strip(),
            "answer": answer.strip(),
        }

    def get_day_plan_detail(self, session_id: str, day_index: int) -> DayPlanDetail:
        if day_index <= 0:
            raise ValueError("day_index must be > 0")

        session = self.storage.load_session(session_id)
        plan = self.storage.load_plan(session_id)
        day = next((item for item in plan.days if item.day_index == day_index), None)
        tasks = sorted(
            (task for task in plan.tasks if task.day_index == day_index),
            key=lambda item: (item.priority, item.task_id),
        )

        if day is None and not tasks:
            raise ValueError(f"Day not found: {day_index}")

        if not tasks:
            return DayPlanDetail(
                session_id=session_id,
                day_index=day_index,
                date=day.date if day else None,
                objective_summary="No fixed tasks today. Do a light review and warm-up.",
                time_blocks=[
                    DayPlanTimeBlock(
                        block_id=f"day{day_index}_fallback_01",
                        title="Light Review and Warm-up",
                        kind=TaskKind.REVIEW,
                        minutes=30,
                        steps=[
                            "Review yesterday's mistakes and key notes (10 min)",
                            "Explain core concepts out loud and write a 3-item checklist (10 min)",
                            "Preview tomorrow's topics and list 2 questions (10 min)",
                        ],
                        linked_task_ids=[],
                    )
                ],
                key_points=["Review prior knowledge", "Warm up new knowledge", "Keep learning continuity"],
                pitfalls=["Reviewing without practice accelerates forgetting", "Review without conclusions limits progress"],
                acceptance_criteria=["Complete one 3-line review note", "List at least 2 unresolved questions"],
                review_actions=["Save your review notes", "Prepare materials and question sets for tomorrow"],
                linked_task_ids=[],
            )

        linked_task_ids = [task.task_id for task in tasks]
        objective_summary = self._build_objective_summary(tasks)
        time_blocks = [self._to_time_block(day_index, idx, task) for idx, task in enumerate(tasks, start=1)]
        key_points = self._extract_key_points(tasks)
        pitfalls = self._collect_pitfalls(tasks)
        acceptance_criteria = self._build_acceptance_criteria(tasks)
        review_actions = self._build_review_actions(tasks, session.goal_config.preferences.include_practice)

        return DayPlanDetail(
            session_id=session_id,
            day_index=day_index,
            date=day.date if day else None,
            objective_summary=objective_summary,
            time_blocks=time_blocks,
            key_points=key_points,
            pitfalls=pitfalls,
            acceptance_criteria=acceptance_criteria,
            review_actions=review_actions,
            linked_task_ids=linked_task_ids,
        )

    def _build_days(self, daily_minutes: int, remaining_days: int, tasks: list) -> list[PlanDay]:
        dates = future_dates(remaining_days)
        days: list[PlanDay] = []
        for day_index in range(1, remaining_days + 1):
            task_ids = [task.task_id for task in tasks if task.day_index == day_index]
            days.append(
                PlanDay(
                    day_index=day_index,
                    date=dates[day_index - 1],
                    budget_minutes=daily_minutes,
                    task_ids=task_ids,
                    notes="Auto-generated learning tasks",
                )
            )
        return days

    def _stage_event(self, stage: str, progress: float) -> dict:
        return {
            "ts": datetime.now().isoformat(),
            "type": "stage",
            "stage": stage,
            "progress": progress,
        }

    def _to_time_block(self, day_index: int, index: int, task: Task) -> DayPlanTimeBlock:
        minutes = max(15, min(task.estimate_minutes, 120))
        return DayPlanTimeBlock(
            block_id=f"day{day_index}_{index:02d}",
            title=task.title,
            kind=task.kind,
            minutes=minutes,
            steps=self._build_steps_for_task(task),
            linked_task_ids=[task.task_id],
        )

    def _build_objective_summary(self, tasks: list[Task]) -> str:
        themes = [
            task.title.replace("Learn ", "").replace("Practice ", "").replace("学习 ", "").replace("练习 ", "")
            for task in tasks[:3]
        ]
        exam_oriented = any(
            task.practice_spec and task.practice_spec.question_type == "mimic_exam"
            for task in tasks
        )
        if exam_oriented:
            return (
                f"Complete {len(tasks)} tasks focused on high-yield score improvement: {', '.join(themes)}. "
                "Follow an explain-practice-correct-repractice loop and prioritize high-return content."
            )
        return f"Complete {len(tasks)} tasks with focus on: {', '.join(themes)}."

    def _extract_key_points(self, tasks: list[Task]) -> list[str]:
        points: list[str] = []
        for task in tasks:
            for chunk in re.split(r"[，,。；;、\n]+", task.objective):
                value = chunk.strip()
                if 4 <= len(value) <= 30 and value not in points:
                    points.append(value)
                if len(points) >= 6:
                    return points
        for task in tasks:
            title = (
                task.title.replace("Learn ", "")
                .replace("Practice ", "")
                .replace("Review ", "")
                .replace("学习 ", "")
                .replace("练习 ", "")
                .replace("复习 ", "")
                .strip()
            )
            if title and title not in points:
                points.append(title)
            if len(points) >= 6:
                break
        return points[:6]

    def _collect_pitfalls(self, tasks: list[Task]) -> list[str]:
        pitfalls: list[str] = []
        for task in tasks:
            template = {
                TaskKind.LEARN: [
                    "Reading definitions without active recall creates false mastery",
                    "Ignoring prerequisite concepts causes downstream gaps",
                ],
                TaskKind.PRACTICE: [
                    "Doing questions without summarizing patterns slows transfer",
                    "Not tracing root causes of mistakes leads to repeat errors",
                ],
                TaskKind.REVIEW: [
                    "Review by rereading only produces weak retention",
                ],
                TaskKind.QUIZ: [
                    "Looking only at scores without error causes blocks optimization",
                ],
            }.get(task.kind, ["Imbalanced pacing reduces daily completion quality"])
            for item in template:
                if item not in pitfalls:
                    pitfalls.append(item)
        return pitfalls[:5]

    def _build_acceptance_criteria(self, tasks: list[Task]) -> list[str]:
        exam_oriented = any(
            task.practice_spec and task.practice_spec.question_type == "mimic_exam"
            for task in tasks
        )
        criteria = [
            f"Complete {len(tasks)} tasks today and record completion status",
            "Produce at least 3 key takeaways (concepts/methods/common mistakes)",
        ]
        if any(task.kind == TaskKind.PRACTICE for task in tasks):
            criteria.append("After practice, document at least 2 error causes and fixes")
        if exam_oriented:
            criteria.append("Reach at least 70% accuracy on mock/high-yield sets (otherwise do one extra round)")
        criteria.append("Use 3 minutes to verbally summarize today's core content")
        return criteria

    def _build_review_actions(self, tasks: list[Task], include_practice: bool) -> list[str]:
        exam_oriented = any(
            task.practice_spec and task.practice_spec.question_type == "mimic_exam"
            for task in tasks
        )
        actions = [
            "Compress today's notes into a 3-line summary and save it",
            "Mark the least stable knowledge point for priority review tomorrow",
        ]
        if include_practice and any(task.practice_spec for task in tasks):
            actions.append("Archive mistakes as concept misunderstanding / calculation error / misreading")
        if exam_oriented:
            actions.append("Put high-loss question patterns into tomorrow's first timed practice block")
        actions.append("Preview tomorrow's tasks and prepare required materials")
        return actions

    def _build_steps_for_task(self, task: Task) -> list[str]:
        topic = (
            task.title.replace("Learn ", "")
            .replace("Practice ", "")
            .replace("Review ", "")
            .replace("学习 ", "")
            .replace("练习 ", "")
            .replace("复习 ", "")
        )
        if task.kind == TaskKind.LEARN:
            exam_oriented = bool(task.practice_spec and task.practice_spec.question_type == "mimic_exam")
            base_steps = [
                f"Quickly review core definitions and conclusions of {topic}",
                "Restate key ideas in your own words and write key formulas/points",
                "Finish 1-2 basic questions to verify understanding",
            ]
            if exam_oriented:
                base_steps.append("Extract a high-yield checklist and mark 2 mistake triggers")
            return base_steps
        if task.kind == TaskKind.PRACTICE:
            count = task.practice_spec.count if task.practice_spec else 3
            question_type = task.practice_spec.question_type if task.practice_spec else "short_answer"
            first_step = f"Complete {count} targeted questions by pattern"
            if question_type == "mimic_exam":
                first_step = f"Complete {count} high-yield mock-style questions with per-question time control"
            return [
                first_step,
                "Check answers question by question and log error causes",
                "Convert fragile steps into a checklist",
            ]
        if task.kind == TaskKind.REVIEW:
            return [
                f"Review weak points in {topic}",
                "Complete one retraining set for mistakes",
                "Write review conclusions and update your error bank",
            ]
        return [
            f"Complete tasks related to {topic}",
            "Record outcomes and update learning status",
        ]

    def _build_interactive_summary(
        self,
        detail: DayPlanDetail,
        goal_config: GoalConfig,
        blueprint: dict[str, Any] | None = None,
    ) -> str:
        topics = []
        for block in detail.time_blocks:
            topic = (
                block.title.replace("Learn ", "")
                .replace("Practice ", "")
                .replace("Review ", "")
                .replace("Error Drill ", "")
                .replace("学习 ", "")
                .replace("练习 ", "")
                .replace("复习 ", "")
                .replace("错题再练 ", "")
                .strip()
            )
            if topic and topic not in topics:
                topics.append(topic)
        topic_text = ", ".join(topics[:6]) if topics else "No clear topic yet"

        domain_pack = self._build_topic_domain_pack(topics)
        sections = [
            f"Today's core topics: {topic_text}",
            "Output must be exam-ready lecture-style content and avoid vague statements.",
            "Knowledge flow: definition and essence -> high-yield points -> common mistakes -> question templates and solving flow.",
            self._build_goal_config_profile(goal_config),
        ]
        if detail.key_points:
            sections.append("High-yield points: " + ", ".join(detail.key_points[:8]))
        if detail.pitfalls:
            sections.append("Common mistakes: " + "; ".join(detail.pitfalls[:5]))
        if detail.acceptance_criteria:
            sections.append("Success criteria: " + "; ".join(detail.acceptance_criteria[:4]))
        sections.append("Suggested teaching sequence: concept definition -> high-yield patterns -> solution templates -> mistake correction.")
        if domain_pack:
            sections.append("[Domain-enhanced lecture template]\n" + domain_pack)
        if blueprint:
            sections.append("[Structured lesson blueprint]\n" + self._format_interactive_blueprint(blueprint))
        return "\n".join(sections)

    async def _generate_interactive_blueprint(
        self,
        detail: DayPlanDetail,
        goal_config: GoalConfig,
        language: str,
    ) -> dict[str, Any]:
        fallback = self._fallback_interactive_blueprint(detail)
        topics = []
        for block in detail.time_blocks:
            topic = (
                block.title.replace("Learn ", "")
                .replace("Practice ", "")
                .replace("Review ", "")
                .replace("Error Drill ", "")
                .replace("学习 ", "")
                .replace("练习 ", "")
                .replace("复习 ", "")
                .replace("错题再练 ", "")
                .strip()
            )
            if topic and topic not in topics:
                topics.append(topic)
        topic_text = ", ".join(topics[:6]) if topics else "Today's core topics"
        key_points = ", ".join(detail.key_points[:8]) if detail.key_points else "No explicit high-yield points yet"
        pitfalls = "; ".join(detail.pitfalls[:6]) if detail.pitfalls else "No explicit common mistakes yet"
        objective = detail.objective_summary or f"Build exam-reusable capability around {topic_text}"
        profile_text = self._build_goal_config_profile(goal_config)
        system_prompt = (
            "You are an exam-oriented curriculum designer."
            " Return a concrete, actionable JSON blueprint with knowledge map, high-yield points, mistakes, question templates, and method flow."
            " Output JSON object only."
        )
        user_prompt = (
            f"[Objective]\n{objective}\n\n"
            f"[Topics]\n{topic_text}\n\n"
            f"[Plan profile]\n{profile_text}\n\n"
            f"[Known key points]\n{key_points}\n\n"
            f"[Known pitfalls]\n{pitfalls}\n\n"
            "Return JSON object with keys: domain, objective, knowledge_map, high_frequency_points, common_mistakes, question_patterns, method_flow, rapid_review, practice_checklist."
        )

        try:
            raw = await llm_complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2,
                max_tokens=1400,
                response_format={"type": "json_object"},
            )
            parsed = self._parse_json_payload(raw)
            if isinstance(parsed, dict):
                normalized = self._normalize_interactive_blueprint(parsed, fallback)
                score, issues = self._score_interactive_blueprint(normalized)
                if score >= 72:
                    return normalized
                repaired = await self._repair_interactive_blueprint(
                    normalized,
                    issues,
                    detail,
                    goal_config,
                    language,
                )
                repaired_score, _ = self._score_interactive_blueprint(repaired)
                return repaired if repaired_score >= score else normalized
            return fallback
        except Exception:
            return fallback

    async def _repair_interactive_blueprint(
        self,
        blueprint: dict[str, Any],
        issues: list[str],
        detail: DayPlanDetail,
        goal_config: GoalConfig,
        language: str,
    ) -> dict[str, Any]:
        fallback = self._fallback_interactive_blueprint(detail)
        profile_text = self._build_goal_config_profile(goal_config)
        issue_text = "; ".join(issues[:6]) if issues else "Insufficient detail density"
        system_prompt = (
            "You are a curriculum QA and refinement expert."
            " Improve the blueprint with concrete and actionable details. Output JSON object only."
        )
        user_prompt = (
            f"[Issues]\n{issue_text}\n\n"
            f"[Plan profile]\n{profile_text}\n\n"
            f"[Current Blueprint]\n{json.dumps(blueprint, ensure_ascii=False)}\n\n"
            "Return improved JSON with the same keys and stronger specificity."
        )
        try:
            raw = await llm_complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2,
                max_tokens=1400,
                response_format={"type": "json_object"},
            )
            parsed = self._parse_json_payload(raw)
            if isinstance(parsed, dict):
                return self._normalize_interactive_blueprint(parsed, fallback)
            return blueprint
        except Exception:
            return blueprint

    def _normalize_interactive_blueprint(
        self,
        blueprint: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(fallback)
        for key in (
            "domain",
            "objective",
            "knowledge_map",
            "high_frequency_points",
            "common_mistakes",
            "question_patterns",
            "method_flow",
            "rapid_review",
            "practice_checklist",
        ):
            value = blueprint.get(key)
            if value:
                normalized[key] = value
        return normalized

    def _parse_json_payload(self, response: str) -> object:
        text = (response or "").strip()
        if not text:
            raise json.JSONDecodeError("Empty response", response, 0)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        fence_match = re.search(r"```json\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence_match:
            return json.loads(fence_match.group(1).strip())
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
            return json.loads(text[obj_start : obj_end + 1])
        raise json.JSONDecodeError("No JSON payload found", response, 0)

    def _fallback_interactive_blueprint(self, detail: DayPlanDetail) -> dict[str, Any]:
        topics = []
        for block in detail.time_blocks:
            topic = (
                block.title.replace("Learn ", "")
                .replace("Practice ", "")
                .replace("Review ", "")
                .replace("Error Drill ", "")
                .replace("学习 ", "")
                .replace("练习 ", "")
                .replace("复习 ", "")
                .replace("错题再练 ", "")
                .strip()
            )
            if topic and topic not in topics:
                topics.append(topic)
        if not topics:
            topics = detail.key_points[:4] if detail.key_points else ["Core concepts", "High-yield points", "Typical patterns"]
        knowledge_map = [
            {
                "module": f"{index}. {topic}",
                "focus_points": [
                    f"Core definitions and boundaries of {topic}",
                    f"Common exam usage and solving steps for {topic}",
                ],
            }
            for index, topic in enumerate(topics[:4], start=1)
        ]
        high_frequency_points = [
            {
                "point": item,
                "why_high_yield": "Appears frequently and transfers to later question patterns",
                "exam_usage": "Often appears in foundational judgment or integrated application forms",
            }
            for item in (detail.key_points[:6] or topics[:4])
        ]
        common_mistakes = [
            {
                "mistake": pitfall,
                "fix": "Clarify definitions and conditions first, then solve step by step and verify key links",
                "quick_check": "Check whether conditions are complete and conclusions match the question",
            }
            for pitfall in (detail.pitfalls[:5] or ["Incomplete concept understanding leads to method misuse"])
        ]
        question_patterns = [
            {
                "pattern": "Foundational judgment questions",
                "trigger": "The prompt asks for correctness, feasibility, or conceptual relation judgment",
                "steps": ["Extract conditions", "Apply definitions/rules", "Give conclusion with brief reasoning"],
            },
            {
                "pattern": "Integrated application questions",
                "trigger": "Requires joint solving across multiple knowledge points",
                "steps": ["Break into subproblems", "Choose high-yield method", "Solve stepwise and back-check"],
            },
            {
                "pattern": "Parameter/boundary questions",
                "trigger": "Requires parameter range or boundary condition solving",
                "steps": ["List conditions", "Combine constraints", "Solve parameters and check edge cases"],
            },
        ]
        return {
            "domain": "exam-oriented",
            "objective": detail.objective_summary,
            "knowledge_map": knowledge_map,
            "high_frequency_points": high_frequency_points,
            "common_mistakes": common_mistakes,
            "question_patterns": question_patterns,
            "method_flow": ["Identify question type and objective", "Match method and execute", "Review result and log error causes"],
            "rapid_review": detail.acceptance_criteria[:3]
            or ["Restate core concepts", "List common pitfalls", "Write a reusable solving flow"],
            "practice_checklist": detail.review_actions[:4]
            or ["Finish one foundational and one integrated question", "Classify mistakes by cause", "Record priority review points for tomorrow"],
        }

    def _format_interactive_blueprint(self, blueprint: dict[str, Any]) -> str:
        sections = [
            f"Domain: {blueprint.get('domain', 'unknown')}",
            f"Objective: {blueprint.get('objective', '')}",
        ]
        knowledge_map = blueprint.get("knowledge_map") or []
        if isinstance(knowledge_map, list) and knowledge_map:
            lines = []
            for idx, item in enumerate(knowledge_map[:6], start=1):
                if not isinstance(item, dict):
                    continue
                module = str(item.get("module", f"Module {idx}")).strip()
                focus_points = item.get("focus_points") or []
                if isinstance(focus_points, list):
                    focus_text = ", ".join(str(p).strip() for p in focus_points[:5] if str(p).strip())
                else:
                    focus_text = str(focus_points).strip()
                lines.append(f"- {module}: {focus_text}")
            if lines:
                sections.append("Knowledge Map:\n" + "\n".join(lines))

        def _items(name: str, key: str, fields: list[str], limit: int = 8):
            values = blueprint.get(key) or []
            if not isinstance(values, list) or not values:
                return
            rendered = []
            for item in values[:limit]:
                if isinstance(item, dict):
                    parts = [str(item.get(f, "")).strip() for f in fields if str(item.get(f, "")).strip()]
                    if parts:
                        rendered.append("- " + " | ".join(parts))
                else:
                    text = str(item).strip()
                    if text:
                        rendered.append(f"- {text}")
            if rendered:
                sections.append(f"{name}：\n" + "\n".join(rendered))

        _items("High-yield Points", "high_frequency_points", ["point", "why_high_yield", "exam_usage"])
        _items("Common Mistakes", "common_mistakes", ["mistake", "fix", "quick_check"])
        _items("Question Templates", "question_patterns", ["pattern", "trigger", "steps"])
        _items("Method Flow", "method_flow", [])
        _items("30-Second Review", "rapid_review", [])
        _items("Practice Checklist", "practice_checklist", [])
        return "\n\n".join(sections)

    def _score_interactive_blueprint(self, blueprint: dict[str, Any]) -> tuple[int, list[str]]:
        score = 0
        issues: list[str] = []
        if str(blueprint.get("domain", "")).strip():
            score += 8
        else:
            issues.append("Missing domain label")
        if len(str(blueprint.get("objective", "")).strip()) >= 8:
            score += 8
        else:
            issues.append("Objective is too short")

        knowledge_map = blueprint.get("knowledge_map")
        if isinstance(knowledge_map, list) and len(knowledge_map) >= 2:
            detailed_modules = 0
            for item in knowledge_map:
                if not isinstance(item, dict):
                    continue
                fp = item.get("focus_points")
                if isinstance(fp, list) and len([x for x in fp if str(x).strip()]) >= 2:
                    detailed_modules += 1
            if detailed_modules >= 2:
                score += 22
            else:
                score += 10
                issues.append("Knowledge map hierarchy is unclear")
        else:
            issues.append("Insufficient knowledge map")

        def _count_rich(items: Any, required_fields: list[str]) -> int:
            if not isinstance(items, list):
                return 0
            cnt = 0
            for item in items:
                if isinstance(item, dict):
                    if all(str(item.get(field, "")).strip() for field in required_fields):
                        cnt += 1
            return cnt

        hf_cnt = _count_rich(
            blueprint.get("high_frequency_points"),
            ["point", "why_high_yield", "exam_usage"],
        )
        if hf_cnt >= 3:
            score += 18
        elif hf_cnt >= 2:
            score += 10
            issues.append("High-yield point details are thin")
        else:
            issues.append("Insufficient high-yield points")

        mistake_cnt = _count_rich(
            blueprint.get("common_mistakes"),
            ["mistake", "fix", "quick_check"],
        )
        if mistake_cnt >= 3:
            score += 16
        elif mistake_cnt >= 2:
            score += 9
            issues.append("Mistake correction details are insufficient")
        else:
            issues.append("Insufficient common mistakes")

        patterns = blueprint.get("question_patterns")
        if isinstance(patterns, list) and patterns:
            rich_patterns = 0
            for item in patterns:
                if not isinstance(item, dict):
                    continue
                steps = item.get("steps")
                if (
                    str(item.get("pattern", "")).strip()
                    and str(item.get("trigger", "")).strip()
                    and isinstance(steps, list)
                    and len([x for x in steps if str(x).strip()]) >= 2
                ):
                    rich_patterns += 1
            if rich_patterns >= 2:
                score += 16
            else:
                score += 8
                issues.append("Question template steps are incomplete")
        else:
            issues.append("Missing question templates")

        method_flow = blueprint.get("method_flow")
        if isinstance(method_flow, list) and len([x for x in method_flow if str(x).strip()]) >= 3:
            score += 12
        else:
            issues.append("Method flow is not actionable")

        return min(score, 100), issues

    def _build_interactive_generation_requirements(self, detail: DayPlanDetail, goal_config: GoalConfig) -> str:
        topics = []
        for block in detail.time_blocks:
            topic = (
                block.title.replace("Learn ", "")
                .replace("Practice ", "")
                .replace("Review ", "")
                .replace("Error Drill ", "")
                .replace("学习 ", "")
                .replace("练习 ", "")
                .replace("复习 ", "")
                .replace("错题再练 ", "")
                .strip()
            )
            if topic and topic not in topics:
                topics.append(topic)
        topic_text = ", ".join(topics[:6]) if topics else "Today's core topics"
        strategy_label = {
            "high_yield_first": "high-yield first",
            "depth_first": "depth first",
            "breadth_first": "breadth first",
        }.get(goal_config.preferences.strategy.value, "high-yield first")
        level_label = {
            "foundation": "foundation",
            "competent": "competent",
            "advanced": "advanced",
        }.get(goal_config.goal_level.value, "competent")
        weekly_rhythm = (
            f"Study {goal_config.days_per_week} days per week (other days are for light review/rest)."
            if goal_config.days_per_week < 7
            else "Study 7 days per week."
        )
        return (
            f"Target topics: {topic_text}\n"
            f"Goal level: {level_label}; strategy: {strategy_label}; "
            f"time budget: {goal_config.remaining_days} days x {goal_config.daily_minutes} minutes; "
            f"practice ratio: {int(goal_config.preferences.practice_ratio*100)}%; review ratio: {int(goal_config.preferences.review_ratio*100)}%.\n"
            f"Rhythm: {weekly_rhythm}\n"
            "1) Must include an overall knowledge-map section with topic -> subtopic -> key-point hierarchy.\n"
            "2) Must include high-yield points, each with conclusion/formula + condition + reminder.\n"
            "3) Must include common mistakes in mistake -> correction -> quick check format.\n"
            "4) Must include core question templates with trigger -> steps -> warning.\n"
            "5) Must include a visual method-selection flow (cards or flowchart), not plain paragraph only.\n"
            "6) Math/engineering topics should include formulas; programming topics should include code snippets.\n"
            "7) Wording must be specific and avoid placeholders.\n"
            "8) Add a 30-second review card at the bottom of each major section.\n"
            "9) Page default language must be English, including buttons and helper text.\n"
            "10) Interaction should include expand/collapse, mistake-correction toggles, and template step switching."
        )

    def _build_goal_config_profile(self, goal_config: GoalConfig) -> str:
        level_line = {
            "foundation": "Goal level: foundation (stabilize definitions, basic patterns, and high-yield basics first).",
            "competent": "Goal level: competent (balance core principles and medium-difficulty transfer).",
            "advanced": "Goal level: advanced (strengthen integrated problems, boundary cases, and harder variations).",
        }.get(goal_config.goal_level.value, "Goal level: competent.")
        strategy_line = {
            "high_yield_first": "Strategy: high-yield first (cover high-frequency, high-score topics first).",
            "depth_first": "Strategy: depth first (go deep along principle -> variation -> mistakes -> retraining).",
            "breadth_first": "Strategy: breadth first (build full map first, then connect key relations).",
        }.get(goal_config.preferences.strategy.value, "Strategy: high-yield first.")
        rhythm_line = (
            f"Rhythm: {goal_config.remaining_days} days, {goal_config.daily_minutes} minutes/day, {goal_config.days_per_week} study days/week."
        )
        practice_line = (
            f"Practice config: include_practice={goal_config.preferences.include_practice}, "
            f"practice_ratio={goal_config.preferences.practice_ratio:.2f}, "
            f"review_ratio={goal_config.preferences.review_ratio:.2f}."
        )
        return "\n".join([level_line, strategy_line, rhythm_line, practice_line])

    def _extract_text_from_html(self, html: str) -> str:
        text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _extract_text_from_upload(self, name: str, content_type: str, payload: bytes) -> str:
        lower_name = name.lower()
        if content_type == "application/pdf" or lower_name.endswith(".pdf"):
            return self._extract_pdf_text(payload)
        if (
            content_type.startswith("text/")
            or lower_name.endswith(".txt")
            or lower_name.endswith(".md")
            or lower_name.endswith(".json")
        ):
            return payload.decode("utf-8", errors="ignore")
        try:
            return payload.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def _extract_pdf_text(self, payload: bytes) -> str:
        try:
            import fitz  # type: ignore

            with fitz.open(stream=io.BytesIO(payload), filetype="pdf") as document:
                pages = []
                for page in document:
                    pages.append(page.get_text("text"))
                return "\n".join(pages).strip()
        except Exception:
            return ""

    def _build_topic_domain_pack(self, topics: list[str]) -> str:
        lowered = " ".join(topics).lower()
        if any(token in lowered for token in ("极限", "连续", "limit", "continuity")):
            return self._calculus_limit_continuity_pack()

        # Generic exam-oriented scaffolding for other topics.
        return (
            "I. Overall Knowledge Map\n"
            "1) Core definitions and essence\n"
            "2) Key properties and common conclusions\n"
            "3) Core relations (necessary/sufficient conditions)\n\n"
            "II. High-yield Points (memorization-ready)\n"
            "- 3-7 key formulas/conclusions\n"
            "- Each point includes conditions and common variations\n\n"
            "III. Common Mistakes\n"
            "- Concept misclassification\n"
            "- Missing conditions\n"
            "- Method misuse\n\n"
            "IV. Question Templates (directly usable)\n"
            "- Pattern 1: foundational judgment questions\n"
            "- Pattern 2: integrated application questions\n"
            "- Pattern 3: parameter/proof questions"
        )

    def _calculus_limit_continuity_pack(self) -> str:
        return (
            "I. Knowledge Map (must be visualized)\n"
            "1. Limits\n"
            "- Core definition: $\\lim_{x\\to x_0} f(x)=L$.\n"
            "- Three views: numerical approach, graphical approach, and $\\varepsilon-\\delta$ definition.\n"
            "- High-yield tools: algebraic transforms, squeeze theorem, monotone-bounded sequence ideas.\n"
            "2. Continuity\n"
            "- Definition: $\\lim_{x\\to x_0} f(x)=f(x_0)$.\n"
            "- Three checks: function value exists, limit exists, and they are equal.\n"
            "- Essence: no break at the point.\n"
            "3. Relation between limits and continuity\n"
            "- One-line rule: continuity = limit exists and equals function value.\n\n"
            "II. High-yield points (memorize directly)\n"
            "1) Important limits (at minimum)\n"
            "- $\\lim_{x\\to 0}\\frac{\\sin x}{x}=1$\n"
            "- $\\lim_{x\\to 0}(1+x)^{1/x}=e$\n"
            "- $\\lim_{x\\to 0}\\frac{\\tan x}{x}=1$\n"
            "- $\\lim_{x\\to 0}\\frac{e^x-1}{x}=1$\n"
            "- $\\lim_{x\\to 0}\\frac{\\ln(1+x)}{x}=1$\n"
            "2) Equivalent infinitesimal substitutions\n"
            "- $\\sin x\\sim x$, $\\tan x\\sim x$, $1-\\cos x\\sim x^2/2$, $e^x-1\\sim x$\n"
            "- Reminder: prefer multiplicative/division structures; be careful with additive/subtractive forms.\n"
            "3) L'Hopital's rule\n"
            "- Applicable forms: $0/0$ or $\\infty/\\infty$.\n"
            "- Re-check indeterminate form after each differentiation.\n\n"
            "III. Common mistakes\n"
            "- Missing the left-limit = right-limit condition.\n"
            "- Confusing removable/jump/infinite discontinuities.\n"
            "- Misusing equivalent substitutions in additive/subtractive forms.\n"
            "- Overusing L'Hopital where form is not indeterminate.\n"
            "- Forgetting function-value conditions in piecewise continuity checks.\n\n"
            "IV. Frequent templates\n"
            "- Pattern 1: evaluate limits (substitute -> transform -> substitute equivalent forms -> L'Hopital -> squeeze)\n"
            "- Pattern 2: test continuity (left limit, right limit, value, compare)\n"
            "- Pattern 3: fill value for continuity (compute limit, set equal to parameter)\n"
            "- Pattern 4: solve/prove with parameters (write form, set conditions, solve, verify edges)"
        )
