"""Planning logic for Goal mode."""

from __future__ import annotations

from collections import defaultdict, deque

from deeptutor.agents.goal.models import GoalConfig, KnowledgeEdge, KnowledgeNode, PracticeSpec, Task, TaskKind, TaskResource


class Planner:
    """Create day-level tasks from a weighted graph."""

    def plan(
        self,
        nodes: list[KnowledgeNode],
        edges: list[KnowledgeEdge],
        goal_config: GoalConfig,
    ) -> list[Task]:
        ordered_nodes = self._topo_sort(nodes, edges)
        selected_nodes = self._select_high_yield_nodes(ordered_nodes, goal_config)
        tasks: list[Task] = []
        current_day = 1
        remaining_budget = goal_config.daily_minutes
        target_days = min(goal_config.remaining_days, max(len(selected_nodes), 1))
        exam_oriented = self._is_exam_oriented(goal_config.goal_statement)
        practice_profile = self._practice_profile(goal_config, exam_oriented)

        for index, node in enumerate(selected_nodes, start=1):
            learn_minutes = self._learn_minutes(node, goal_config)
            if learn_minutes > remaining_budget and current_day < goal_config.remaining_days:
                current_day += 1
                remaining_budget = goal_config.daily_minutes

            topic = node.title
            tasks.append(
                Task(
                    task_id=f"task_day{current_day}_{index:03d}",
                    day_index=current_day,
                    node_id=node.node_id,
                    title=f"Learn {topic}",
                    kind=TaskKind.LEARN,
                    objective=self._learn_objective(topic, exam_oriented, goal_config),
                    estimate_minutes=learn_minutes,
                    priority=index,
                    resources=[TaskResource(type="kb", ref=f"{goal_config.kb_name}/{node.node_id}")],
                    practice_spec=(
                        PracticeSpec(
                            difficulty=practice_profile["difficulty"],
                            question_type=practice_profile["question_type"],
                            count=practice_profile["count"],
                        )
                        if goal_config.preferences.include_practice
                        else None
                    ),
                )
            )
            remaining_budget -= learn_minutes

            if (
                goal_config.preferences.include_practice
                and remaining_budget >= practice_profile["minutes_floor"]
                and current_day <= goal_config.remaining_days
            ):
                practice_minutes = min(practice_profile["minutes"], remaining_budget)
                tasks.append(
                    Task(
                        task_id=f"task_day{current_day}_{index:03d}_practice",
                        day_index=current_day,
                        node_id=node.node_id,
                        title=f"Practice {topic}",
                        kind=TaskKind.PRACTICE,
                        objective=self._practice_objective(topic, exam_oriented, goal_config),
                        estimate_minutes=practice_minutes,
                        priority=index,
                        resources=[TaskResource(type="kb", ref=f"{goal_config.kb_name}/{node.node_id}")],
                        practice_spec=PracticeSpec(
                            difficulty=practice_profile["difficulty"],
                            question_type=practice_profile["question_type"],
                            count=practice_profile["count"],
                        ),
                        optional=False,
                    )
                )
                remaining_budget -= practice_minutes

            # Spread primary learning tasks across the available horizon before packing.
            if index < target_days and current_day < goal_config.remaining_days:
                current_day += 1
                remaining_budget = goal_config.daily_minutes

            if current_day >= goal_config.remaining_days and remaining_budget <= 0:
                break

        # Ensure the full horizon has executable tasks even when KB drafts are sparse
        # (e.g. placeholder/fallback KB with only a few nodes).
        if tasks:
            self._backfill_horizon(tasks, selected_nodes, goal_config, exam_oriented, practice_profile)

        return tasks

    def _backfill_horizon(
        self,
        tasks: list[Task],
        ordered_nodes: list[KnowledgeNode],
        goal_config: GoalConfig,
        exam_oriented: bool,
        practice_profile: dict[str, int | str],
    ) -> None:
        latest_day = max((task.day_index for task in tasks), default=0)
        if latest_day >= goal_config.remaining_days:
            return

        learn_by_node_id: dict[str, Task] = {}
        for task in tasks:
            if task.kind == TaskKind.LEARN and task.node_id not in learn_by_node_id:
                learn_by_node_id[task.node_id] = task

        if not learn_by_node_id:
            return

        ordered_learn_tasks = [
            learn_by_node_id[node.node_id]
            for node in ordered_nodes
            if node.node_id in learn_by_node_id
        ]
        if not ordered_learn_tasks:
            ordered_learn_tasks = list(learn_by_node_id.values())

        cursor = 0
        for day_index in range(latest_day + 1, goal_config.remaining_days + 1):
            base_task = ordered_learn_tasks[cursor % len(ordered_learn_tasks)]
            cursor += 1
            topic = base_task.title.replace("Learn ", "").replace("学习 ", "")
            tasks.append(
                Task(
                    task_id=f"{base_task.task_id}_review_d{day_index}",
                    day_index=day_index,
                    node_id=base_task.node_id,
                    title=f"Review and Reinforce {topic}",
                    kind=TaskKind.REVIEW,
                    objective=f"Review weak points in {topic}, summarize error causes, and complete targeted retraining.",
                    estimate_minutes=min(45, goal_config.daily_minutes),
                    priority=base_task.priority,
                    resources=base_task.resources,
                    practice_spec=base_task.practice_spec if goal_config.preferences.include_practice else None,
                    optional=False if day_index >= goal_config.remaining_days - 1 else True,
                )
            )
            if goal_config.preferences.include_practice and goal_config.daily_minutes >= int(practice_profile["minutes_floor"]):
                tasks.append(
                    Task(
                        task_id=f"{base_task.task_id}_drill_d{day_index}",
                        day_index=day_index,
                        node_id=base_task.node_id,
                        title=f"Error Drill {topic}",
                        kind=TaskKind.PRACTICE,
                        objective=self._practice_objective(topic, exam_oriented, goal_config),
                        estimate_minutes=min(int(practice_profile["minutes"]), max(20, goal_config.daily_minutes // 3)),
                        priority=base_task.priority,
                        resources=base_task.resources,
                        practice_spec=PracticeSpec(
                            difficulty=str(practice_profile["difficulty"]),
                            question_type=str(practice_profile["question_type"]),
                            count=int(practice_profile["count"]),
                        ),
                        optional=day_index < goal_config.remaining_days,
                    )
                )

    def _topo_sort(
        self,
        nodes: list[KnowledgeNode],
        edges: list[KnowledgeEdge],
    ) -> list[KnowledgeNode]:
        node_by_id = {node.node_id: node for node in nodes}
        indegree = {node.node_id: 0 for node in nodes}
        outgoing: dict[str, list[str]] = defaultdict(list)

        for edge in edges:
            if edge.edge_type.value != "prerequisite":
                continue
            if edge.from_ not in indegree or edge.to not in indegree:
                continue
            indegree[edge.to] += 1
            outgoing[edge.from_].append(edge.to)

        queue = deque(
            sorted(
                (node_by_id[node_id] for node_id, degree in indegree.items() if degree == 0),
                key=lambda node: node.weight,
                reverse=True,
            )
        )
        ordered: list[KnowledgeNode] = []
        while queue:
            node = queue.popleft()
            ordered.append(node)
            for child_id in outgoing.get(node.node_id, []):
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    queue.append(node_by_id[child_id])

        if len(ordered) != len(nodes):
            return sorted(nodes, key=lambda item: item.weight, reverse=True)
        return ordered

    def _select_high_yield_nodes(self, ordered_nodes: list[KnowledgeNode], goal_config: GoalConfig) -> list[KnowledgeNode]:
        if not ordered_nodes:
            return ordered_nodes

        total_budget = goal_config.remaining_days * goal_config.daily_minutes
        avg_minutes = max(25, int(sum(max(20, n.estimated_minutes) for n in ordered_nodes) / len(ordered_nodes)))
        capacity = max(1, total_budget // avg_minutes)

        # Under tight time constraints, prioritize top-weight nodes and allow strategic coverage tradeoffs.
        compress_ratio = 1.0
        if goal_config.remaining_days <= 7:
            compress_ratio = 0.85
        if goal_config.remaining_days <= 3:
            compress_ratio = 0.7
        if total_budget < len(ordered_nodes) * 40:
            compress_ratio = min(compress_ratio, 0.75)

        target_count = max(1, min(len(ordered_nodes), int(max(1, capacity) * compress_ratio)))
        strategy = goal_config.preferences.strategy.value
        if strategy == "breadth_first":
            return self._select_breadth_first_nodes(ordered_nodes, target_count)
        if strategy == "depth_first":
            return self._select_depth_first_nodes(ordered_nodes, target_count)
        return ordered_nodes[:target_count]

    def _select_breadth_first_nodes(
        self,
        ordered_nodes: list[KnowledgeNode],
        target_count: int,
    ) -> list[KnowledgeNode]:
        buckets: dict[str, list[KnowledgeNode]] = defaultdict(list)
        for node in ordered_nodes:
            if node.tags:
                key = str(node.tags[0]).strip() or node.node_type.value
            else:
                key = node.node_type.value
            buckets[key].append(node)

        keys = [key for key, nodes in buckets.items() if nodes]
        selected: list[KnowledgeNode] = []
        used = set()
        while len(selected) < target_count and keys:
            progressed = False
            for key in list(keys):
                nodes = buckets.get(key) or []
                while nodes and nodes[0].node_id in used:
                    nodes.pop(0)
                if not nodes:
                    keys.remove(key)
                    continue
                node = nodes.pop(0)
                if node.node_id in used:
                    continue
                selected.append(node)
                used.add(node.node_id)
                progressed = True
                if len(selected) >= target_count:
                    break
            if not progressed:
                break

        if len(selected) < target_count:
            for node in ordered_nodes:
                if node.node_id in used:
                    continue
                selected.append(node)
                used.add(node.node_id)
                if len(selected) >= target_count:
                    break
        return selected

    def _select_depth_first_nodes(
        self,
        ordered_nodes: list[KnowledgeNode],
        target_count: int,
    ) -> list[KnowledgeNode]:
        # Depth-first flavor: prioritize one coherent chain by repeatedly selecting
        # nodes that share the strongest prerequisites with already selected nodes.
        if target_count <= 1:
            return ordered_nodes[:target_count]
        selected = [ordered_nodes[0]]
        used = {ordered_nodes[0].node_id}
        while len(selected) < target_count:
            best_node: KnowledgeNode | None = None
            best_score = -1
            for node in ordered_nodes:
                if node.node_id in used:
                    continue
                overlap = len([pid for pid in node.prerequisites if pid in used])
                score = overlap * 10 + int(node.weight * 100)
                if score > best_score:
                    best_score = score
                    best_node = node
            if best_node is None:
                break
            selected.append(best_node)
            used.add(best_node.node_id)
        return selected[:target_count]

    def _is_exam_oriented(self, goal_statement: str) -> bool:
        if not goal_statement:
            return False
        text = goal_statement.lower()
        return any(
            token in text
            for token in (
                "exam",
                "past paper",
                "mock",
                "sprint",
                "score boost",
                "pass line",
                "target score",
                "mock",
                "past paper",
                "exam",
            )
        )

    def _practice_profile(self, goal_config: GoalConfig, exam_oriented: bool) -> dict[str, int | str]:
        ratio = max(0.25, min(0.7, goal_config.preferences.practice_ratio))
        minutes = max(20, min(45, int(goal_config.daily_minutes * ratio * 0.6)))
        question_type = "mimic_exam" if exam_oriented else "short_answer"
        difficulty = "medium"
        if goal_config.goal_level.value == "foundation":
            difficulty = "easy"
        elif goal_config.goal_level.value == "advanced":
            difficulty = "hard"
        count = 4 if exam_oriented else 3
        if goal_config.remaining_days <= 5:
            count += 1
        if goal_config.preferences.strategy.value == "high_yield_first":
            count += 1
            question_type = "mimic_exam" if exam_oriented else "short_answer"
        elif goal_config.preferences.strategy.value == "depth_first":
            minutes = min(50, minutes + 5)
        elif goal_config.preferences.strategy.value == "breadth_first":
            count = max(3, count - 1)
        return {
            "minutes": minutes,
            "minutes_floor": 20,
            "question_type": question_type,
            "difficulty": difficulty,
            "count": count,
        }

    def _learn_minutes(self, node: KnowledgeNode, goal_config: GoalConfig) -> int:
        base = max(25, min(node.estimated_minutes, 70))
        # High-yield nodes deserve denser explanation in short horizon settings.
        if goal_config.remaining_days <= 7 and ("high_yield" in node.tags or "高频" in node.tags or node.weight >= 0.65):
            base = min(base + 10, goal_config.daily_minutes)
        if goal_config.preferences.strategy.value == "depth_first":
            base = min(base + 8, goal_config.daily_minutes)
        elif goal_config.preferences.strategy.value == "breadth_first":
            base = max(20, base - 5)
        if goal_config.goal_level.value == "foundation":
            base = min(base + 5, goal_config.daily_minutes)
        elif goal_config.goal_level.value == "advanced":
            base = min(base + 8, goal_config.daily_minutes)
        return min(base, goal_config.daily_minutes)

    def _learn_objective(self, topic: str, exam_oriented: bool, goal_config: GoalConfig) -> str:
        target_band = self._target_band_label(goal_config)
        if exam_oriented:
            return (
                f"Cover high-yield exam patterns and worked examples for {topic}, "
                f"then produce a concept-method-mistake template to reach {target_band}."
            )
        return f"Understand core concepts and methods of {topic}, build transferable solving steps, and reach {target_band}."

    def _practice_objective(self, topic: str, exam_oriented: bool, goal_config: GoalConfig) -> str:
        target_band = self._target_band_label(goal_config)
        if exam_oriented:
            return f"Complete targeted and mock-style questions on {topic}, classify error causes, and run a fix-repractice-review loop toward {target_band}."
        return f"Complete targeted practice for {topic}, verify understanding, and close weak points toward {target_band}."

    def _target_band_label(self, goal_config: GoalConfig) -> str:
        if goal_config.goal_level.value == "foundation":
            return "baseline proficiency"
        if goal_config.goal_level.value == "competent":
            return "stable proficiency"
        return "high-score target"
