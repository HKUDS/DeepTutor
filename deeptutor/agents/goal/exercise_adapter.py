"""Practice generation adapter for Goal mode."""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.agents.question import AgentCoordinator
from deeptutor.agents.goal.models import Task
from deeptutor.services.llm.config import get_llm_config
from deeptutor.services.settings.interface_settings import get_ui_language


class ExerciseAdapter:
    """Persist a lightweight practice set for a task.

    Goal mode prefers the existing DeepTutor question pipeline. If the
    coordinator is unavailable or generation fails, it falls back to a
    deterministic local payload so the user still gets a usable artifact.
    """

    async def generate_for_task(self, task: Task, kb_name: str, output_dir: str | Path) -> dict:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{task.task_id}.json"
        payload = await self._generate_payload(task=task, kb_name=kb_name)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"practice_set_path": str(target), "practice_set": payload}

    async def _generate_payload(self, task: Task, kb_name: str) -> dict:
        try:
            llm_config = get_llm_config()
            coordinator = AgentCoordinator(
                api_key=llm_config.api_key,
                base_url=llm_config.base_url,
                api_version=getattr(llm_config, "api_version", None),
                kb_name=kb_name,
                language=get_ui_language(default="zh"),
            )
            result = await coordinator.generate_from_topic(
                user_topic=task.title,
                preference=task.objective,
                num_questions=task.practice_spec.count if task.practice_spec else 1,
                difficulty=task.practice_spec.difficulty if task.practice_spec else "easy",
                question_type=task.practice_spec.question_type if task.practice_spec else "short_answer",
            )
            if result.get("results"):
                return {
                    "task_id": task.task_id,
                    "kb_name": kb_name,
                    "source": "deeptutor_question",
                    "questions": [item.get("qa_pair", {}) for item in result["results"]],
                    "trace": result.get("trace", {}),
                }
        except Exception:
            pass

        return self._build_fallback_payload(task=task, kb_name=kb_name)

    def _build_fallback_payload(self, task: Task, kb_name: str) -> dict:
        return {
            "task_id": task.task_id,
            "kb_name": kb_name,
            "source": "fallback",
            "questions": [
                {
                    "prompt": f"请解释 {task.title} 的核心概念。",
                    "question_type": (task.practice_spec.question_type if task.practice_spec else "short_answer"),
                    "difficulty": (task.practice_spec.difficulty if task.practice_spec else "easy"),
                    "reference_answer": task.objective,
                }
            ],
        }
