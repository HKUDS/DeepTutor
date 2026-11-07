from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


@dataclass
class Problem:
    id: str
    question: str
    ground_truth: str
    benchmark: str
    system_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    problem: Problem
    model_output: str
    extracted_answer: str | None
    correct: bool
    elapsed_sec: float
    score: float = 1.0
    confidence: int = 100
    judge_reasoning: str = ""
    error: str | None = None


@dataclass
class BenchmarkReport:
    benchmark: str
    mode: str
    model: str
    timestamp: str
    total: int = 0
    correct: int = 0
    errors: int = 0
    elapsed_sec: float = 0.0
    results: list[EvalResult] = field(default_factory=list)
    breakdowns: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total > 0 else 0.0

    @property
    def accuracy_pct(self) -> float:
        return round(100.0 * self.accuracy, 2)

    @property
    def confidence_interval(self) -> float:
        if self.total == 0:
            return 0.0
        acc = self.accuracy_pct
        return round(1.96 * math.sqrt(acc * (100 - acc) / self.total), 2)

    def add(self, r: EvalResult, breakdown_keys: list[str]) -> None:
        self.results.append(r)
        self.total += 1

        if r.error:
            self.errors += 1
            return

        if r.correct:
            self.correct += 1

        for key in breakdown_keys:
            if key not in r.problem.metadata:
                continue
            bucket_name = f"by_{key}"
            bucket_value = str(r.problem.metadata.get(key))
            bucket = self.breakdowns.setdefault(bucket_name, {})
            stats = bucket.setdefault(bucket_value, {"total": 0, "correct": 0})
            stats["total"] += 1
            if r.correct:
                stats["correct"] += 1

    def summary_lines(self) -> list[str]:
        lines = [
            "=" * 70,
            f"{self.benchmark.upper()} Benchmark Report — {self.mode} mode",
            f"Model: {self.model}",
            f"Time:  {self.timestamp}",
            "=" * 70,
            f"Overall: {self.correct}/{self.total} = {self.accuracy_pct}% "
            f"+/- {self.confidence_interval}% (errors={self.errors})",
            f"Wall time: {self.elapsed_sec:.1f}s",
        ]
        for bucket_name in sorted(self.breakdowns):
            lines.append("")
            lines.append(f"--- {bucket_name} ---")
            for k in sorted(self.breakdowns[bucket_name]):
                s = self.breakdowns[bucket_name][k]
                acc = s["correct"] / s["total"] if s["total"] else 0.0
                lines.append(f"  {k:30s} {s['correct']:4d}/{s['total']:4d} = {acc:.3f}")
        lines.append("=" * 70)
        return lines

    def to_dict(self) -> dict[str, Any]:
        breakdowns: dict[str, dict[str, Any]] = {}
        for bucket_name, bucket in self.breakdowns.items():
            breakdowns[bucket_name] = {}
            for k, s in bucket.items():
                acc = s["correct"] / s["total"] if s["total"] else 0.0
                breakdowns[bucket_name][k] = {
                    **s,
                    "accuracy": round(acc, 4),
                }

        return {
            "benchmark": self.benchmark,
            "mode": self.mode,
            "model": self.model,
            "timestamp": self.timestamp,
            "overall": {
                "total": self.total,
                "correct": self.correct,
                "accuracy": round(self.accuracy, 4),
                "accuracy_pct": self.accuracy_pct,
                "confidence_interval": self.confidence_interval,
                "errors": self.errors,
                "elapsed_sec": round(self.elapsed_sec, 2),
            },
            "breakdowns": breakdowns,
            "results": [
                {
                    "id": r.problem.id,
                    "question": r.problem.question[:300],
                    "ground_truth": r.problem.ground_truth,
                    "extracted_answer": r.extracted_answer,
                    "correct": r.correct,
                    "score": r.score,
                    "confidence": r.confidence,
                    "judge_reasoning": r.judge_reasoning[:400],
                    "elapsed_sec": round(r.elapsed_sec, 3),
                    "error": r.error,
                    "metadata": r.problem.metadata,
                }
                for r in self.results
            ],
        }
