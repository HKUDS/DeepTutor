from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@dataclass
class TraceNode:
    """Node in the unified 3-level trace tree.

    Nodes use short IDs within a trace (e.g. ``S1``, ``S1.R1``).
    The full globally-unique ID is ``{trace_id}:{short_id}``.
    """

    short_id: str
    level: int
    text: str
    node_type: str
    action: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)
    parent: str | None = None

    def full_id(self, trace_id: str) -> str:
        return f"{trace_id}:{self.short_id}"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "short_id": self.short_id,
            "level": self.level,
            "text": self.text,
            "node_type": self.node_type,
            "children": self.children,
            "parent": self.parent,
        }
        if self.action:
            result["action"] = self.action
        if self.data:
            result["data"] = self.data
        return result

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TraceNode":
        short_id = str(payload.get("short_id", "") or payload.get("node_id", ""))
        return cls(
            short_id=short_id,
            level=int(payload.get("level", 0)),
            text=str(payload.get("text", "")),
            node_type=str(payload.get("node_type", "")),
            action=str(payload.get("action", "") or ""),
            data=dict(payload.get("data", {}) or {}),
            children=list(payload.get("children", []) or []),
            parent=payload.get("parent"),
        )


@dataclass
class TraceTree:
    """Unified trace tree for solve and question workflows.

    Nodes are keyed by ``short_id`` in the ``nodes`` dict.
    """

    trace_id: str
    trace_type: str
    timestamp: str
    root_id: str
    nodes: dict[str, TraceNode]
    answer_path: str = ""
    tools_used: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def root(self) -> TraceNode:
        return self.nodes[self.root_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "trace_type": self.trace_type,
            "timestamp": self.timestamp,
            "root_id": self.root_id,
            "answer_path": self.answer_path,
            "tools_used": self.tools_used,
            "stats": self.stats,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
        }

    # ------------------------------------------------------------------
    # Deserialization
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TraceTree":
        """Deserialize a trace tree from its JSON representation.

        Automatically detects and migrates the old format (``node_id``
        based keys, ``root`` object) to the new short-ID format.
        """
        if _is_old_format(payload):
            return cls._migrate_old(payload)

        nodes_payload = payload.get("nodes", {}) or {}
        nodes = {k: TraceNode.from_dict(v) for k, v in nodes_payload.items()}
        root_id = str(payload.get("root_id", "L1"))
        if root_id not in nodes and nodes:
            root_id = next(iter(nodes))
        return cls(
            trace_id=str(payload.get("trace_id", "")),
            trace_type=str(payload.get("trace_type", "")),
            timestamp=str(payload.get("timestamp", datetime.now().isoformat())),
            root_id=root_id,
            nodes=nodes,
            answer_path=str(payload.get("answer_path", "") or ""),
            tools_used=list(payload.get("tools_used", []) or []),
            stats=dict(payload.get("stats", {}) or {}),
        )

    @classmethod
    def _migrate_old(cls, payload: dict[str, Any]) -> "TraceTree":
        """Convert old format (verbose node_ids) to new short-ID format."""
        trace_id = str(payload.get("trace_id", ""))
        old_nodes = payload.get("nodes", {}) or {}

        old_to_new: dict[str, str] = {}
        for old_key in old_nodes:
            old_to_new[old_key] = _old_id_to_short(old_key, trace_id)

        old_root_payload = payload.get("root", {})
        old_root_id = str(old_root_payload.get("node_id", "")) if old_root_payload else ""
        if not old_root_id and old_nodes:
            old_root_id = next(iter(old_nodes))

        nodes: dict[str, TraceNode] = {}
        tools_seen: set[str] = set()
        step_count = 0
        round_count = 0

        for old_key, old_node_data in old_nodes.items():
            short = old_to_new[old_key]
            action = str(old_node_data.get("data", {}).get("action", "") or "")
            node = TraceNode(
                short_id=short,
                level=int(old_node_data.get("level", 0)),
                text=str(old_node_data.get("text", "")),
                node_type=str(old_node_data.get("node_type", "")),
                action=action,
                data=dict(old_node_data.get("data", {}) or {}),
                children=[old_to_new.get(c, c) for c in (old_node_data.get("children") or [])],
                parent=old_to_new.get(old_node_data.get("parent", ""), old_node_data.get("parent")),
            )
            nodes[short] = node
            if node.level == 2:
                step_count += 1
            elif node.level == 3:
                round_count += 1
            if action and action not in ("done", "replan", ""):
                tools_seen.add(action)

        root_id = old_to_new.get(old_root_id, "L1")
        return cls(
            trace_id=trace_id,
            trace_type=str(payload.get("trace_type", "")),
            timestamp=str(payload.get("timestamp", "")),
            root_id=root_id,
            nodes=nodes,
            answer_path=str(payload.get("answer_path", "") or ""),
            tools_used=sorted(tools_seen) or list(payload.get("tools_used", []) or []),
            stats=payload.get("stats") or {"steps": step_count, "rounds": round_count},
        )

    # ------------------------------------------------------------------
    # Factory: Solve workflow
    # ------------------------------------------------------------------

    @classmethod
    def from_scratchpad(
        cls,
        scratchpad: Any,
        task_id: str,
        answer_path: str = "",
    ) -> "TraceTree":
        """Build a solve trace tree from Scratchpad-like data.

        Structure::

            L1 (question)
            ├─ S1 (step)
            │  ├─ S1.R1 (round)
            │  └─ S1.R2 (round)
            └─ S2 (step)
               └─ S2.R1 (round)
        """
        ts = datetime.now().isoformat()
        trace_id = task_id or f"solve_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        question = str(_get(scratchpad, "question", "") or "")

        root = TraceNode(
            short_id="L1",
            level=1,
            text=question,
            node_type="question",
            data={"question": question},
        )
        nodes: dict[str, TraceNode] = {"L1": root}

        plan = _get(scratchpad, "plan", None)
        raw_steps = _get(plan, "steps", []) if plan is not None else []
        entries = list(_get(scratchpad, "entries", []) or [])

        tools_seen: set[str] = set()
        round_total = 0

        for step_idx, step in enumerate(raw_steps, 1):
            step_id_raw = str(_get(step, "id", f"S{step_idx}"))
            step_short = f"S{step_idx}"
            step_goal = str(_get(step, "goal", "") or "")
            step_status = str(_get(step, "status", "pending"))
            tools_hint = list(_get(step, "tools_hint", []) or [])

            step_node = TraceNode(
                short_id=step_short,
                level=2,
                text=step_goal or step_short,
                node_type="step",
                data={
                    "step_id": step_id_raw,
                    "step_goal": step_goal,
                    "status": step_status,
                    "tools_hint": tools_hint,
                },
                parent="L1",
            )
            root.children.append(step_short)
            nodes[step_short] = step_node

            step_entries = [
                e for e in entries if str(_get(e, "step_id", "")) == step_id_raw
            ]
            step_entries.sort(key=lambda e: int(_get(e, "round", 0)))

            for round_idx, entry in enumerate(step_entries, 1):
                round_total += 1
                thought = str(_get(entry, "thought", "") or "")
                action = str(_get(entry, "action", "") or "")
                action_input = str(_get(entry, "action_input", "") or "")
                observation = str(_get(entry, "observation", "") or "")
                self_note = str(_get(entry, "self_note", "") or "")
                timestamp = str(_get(entry, "timestamp", "") or "")
                sources = _get(entry, "sources", []) or []

                round_short = f"{step_short}.R{round_idx}"
                round_text = self_note or thought or observation[:200]

                round_node = TraceNode(
                    short_id=round_short,
                    level=3,
                    text=round_text,
                    node_type="round",
                    action=action,
                    data={
                        "step_id": step_id_raw,
                        "round": int(_get(entry, "round", round_idx)),
                        "thought": thought,
                        "action_input": action_input,
                        "observation": observation,
                        "self_note": self_note,
                        "timestamp": timestamp,
                        "sources": [
                            s.to_dict() if hasattr(s, "to_dict") else dict(s) if isinstance(s, dict) else {"value": str(s)}
                            for s in sources
                        ],
                    },
                    parent=step_short,
                )
                step_node.children.append(round_short)
                nodes[round_short] = round_node

                if action and action not in ("done", "replan"):
                    tools_seen.add(action)

        return cls(
            trace_id=trace_id,
            trace_type="solve",
            timestamp=ts,
            root_id="L1",
            nodes=nodes,
            answer_path=answer_path,
            tools_used=sorted(tools_seen),
            stats={"steps": len(raw_steps), "rounds": round_total},
        )

    # ------------------------------------------------------------------
    # Factory: Question workflow
    # ------------------------------------------------------------------

    @classmethod
    def from_question_summary(
        cls,
        summary: dict[str, Any],
        user_topic: str,
        task_id: str,
        include_answers: bool = True,
        answer_path: str = "",
    ) -> "TraceTree":
        """Build a question trace tree from summary.json-like data.

        Structure::

            L1 (topic)
            ├─ T1 (template)
            │  └─ T1.A1 (answer)
            └─ T2 (template)
               └─ T2.A1 (answer)
        """
        ts = datetime.now().isoformat()
        trace_id = task_id or f"question_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        root_text = (user_topic or "").strip() or str(summary.get("source", "question"))

        root = TraceNode(
            short_id="L1",
            level=1,
            text=root_text,
            node_type="topic",
            data={"topic": root_text, "source": summary.get("source", "topic")},
        )
        nodes: dict[str, TraceNode] = {"L1": root}

        results = list(summary.get("results", []) or [])
        answer_count = 0

        for idx, result in enumerate(results, 1):
            template = result.get("template", {}) or {}
            qa_pair = result.get("qa_pair", {}) or {}

            question_id = str(
                template.get("question_id") or qa_pair.get("question_id") or f"q_{idx}"
            )
            concentration = str(template.get("concentration", "") or "")
            question_type = str(
                template.get("question_type") or qa_pair.get("question_type") or "written"
            )
            difficulty = str(
                template.get("difficulty") or qa_pair.get("difficulty") or "medium"
            )

            tmpl_short = f"T{idx}"
            template_node = TraceNode(
                short_id=tmpl_short,
                level=2,
                text=concentration or question_id,
                node_type="template",
                data={
                    "question_id": question_id,
                    "concentration": concentration,
                    "question_type": question_type,
                    "difficulty": difficulty,
                    "template": template,
                },
                parent="L1",
            )
            root.children.append(tmpl_short)
            nodes[tmpl_short] = template_node

            if not include_answers:
                continue

            user_answer = qa_pair.get("user_answer")
            judged = qa_pair.get("judged_result")
            answer_text = ""
            if isinstance(user_answer, str):
                answer_text = user_answer
            elif user_answer is not None:
                answer_text = str(user_answer)
            elif isinstance(qa_pair.get("answer"), str):
                answer_text = qa_pair.get("answer", "")

            leaf_text = answer_text or str(qa_pair.get("question", ""))[:200] or concentration
            answer_short = f"{tmpl_short}.A1"
            answer_count += 1
            answer_node = TraceNode(
                short_id=answer_short,
                level=3,
                text=leaf_text,
                node_type="answer",
                data={
                    "question_id": question_id,
                    "question": qa_pair.get("question", ""),
                    "user_answer": user_answer,
                    "judged_result": judged,
                    "correct_answer": qa_pair.get("correct_answer", ""),
                    "explanation": qa_pair.get("explanation", ""),
                    "validation": qa_pair.get("validation", {}),
                    "success": bool(result.get("success", False)),
                },
                parent=tmpl_short,
            )
            template_node.children.append(answer_short)
            nodes[answer_short] = answer_node

        return cls(
            trace_id=trace_id,
            trace_type="question",
            timestamp=ts,
            root_id="L1",
            nodes=nodes,
            answer_path=answer_path,
            tools_used=[],
            stats={"templates": len(results), "answers": answer_count},
        )

    # ------------------------------------------------------------------
    # Compact text for LLM consumption
    # ------------------------------------------------------------------

    def compact_text(self, max_chars: int = 8000) -> str:
        """Build compact readable text with short IDs for LLM analysis."""
        ts_short = self.timestamp[:16].replace("T", " ") if self.timestamp else ""
        lines: list[str] = [
            f"[{self.trace_id}] {self.trace_type} | {ts_short}",
            f"Question: {self.root.text}",
        ]
        if self.answer_path:
            lines.append(f"Answer: {self.answer_path}")
        lines.append("")

        def _render(node_id: str, depth: int) -> None:
            node = self.nodes.get(node_id)
            if node is None:
                return
            indent = "  " * max(0, depth)
            if node.level == 2:
                status = node.data.get("status", "")
                status_tag = f" ({status})" if status else ""
                lines.append(
                    f"{indent}[{node.short_id}] {node.node_type}{status_tag}: {node.text}"
                )
            elif node.level == 3:
                action_tag = node.action or node.node_type
                lines.append(
                    f"{indent}[{node.short_id}] {action_tag} -> {node.text}"
                )
            else:
                lines.append(
                    f"{indent}[{node.short_id}] ({node.node_type}) {node.text}"
                )
            for child_id in node.children:
                _render(child_id, depth + 1)

        for child_id in self.root.children:
            _render(child_id, 0)

        text = "\n".join(lines)
        if len(text) > max_chars:
            return text[: max_chars - 3] + "..."
        return text


# ======================================================================
# Old-format detection & migration helpers
# ======================================================================

def _is_old_format(payload: dict[str, Any]) -> bool:
    """Detect old trace format (has ``root`` object or verbose node_id keys)."""
    if "root" in payload and isinstance(payload["root"], dict):
        return True
    nodes = payload.get("nodes", {})
    if isinstance(nodes, dict) and nodes:
        first_key = next(iter(nodes))
        if ":" in first_key and ("L1:" in first_key or "L2:" in first_key or "L3:" in first_key):
            return True
    return False


_STEP_RE = re.compile(r":L2:(?:step|template):(\w+)$")
_ROUND_RE = re.compile(r":L3:(?:round|answer):(\w+)")


def _old_id_to_short(old_id: str, trace_id: str) -> str:
    """Convert a verbose old-format node_id to a short_id."""
    suffix = old_id
    if trace_id and old_id.startswith(trace_id + ":"):
        suffix = old_id[len(trace_id) + 1:]

    if suffix.startswith("L1:"):
        return "L1"

    m_step = _STEP_RE.search(old_id)
    if m_step and ":L2:step:" in old_id:
        raw = m_step.group(1)
        return raw if raw.startswith("S") else f"S{raw}"
    if m_step and ":L2:template:" in old_id:
        raw = m_step.group(1)
        idx = raw.replace("q_", "")
        return f"T{idx}" if idx.isdigit() else f"T{raw}"

    m_round = _ROUND_RE.search(old_id)
    if m_round and ":L3:round:" in old_id:
        parts = suffix.split(":")
        step_raw = parts[2] if len(parts) > 2 else "S1"
        step_short = step_raw if step_raw.startswith("S") else f"S{step_raw}"
        round_idx = parts[-1] if len(parts) > 4 else "1"
        return f"{step_short}.R{round_idx}"
    if m_round and ":L3:answer:" in old_id:
        parts = suffix.split(":")
        q_raw = parts[2] if len(parts) > 2 else "1"
        idx = q_raw.replace("q_", "")
        tmpl_short = f"T{idx}" if idx.isdigit() else f"T{q_raw}"
        return f"{tmpl_short}.A1"

    return suffix
