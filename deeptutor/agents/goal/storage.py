"""Storage helpers for Goal-Oriented Adaptive Learning Mode."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from deeptutor.agents.goal.models import GoalSession, KnowledgeEdge, KnowledgeNode, Plan, model_to_dict
from deeptutor.services.path_service import get_path_service


class GoalStorage:
    """Persist goal sessions, plans, graphs, and event streams under ``data/user/goal``."""

    def __init__(self, base_dir: str | Path | None = None):
        if base_dir is None:
            self.base_dir = get_path_service().get_goal_root_dir()
        else:
            self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_session_dir(self, session_id: str) -> Path:
        path = self.base_dir / session_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "practice").mkdir(parents=True, exist_ok=True)
        (path / "artifacts").mkdir(parents=True, exist_ok=True)
        return path

    def save_session(self, session: GoalSession) -> str:
        session_dir = self.get_session_dir(session.session_id)
        target = session_dir / session.artifacts.session_json
        self._atomic_write_json(target, model_to_dict(session))
        return str(target)

    def save_plan(self, plan: Plan) -> str:
        session_dir = self.get_session_dir(plan.session_id)
        target = session_dir / plan.artifacts.plan_json
        if target.exists():
            previous = self._read_json(target)
            previous_version = previous.get("plan_version")
            if isinstance(previous_version, int):
                versioned = session_dir / f"plan.v{previous_version}.json"
                self._atomic_write_json(versioned, previous)
        self._atomic_write_json(target, model_to_dict(plan))
        return str(target)

    def save_graph(
        self,
        session_id: str,
        nodes: list[KnowledgeNode],
        edges: list[KnowledgeEdge],
        filename: str = "graph.json",
    ) -> str:
        session_dir = self.get_session_dir(session_id)
        target = session_dir / filename
        payload = {
            "knowledge_nodes": [model_to_dict(node) for node in nodes],
            "knowledge_edges": [model_to_dict(edge) for edge in edges],
        }
        self._atomic_write_json(target, payload)
        return str(target)

    def append_event(self, session_id: str, event: dict[str, Any]) -> None:
        session_dir = self.get_session_dir(session_id)
        target = session_dir / "events.jsonl"
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def load_session(self, session_id: str) -> GoalSession:
        session_dir = self.get_session_dir(session_id)
        data = self._read_json(session_dir / "session.json")
        return GoalSession.model_validate(data)

    def load_plan(self, session_id: str) -> Plan:
        session_dir = self.get_session_dir(session_id)
        data = self._read_json(session_dir / "plan.json")
        return Plan.model_validate(data)

    def _read_json(self, path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_handle:
            json.dump(payload, tmp_handle, indent=2, ensure_ascii=False)
            tmp_handle.flush()
            os.fsync(tmp_handle.fileno())
            Path(tmp_handle.name).replace(path)
