"""
Scratchpad - Unified memory for the Plan -> ReAct -> Write pipeline.

Replaces InvestigateMemory + SolveMemory + CitationMemory with a single
linear data structure that tracks the plan, all ReAct iterations, and
sources for citation.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Optional tiktoken for accurate token counting
try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Source:
    """A citation source attached to a retrieval entry."""

    type: str  # rag, web, code
    file: str | None = None
    page: int | None = None
    url: str | None = None
    chunk_id: str | None = None

    # ---------- serialisation helpers ----------
    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Source:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PlanStep:
    """One step in the plan produced by PlannerAgent."""

    id: str
    goal: str
    tools_hint: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | in_progress | completed | skipped

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanStep:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Plan:
    """High-level plan output by PlannerAgent."""

    analysis: str = ""
    steps: list[PlanStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Plan:
        steps = [PlanStep.from_dict(s) for s in data.get("steps", [])]
        return cls(analysis=data.get("analysis", ""), steps=steps)


@dataclass
class Entry:
    """One ReAct iteration entry."""

    step_id: str
    round: int
    thought: str = ""
    action: str = ""
    action_input: str = ""
    observation: str = ""
    self_note: str = ""
    sources: list[Source] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sources"] = [s.to_dict() for s in self.sources]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entry:
        sources = [Source.from_dict(s) for s in data.get("sources", [])]
        filtered = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "sources"}
        return cls(sources=sources, **filtered)


# ---------------------------------------------------------------------------
# Scratchpad
# ---------------------------------------------------------------------------


class Scratchpad:
    """Unified memory: plan + ReAct entries + metadata."""

    VERSION = "1.0"
    FILENAME = "scratchpad.json"

    def __init__(self, question: str) -> None:
        self.question: str = question
        self.plan: Plan | None = None
        self.entries: list[Entry] = []
        self.metadata: dict[str, Any] = {
            "total_llm_calls": 0,
            "total_tokens": 0,
            "start_time": datetime.now().isoformat(),
            "plan_revisions": 0,
        }

    # ------------------------------------------------------------------
    # Plan management
    # ------------------------------------------------------------------

    def set_plan(self, plan: Plan) -> None:
        """Set the initial plan."""
        self.plan = plan

    def update_plan(self, new_plan: Plan) -> None:
        """Replan: keep completed steps from the old plan, replace the rest."""
        if self.plan is None:
            self.plan = new_plan
            return

        self.metadata["plan_revisions"] = self.metadata.get("plan_revisions", 0) + 1

        completed = [s for s in self.plan.steps if s.status == "completed"]
        completed_ids = {s.id for s in completed}

        # New steps = completed (preserved) + new pending steps (with fresh IDs)
        new_pending = [s for s in new_plan.steps if s.id not in completed_ids]
        self.plan.analysis = new_plan.analysis
        self.plan.steps = completed + new_pending

    # ------------------------------------------------------------------
    # Step status management
    # ------------------------------------------------------------------

    def mark_step_status(self, step_id: str, status: str) -> None:
        if self.plan is None:
            return
        for step in self.plan.steps:
            if step.id == step_id:
                step.status = status
                return

    def get_next_pending_step(self) -> PlanStep | None:
        if self.plan is None:
            return None
        for step in self.plan.steps:
            if step.status == "pending":
                return step
        return None

    def get_completed_steps(self) -> list[PlanStep]:
        if self.plan is None:
            return []
        return [s for s in self.plan.steps if s.status == "completed"]

    def is_all_completed(self) -> bool:
        if self.plan is None:
            return True
        return all(s.status in ("completed", "skipped") for s in self.plan.steps)

    # ------------------------------------------------------------------
    # Entry management
    # ------------------------------------------------------------------

    def add_entry(
        self,
        step_id: str,
        round_num: int,
        thought: str,
        action: str,
        action_input: str,
        observation: str,
        self_note: str,
        sources: list[Source] | None = None,
    ) -> Entry:
        entry = Entry(
            step_id=step_id,
            round=round_num,
            thought=thought,
            action=action,
            action_input=action_input,
            observation=observation,
            self_note=self_note,
            sources=sources or [],
        )
        self.entries.append(entry)
        return entry

    def get_entries_for_step(self, step_id: str) -> list[Entry]:
        return [e for e in self.entries if e.step_id == step_id]

    # ------------------------------------------------------------------
    # Context builders (for prompt construction with compression)
    # ------------------------------------------------------------------

    def build_solver_context(
        self,
        current_step_id: str,
        max_tokens: int = 6000,
    ) -> dict[str, str]:
        """Build compressed context for SolverAgent prompt.

        Returns dict with keys: plan, current_step, step_history, previous_knowledge
        """
        # Plan summary
        plan_text = self._format_plan()

        # Current step description
        current_step_text = ""
        if self.plan:
            for s in self.plan.steps:
                if s.id == current_step_id:
                    current_step_text = f"[{s.id}] {s.goal}"
                    break

        # Step history (current step entries – full observations)
        current_entries = self.get_entries_for_step(current_step_id)
        step_history_parts: list[str] = []
        for e in current_entries:
            step_history_parts.append(
                f"Round {e.round}:\n"
                f"  Thought: {e.thought}\n"
                f"  Action: {e.action}({e.action_input})\n"
                f"  Observation: {e.observation}\n"
                f"  Note: {e.self_note}"
            )
        step_history = "\n\n".join(step_history_parts) if step_history_parts else "(no actions yet)"

        # Tool usage stats for the current step — helps the agent detect
        # repeated calls to the same tool and consider switching strategy.
        tool_actions = [e.action for e in current_entries if e.action not in ("done", "replan", "")]
        if tool_actions:
            from collections import Counter
            counts = Counter(tool_actions)
            stats = ", ".join(f"{tool} ×{n}" for tool, n in counts.most_common())
            step_history += f"\n\n[Tool usage this step: {stats}]"

        # Previous knowledge from completed steps (compressed)
        previous_parts: list[str] = []
        if self.plan:
            completed_ids = [s.id for s in self.plan.steps if s.status == "completed"]
            for sid in completed_ids:
                entries = self.get_entries_for_step(sid)
                step_obj = next((s for s in self.plan.steps if s.id == sid), None)
                goal_text = step_obj.goal if step_obj else sid
                notes = [e.self_note for e in entries if e.self_note]
                if notes:
                    previous_parts.append(f"[{sid}] {goal_text}: {' '.join(notes)}")

        previous_knowledge = "\n".join(previous_parts) if previous_parts else "(no previous steps completed)"

        # Token budget check – if over budget, aggressively compress previous_knowledge
        total = self._estimate_tokens(plan_text + current_step_text + step_history + previous_knowledge)
        if total > max_tokens and previous_parts:
            # Keep only self_notes, one line each
            compressed = []
            for sid in completed_ids:
                entries = self.get_entries_for_step(sid)
                notes = " | ".join(e.self_note for e in entries if e.self_note)
                if notes:
                    compressed.append(f"[{sid}]: {notes}")
            previous_knowledge = "\n".join(compressed) if compressed else "(compressed)"

        return {
            "plan": plan_text,
            "current_step": current_step_text,
            "step_history": step_history,
            "previous_knowledge": previous_knowledge,
        }

    def build_writer_context(self, max_tokens: int = 12000) -> str:
        """Build context for WriterAgent – preserves more detail."""
        parts: list[str] = []

        if self.plan:
            parts.append("## Plan\n" + self._format_plan())

        if not self.plan:
            return "\n\n".join(parts) or "(no evidence gathered)"

        for step in self.plan.steps:
            if step.status not in ("completed", "in_progress"):
                continue
            entries = self.get_entries_for_step(step.id)
            if not entries:
                continue

            step_parts = [f"### Step {step.id}: {step.goal}"]
            for e in entries:
                entry_text = (
                    f"**Round {e.round}** — Action: {e.action}({e.action_input})\n"
                    f"Note: {e.self_note}\n"
                    f"Observation:\n{e.observation}"
                )
                step_parts.append(entry_text)
            parts.append("\n\n".join(step_parts))

        full = "\n\n---\n\n".join(parts)

        # If over budget, drop observations from early steps
        if self._estimate_tokens(full) > max_tokens and self.plan:
            parts_compressed: list[str] = []
            step_list = [s for s in self.plan.steps if s.status in ("completed", "in_progress")]
            n = len(step_list)
            for i, step in enumerate(step_list):
                entries = self.get_entries_for_step(step.id)
                if not entries:
                    continue
                step_parts_c = [f"### Step {step.id}: {step.goal}"]
                for e in entries:
                    if i < n - 2:
                        # Early steps: notes only
                        step_parts_c.append(f"Round {e.round}: {e.self_note}")
                    else:
                        # Recent steps: full observation
                        step_parts_c.append(
                            f"**Round {e.round}** — Action: {e.action}({e.action_input})\n"
                            f"Note: {e.self_note}\n"
                            f"Observation:\n{e.observation}"
                        )
                parts_compressed.append("\n".join(step_parts_c))
            full = "\n\n---\n\n".join(parts_compressed)

        return full or "(no evidence gathered)"

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def get_all_sources(self) -> list[dict[str, Any]]:
        """Return deduplicated list of all sources with IDs."""
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        counter: dict[str, int] = {}
        for entry in self.entries:
            for src in entry.sources:
                key = f"{src.type}:{src.file or src.url or src.chunk_id}"
                if key not in seen:
                    seen.add(key)
                    prefix = src.type if src.type in ("rag", "web", "code") else "src"
                    counter[prefix] = counter.get(prefix, 0) + 1
                    source_id = f"{prefix}-{counter[prefix]}"
                    d = src.to_dict()
                    d["id"] = source_id
                    result.append(d)
        return result

    def format_sources_markdown(self) -> str:
        """Format sources as a Markdown references section."""
        sources = self.get_all_sources()
        if not sources:
            return ""
        lines = ["## References\n"]
        for s in sources:
            label = s.get("file") or s.get("url") or s.get("chunk_id") or "unknown"
            lines.append(f"- **[{s['id']}]** {label}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, output_dir: str) -> str:
        path = os.path.join(output_dir, self.FILENAME)
        data = {
            "version": self.VERSION,
            "question": self.question,
            "plan": self.plan.to_dict() if self.plan else None,
            "entries": [e.to_dict() for e in self.entries],
            "metadata": self.metadata,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load_or_create(cls, output_dir: str, question: str) -> Scratchpad:
        path = os.path.join(output_dir, cls.FILENAME)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            pad = cls(question=data.get("question", question))
            if data.get("plan"):
                pad.plan = Plan.from_dict(data["plan"])
            pad.entries = [Entry.from_dict(e) for e in data.get("entries", [])]
            pad.metadata = data.get("metadata", pad.metadata)
            return pad
        return cls(question=question)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_plan(self) -> str:
        if self.plan is None:
            return "(no plan yet)"
        lines = [f"Analysis: {self.plan.analysis}"]
        for s in self.plan.steps:
            status_mark = {"completed": "[x]", "in_progress": "[>]", "skipped": "[-]"}.get(
                s.status, "[ ]"
            )
            lines.append(f"  {status_mark} {s.id}: {s.goal}")
        return "\n".join(lines)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count. Uses tiktoken if available, else chars/4."""
        if _TIKTOKEN_AVAILABLE:
            try:
                enc = tiktoken.get_encoding("cl100k_base")
                return len(enc.encode(text))
            except Exception:
                pass
        return len(text) // 4
