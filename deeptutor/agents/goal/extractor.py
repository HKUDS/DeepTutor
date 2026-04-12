"""Rule-based knowledge extraction for Goal mode."""

from __future__ import annotations

import json
from pathlib import Path
import re

from deeptutor.agents.goal.models import KnowledgeNodeDraft, WeightEvidence
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.config import PROJECT_ROOT


class KnowledgeExtractor:
    """Extract candidate knowledge nodes from an existing knowledge base."""

    def __init__(self, kb_base_dir: str | Path | None = None):
        base_dir = Path(kb_base_dir) if kb_base_dir is not None else PROJECT_ROOT / "data" / "knowledge_bases"
        self.manager = KnowledgeBaseManager(base_dir=str(base_dir))

    async def extract(
        self,
        kb_name: str,
        scope: dict | None = None,
    ) -> list[KnowledgeNodeDraft]:
        try:
            kb_dir = self.manager.get_knowledge_base_path(kb_name)
        except Exception:
            return self._fallback_drafts(scope or {}, kb_name)
        raw_dir = kb_dir / "raw"
        content_dir = kb_dir / "content_list"

        files = self._collect_source_files(raw_dir, content_dir)
        drafts: list[KnowledgeNodeDraft] = []
        for path in files:
            text = self._read_text(path)
            if not text.strip():
                continue
            drafts.extend(self._extract_from_text(path, text, scope or {}))
        deduped = self._dedupe(drafts)
        if deduped:
            return deduped
        return self._fallback_drafts(scope or {}, kb_name)

    def _collect_source_files(self, raw_dir: Path, content_dir: Path) -> list[Path]:
        files: list[Path] = []
        for directory in (content_dir, raw_dir):
            if not directory.exists():
                continue
            for path in directory.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json"}:
                    files.append(path)
        return sorted(files)

    def _read_text(self, path: Path) -> str:
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return json.dumps(data, ensure_ascii=False)
            except Exception:
                return ""
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="ignore")

    def _extract_from_text(
        self,
        path: Path,
        text: str,
        scope: dict,
    ) -> list[KnowledgeNodeDraft]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        selected_scope = set(scope.get("chapters") or []) | set(scope.get("topics") or [])
        excluded = set(scope.get("exclude_topics") or [])

        drafts: list[KnowledgeNodeDraft] = []
        for index, line in enumerate(lines):
            normalized = self._normalize_title(line)
            if not normalized or normalized in excluded:
                continue
            if selected_scope and normalized not in selected_scope and line not in selected_scope:
                if not self._looks_like_heading(line):
                    continue

            evidence = WeightEvidence(
                source=str(path.relative_to(path.parents[1])) if len(path.parents) > 1 else path.name,
                snippet=self._build_snippet(lines, index),
            )
            practice_freq = 0.0
            if re.search(r"真题|模拟|练习|题型|刷题|exam|mock|practice", line, re.IGNORECASE):
                practice_freq = 1.0
            elif re.search(r"例题|习题|训练", line, re.IGNORECASE):
                practice_freq = 0.6
            drafts.append(
                KnowledgeNodeDraft(
                    title=normalized,
                    aliases=[line] if line != normalized else [],
                    evidence=[evidence],
                    tags=self._build_tags(line),
                    estimated_minutes=30 if self._looks_like_heading(line) else 20,
                    doc_freq=1.0,
                    practice_freq=practice_freq,
                    heading_score=1.0 if self._looks_like_heading(line) else 0.5,
                )
            )

        if not drafts:
            fallback = " ".join(lines[:8]).strip()
            if fallback:
                drafts.append(
                    KnowledgeNodeDraft(
                        title=path.stem,
                        evidence=[WeightEvidence(source=path.name, snippet=fallback[:240])],
                        tags=["document"],
                    )
                )
        return drafts

    def _build_tags(self, line: str) -> list[str]:
        tags: list[str] = []
        if re.search(r"基础|basic|introduction", line, re.IGNORECASE):
            tags.append("foundation")
        if re.search(r"重点|核心|high[- ]yield", line, re.IGNORECASE):
            tags.append("high_yield")
        if re.search(r"真题|历年|模拟|exam|mock", line, re.IGNORECASE):
            tags.append("exam")
        return tags

    def _build_snippet(self, lines: list[str], index: int) -> str:
        window = lines[index : index + 3]
        return " ".join(window)[:240]

    def _normalize_title(self, line: str) -> str:
        value = re.sub(r"^\s*(#+|\d+[\.\)]|[-*])\s*", "", line).strip(" :：-")
        if len(value) < 2:
            return ""
        return value[:80]

    def _looks_like_heading(self, line: str) -> bool:
        return bool(re.match(r"^\s*(#+|\d+[\.\)]|第.+[章节])", line)) or len(line) <= 30

    def _dedupe(self, drafts: list[KnowledgeNodeDraft]) -> list[KnowledgeNodeDraft]:
        merged: dict[str, KnowledgeNodeDraft] = {}
        for draft in drafts:
            key = draft.title.lower()
            current = merged.get(key)
            if current is None:
                merged[key] = draft
                continue
            current.aliases = sorted(set(current.aliases + draft.aliases))
            current.tags = sorted(set(current.tags + draft.tags))
            current.evidence.extend(draft.evidence)
            current.doc_freq += draft.doc_freq
            current.heading_score = max(current.heading_score, draft.heading_score)
        return list(merged.values())

    def _fallback_drafts(self, scope: dict, kb_name: str) -> list[KnowledgeNodeDraft]:
        seeds = list(scope.get("chapters") or []) + list(scope.get("topics") or [])
        goal_statement = str(scope.get("goal_statement") or "").strip()
        goal_seeds = self._infer_goal_seeds(goal_statement)
        for seed in goal_seeds:
            if seed not in seeds:
                seeds.append(seed)
        if not seeds:
            seeds = [
                "Core concept review",
                "High-yield question type training",
                "Comprehensive review and self-check",
            ]
        drafts: list[KnowledgeNodeDraft] = []
        previous_title: str | None = None
        for index, seed in enumerate(seeds[:8], start=1):
            drafts.append(
                KnowledgeNodeDraft(
                    title=seed,
                    aliases=[],
                    evidence=[
                        WeightEvidence(
                            source=f"fallback:{kb_name}",
                            snippet="Knowledge base unavailable; using scaffolded goal plan.",
                        )
                    ],
                    tags=self._fallback_tags(seed, index),
                    estimated_minutes=30 + (index - 1) * 5,
                    doc_freq=max(0.2, 1.0 - (index - 1) * 0.1),
                    practice_freq=0.8 if re.search(r"past paper|question type|training|self-check|error", seed, re.IGNORECASE) else 0.3,
                    heading_score=0.6,
                    prerequisites=[previous_title] if previous_title else [],
                )
            )
            previous_title = seed
        return drafts

    def _infer_goal_seeds(self, goal_statement: str) -> list[str]:
        if not goal_statement:
            return []

        text = goal_statement.lower()
        seeds: list[str] = []

        # Domain priors: provide a concrete plan skeleton from common subject knowledge.
        if any(token in text for token in ("微积分", "calculus", "导数", "积分", "极限")):
            seeds.extend(
                [
                    "Limits and continuity",
                    "Derivatives and differentiation rules",
                    "Derivative applications (monotonicity and extrema)",
                    "Indefinite integrals and integration techniques",
                    "Definite integrals and geometric applications",
                    "Comprehensive review and self-check",
                ]
            )
        elif any(token in text for token in ("线代", "线性代数", "linear algebra", "矩阵", "特征值")):
            seeds.extend(
                [
                    "Matrices and linear systems",
                    "Vector spaces and linear dependence",
                    "Eigenvalues and eigenvectors",
                    "Orthogonalization and quadratic forms",
                    "Comprehensive question type training",
                ]
            )
        elif any(token in text for token in ("概率", "统计", "probability", "statistics")):
            seeds.extend(
                [
                    "Random variables and distributions",
                    "Expectation, variance, and common inequalities",
                    "Conditional probability and Bayes",
                    "Parameter estimation and hypothesis testing",
                    "Comprehensive question type training",
                ]
            )

        # Exam-aware enrichment for real past papers / mock questions.
        if any(token in text for token in ("真题", "历年", "模拟题", "试卷", "past paper", "mock")):
            seeds.extend(
                [
                    "High-yield past paper pattern breakdown",
                    "Error-bank retraining and variation practice",
                ]
            )

        # Generic extraction fallback from long goal text phrases.
        if not seeds:
            for chunk in re.split(r"[，,。；;、\n]+", goal_statement):
                value = chunk.strip()
                if 2 <= len(value) <= 24:
                    seeds.append(value)
                if len(seeds) >= 6:
                    break

        # De-duplicate while preserving order.
        deduped: list[str] = []
        for seed in seeds:
            if seed and seed not in deduped:
                deduped.append(seed)
        return deduped[:8]

    def _fallback_tags(self, seed: str, index: int) -> list[str]:
        tags = ["fallback"]
        if index == 1:
            tags.append("foundation")
        if re.search(r"真题|题型|训练|错题|自测", seed):
            tags.append("high_yield")
            tags.append("exam")
        return tags
