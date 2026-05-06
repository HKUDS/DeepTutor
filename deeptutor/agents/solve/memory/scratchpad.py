"""
Scratchpad - Unified memory for the Plan -> ReAct -> Write pipeline.

Replaces InvestigateMemory + SolveMemory + CitationMemory with a single
linear data structure that tracks the plan, all ReAct iterations, and
sources for citation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
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
        filtered = {
            k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "sources"
        }
        return cls(sources=sources, **filtered)


# ---------------------------------------------------------------------------
# Scratchpad
# ---------------------------------------------------------------------------


def _normalize_url_for_dedup(url: str) -> str:
    """Normalize a URL to its paper identity for deduplication.

    Strips version suffixes (v1, v2, v3), file extensions (abs/html/pdf),
    and www/www2 host prefixes so all variants of the same paper collapse.
    """
    import re
    from urllib.parse import urlparse, parse_qs

    if not url:
        return ""
    try:
        # Extract arXiv paper ID if present anywhere in the URL
        # This handles arxiv.org, alphaxiv.org, emergentmind, huggingface, etc.
        paper_id_match = re.search(r"(\d{4}\.\d{4,})", url)
        if paper_id_match:
            return f"arxiv:{paper_id_match.group(1)}"

        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.").removeprefix("www2.")
        path = parsed.path.strip("/")

        # openreview.net: stable ID from query param
        if "openreview.net" in host:
            qs = parse_qs(parsed.query)
            fid = qs.get("id", [""])[0]
            return f"openreview:{fid}"

        # Generic: host + last path segment
        seg = path.split("/")[-1] if path else ""
        return f"{host}:{seg}"
    except Exception:
        return url


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
        completed_ids = []
        if self.plan:
            completed_ids = [s.id for s in self.plan.steps if s.status == "completed"]
            for sid in completed_ids:
                entries = self.get_entries_for_step(sid)
                step_obj = next((s for s in self.plan.steps if s.id == sid), None)
                goal_text = step_obj.goal if step_obj else sid
                notes = [e.self_note for e in entries if e.self_note]
                if notes:
                    previous_parts.append(f"[{sid}] {goal_text}: {' '.join(notes)}")

        previous_knowledge = (
            "\n".join(previous_parts) if previous_parts else "(no previous steps completed)"
        )

        # Token budget check – if over budget, aggressively compress previous_knowledge
        total = self._estimate_tokens(
            plan_text + current_step_text + step_history + previous_knowledge
        )
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
        """Return deduplicated list of all sources with IDs.

        Each distinct (type, file, url, chunk_id) tuple is a unique source.
        For RAG sources this means different queries produce separate citations
        even when they target the same knowledge base.
        """
        return self._build_sources_list()

    @staticmethod
    def _normalize_paper_key(url: str) -> str:
        """Normalize a paper URL to its paper identity key for deduplication.

        Pattern-based approach — no domain allowlist required. Extracts identifiers
        wherever they appear in the URL (path, query, path segments).

        Groups all URL variants of the same paper (e.g. arxiv abs/html/pdf,
        openreview, semanticscholar) under one deduplication key.
        """
        from urllib.parse import urlparse
        import re

        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        path = parsed.path.rstrip("/")

        # --- arxiv: match 4-digit.4+digit[vN] pattern anywhere in path ---
        # Handles: /abs/2311.12424v2, /html/2311.12424v3, /pdf/2311.12424
        # The v suffix may or may not be preceded by a dot
        for p in path.split("/"):
            m = re.match(r"(\d{4}\.\d{4,})(?:v\d+)?$", p)
            if m:
                return f"arxiv:{m.group(1)}"

        # --- openreview.net: id from query param (stable across /pdf and /forum) ---
        if host == "openreview.net":
            m = re.search(r"id=([^&\s]+)", parsed.query)
            if m:
                return f"openreview:{m.group(1)}"
            return f"openreview:{path}"

        # --- semanticscholar: CorpusID:123456789 ---
        if "corpusid" in host.lower() or "semanticscholar" in host.lower():
            if "CorpusID" in path:
                return f"ss:{path.split(':')[-1]}"

        # --- ICLR / NeurIPS proceedings: hash/abcdef123 ---
        if host in ("proceedings.iclr.cc", "proceedings.neurips.cc"):
            m = re.search(r"hash/([a-f0-9]+)", path)
            if m:
                return f"iclr:{m.group(1)}"

        # --- Catch-all: use host+path as the key ---
        # This handles emergentmind, deeplearn.org, researchgate, etc. where
        # each paper gets its own path but we don't extract a formal ID
        return f"{host}{path}"

    def _build_sources_list(self) -> list[dict[str, Any]]:
        """Build deduplicated list of all sources with IDs.

        Uses RapidFuzz token_set_ratio on source titles for fuzzy deduplication
        of web sources, so that URL variants of the same paper (different hosts,
        different URL formats) are correctly collapsed into one entry.
        """
        from rapidfuzz import fuzz

        seen: list[dict[str, Any]] = []  # list of {"primary": src_dict, "alts": set}
        result: list[dict[str, Any]] = []
        counter: dict[str, int] = {}
        for entry in self.entries:
            for src in entry.sources:
                src_dict = src.to_dict()
                src_url = src_dict.get("url") or ""
                norm_url = _normalize_url_for_dedup(src_url)
                matched = False
                for existing in seen:
                    primary = existing["primary"]
                    if primary["type"] != src.type:
                        continue
                    # Exact normalized URL match → same paper regardless of version/host
                    primary_norm = _normalize_url_for_dedup(primary.get("url") or "")
                    if norm_url and primary_norm == norm_url:
                        if src_url:
                            existing["alts"].add(src_url)
                        matched = True
                        break
                    # Same type — check title similarity (catches same paper, different hosts)
                    if src.file and primary.get("file"):
                        ratio = fuzz.token_set_ratio(src.file, primary["file"])
                        if ratio >= 80:
                            if src_url:
                                existing["alts"].add(src_url)
                            matched = True
                            break
                if not matched:
                    seen.append({"primary": src_dict, "alts": set()})

        for data in seen:
            src_dict = data["primary"]
            prefix = src_dict["type"] if src_dict["type"] in ("rag", "web", "code") else "src"
            counter[prefix] = counter.get(prefix, 0) + 1
            src_dict["id"] = f"{prefix}-{counter[prefix]}"
            if data["alts"]:
                src_dict["alternate_urls"] = sorted(data["alts"])
            result.append(src_dict)
        return result

    def remove_sources_by_url(self, urls: list[str]) -> int:
        """Remove Source objects from all entries matching any of the given URLs.

        Returns the number of Source objects removed.
        """
        url_set = set(urls)
        removed = 0
        for entry in self.entries:
            before = len(entry.sources)
            entry.sources = [s for s in entry.sources if s.url not in url_set]
            removed += before - len(entry.sources)
        return removed

    def format_sources_markdown(self) -> str:
        """Format sources as a Markdown references section with clickable URLs."""
        sources = self.get_all_sources()
        if not sources:
            return ""
        lines = ["## References\n"]
        for s in sources:
            label = self._source_label(s)
            url = s.get("url") or ""
            if url:
                lines.append(f"- **[{s['id']}]** [{label}]({url})")
            else:
                lines.append(f"- **[{s['id']}]** {label}")
        return "\n".join(lines)

    @staticmethod
    def _source_label(s: dict[str, Any]) -> str:
        """Build a human-readable label for a source entry.

        RAG sources use the query text as primary label with the knowledge-base
        name as qualifier, so different queries are visually distinguishable.
        """
        if s.get("type") == "rag" and s.get("chunk_id"):
            query_text = s["chunk_id"]
            kb = s.get("file")
            return f"{query_text} ({kb})" if kb else query_text
        return s.get("file") or s.get("url") or s.get("chunk_id") or "unknown"

    def find_source_id_by_url(self, url: str) -> str | None:
        """Find the assigned source ID for a given URL.

        Used by CriticAgent to map a visit_url result back to its source ID
        so invalid URLs can be marked and excluded from the final answer.
        """
        sources = self.get_all_sources()
        for s in sources:
            if s.get("url") == url:
                return s["id"]
        return None

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
