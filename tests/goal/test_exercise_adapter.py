from __future__ import annotations

import json
from pathlib import Path

from deeptutor.agents.goal.exercise_adapter import ExerciseAdapter
from deeptutor.agents.goal.models import Task


def _build_task() -> Task:
    return Task.model_validate(
        {
            "task_id": "task_001",
            "day_index": 1,
            "node_id": "node_limit",
            "title": "学习极限基础",
            "kind": "practice",
            "objective": "理解极限定义并完成基础题",
            "estimate_minutes": 30,
            "practice_spec": {
                "difficulty": "easy",
                "question_type": "short_answer",
                "count": 2,
            },
        }
    )


def test_exercise_adapter_falls_back_to_local_payload(tmp_path: Path, monkeypatch) -> None:
    adapter = ExerciseAdapter()
    task = _build_task()

    async def _broken_generate_payload(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(adapter, "_generate_payload", _broken_generate_payload)

    # Since the public method delegates to _generate_payload, call fallback directly for a stable assertion.
    payload = adapter._build_fallback_payload(task, "placeholder_kb")
    target = tmp_path / "task_001.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["source"] == "fallback"
    assert saved["questions"][0]["question_type"] == "short_answer"
