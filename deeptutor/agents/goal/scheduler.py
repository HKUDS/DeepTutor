"""Feedback-based replanning for Goal mode."""

from __future__ import annotations

from copy import deepcopy

from deeptutor.agents.goal.models import CompletionStatus, Feedback, Plan, PlanDiff, Task, TaskKind, TaskStatus


class Scheduler:
    """Apply simple deterministic replan rules to an existing plan."""

    def replan(
        self,
        plan: Plan,
        feedback_batch: list[Feedback],
    ) -> tuple[Plan, dict]:
        new_plan = deepcopy(plan)
        diff = PlanDiff()
        tasks_by_id = {task.task_id: task for task in new_plan.tasks}
        existing_task_ids = {task.task_id for task in new_plan.tasks}

        for feedback in feedback_batch:
            task = tasks_by_id.get(feedback.task_id)
            if task is None:
                continue

            if feedback.quiz and feedback.quiz.score / feedback.quiz.total < 0.6:
                review_task = self._build_review_task(task)
                if review_task.task_id not in existing_task_ids:
                    new_plan.tasks.append(review_task)
                    existing_task_ids.add(review_task.task_id)
                    self._assign_to_day(new_plan, review_task)
                    diff.added_tasks.append(review_task.task_id)
                drill_task = self._build_drill_task(task)
                if drill_task.task_id not in existing_task_ids:
                    new_plan.tasks.append(drill_task)
                    existing_task_ids.add(drill_task.task_id)
                    self._assign_to_day(new_plan, drill_task)
                    diff.added_tasks.append(drill_task.task_id)

            if feedback.completion in {CompletionStatus.PARTIAL, CompletionStatus.MISSED}:
                task.status = TaskStatus.PENDING
                task.day_index = min(task.day_index + 1, self._max_day_index(new_plan))
                diff.moved_tasks.append(task.task_id)
                dropped = self._drop_low_yield_optional_task(new_plan)
                if dropped:
                    diff.dropped_tasks.append(dropped)
            elif feedback.completion == CompletionStatus.DONE:
                task.status = TaskStatus.DONE
            elif feedback.completion == CompletionStatus.SKIPPED:
                task.status = TaskStatus.SKIPPED

        new_plan.plan_version += 1
        new_plan.diff = diff
        self._refresh_days(new_plan)
        return new_plan, diff.model_dump(mode="json")

    def _build_review_task(self, task: Task) -> Task:
        return Task(
            task_id=f"{task.task_id}_review",
            day_index=task.day_index + 1,
            node_id=task.node_id,
            title=f"Review {task.title}",
            kind=TaskKind.REVIEW,
            objective=f"Review weak points in {task.title} and practice again for reinforcement.",
            estimate_minutes=max(20, min(30, task.estimate_minutes)),
            priority=task.priority,
            resources=task.resources,
            practice_spec=task.practice_spec,
        )

    def _build_drill_task(self, task: Task) -> Task:
        practice_spec = task.practice_spec
        if practice_spec is not None:
            practice_spec = practice_spec.model_copy(update={"count": max(3, practice_spec.count)})
        return Task(
            task_id=f"{task.task_id}_drill",
            day_index=task.day_index + 1,
            node_id=task.node_id,
            title=f"Error Drill {task.title}",
            kind=TaskKind.PRACTICE,
            objective=f"Re-practice {task.title} by targeting error causes until performance is stable.",
            estimate_minutes=max(20, min(35, task.estimate_minutes)),
            priority=task.priority,
            resources=task.resources,
            practice_spec=practice_spec,
            optional=False,
        )

    def _assign_to_day(self, plan: Plan, task: Task) -> None:
        for day in plan.days:
            if day.day_index == task.day_index:
                day.task_ids.append(task.task_id)
                return
        plan.days.append(
            type(plan.days[0]).model_validate(
                {
                    "day_index": task.day_index,
                    "budget_minutes": max(task.estimate_minutes, 60),
                    "task_ids": [task.task_id],
                }
            )
        )

    def _refresh_days(self, plan: Plan) -> None:
        max_day = max((task.day_index for task in plan.tasks), default=0)
        day_map = {day.day_index: day for day in plan.days}
        for day_index in range(1, max_day + 1):
            day = day_map.get(day_index)
            if day is None:
                continue
            day.task_ids = [task.task_id for task in plan.tasks if task.day_index == day_index]
        plan.days.sort(key=lambda item: item.day_index)

    def _drop_low_yield_optional_task(self, plan: Plan) -> str | None:
        candidates = sorted(
            [task for task in plan.tasks if task.optional and task.kind in {TaskKind.REVIEW, TaskKind.PRACTICE}],
            key=lambda task: (task.priority, -task.day_index),
            reverse=True,
        )
        if not candidates:
            return None
        dropped = candidates[0]
        plan.tasks = [task for task in plan.tasks if task.task_id != dropped.task_id]
        return dropped.task_id

    def _max_day_index(self, plan: Plan) -> int:
        return max((day.day_index for day in plan.days), default=1)
