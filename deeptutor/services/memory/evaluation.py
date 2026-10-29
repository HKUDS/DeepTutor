"""Evaluation-only history/L3 snapshot comparison; never opens active user memory.

Snapshots are supplied artifacts, not outputs of a consolidation run. The native
MemoryStore read path is exercised in temporary storage for each case. Readers
and token counters are injected so offline tests need no provider or tokenizer
download. Gold answers are kept outside adapter/reader inputs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
from typing import Any

from deeptutor.services.memory.paths import L3_SLOTS, memory_path_service_override
from deeptutor.services.memory.store import MemoryStore
from deeptutor.services.path_service import PathService


@dataclass(frozen=True)
class HistoryItem:
    identifier: str
    timestamp: str
    text: str


@dataclass(frozen=True)
class CaseInput:
    query: str
    history: tuple[HistoryItem, ...]
    l3_snapshot: tuple[tuple[str, str], ...]
    question_time: str = ""
    memory_as_of: str = ""


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    input: CaseInput
    answers: tuple[str, ...]
    evidence_ids: frozenset[str]


@dataclass(frozen=True)
class Evidence:
    identifier: str
    text: str


@dataclass(frozen=True)
class AdapterResult:
    evidence: tuple[Evidence, ...]
    original_source_ids: bool = False


@dataclass(frozen=True)
class ReaderResult:
    answer: str
    usage: Mapping[str, Any] | None = None


Adapter = Callable[[CaseInput], Awaitable[AdapterResult]]
Reader = Callable[[str, str], Awaitable[ReaderResult]]
TokenCounter = Callable[[str], int]


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone")
    return parsed


def load_cases(path: Path) -> tuple[EvalCase, ...]:
    """Load/validate JSONL, including chronology and pre-question gold visibility."""
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            case_id, query, category = (data[key] for key in ("case_id", "query", "category"))
            if not all(isinstance(x, str) and x.strip() for x in (case_id, query, category)):
                raise ValueError("Case ID, query and category must be nonempty strings")
            if case_id in seen:
                raise ValueError("Duplicate case ID")
            if not isinstance(data["history"], list):
                raise ValueError("History must be a list")
            history = tuple(
                HistoryItem(item["id"], item["timestamp"], item["text"]) for item in data["history"]
            )
            if not all(
                isinstance(x, str) and x.strip()
                for item in history
                for x in (item.identifier, item.timestamp, item.text)
            ):
                raise ValueError("History fields must be nonempty strings")
            dates = [_timestamp(item.timestamp) for item in history]
            if dates != sorted(dates):
                raise ValueError("History must be chronological")
            if len({item.identifier for item in history}) != len(history):
                raise ValueError("Duplicate history ID")
            cutoff = _timestamp(data["question_time"])
            snapshot_time = _timestamp(data["memory_as_of"])
            if snapshot_time > cutoff:
                raise ValueError("Memory snapshot is newer than the question")
            visible = tuple(
                item for item, date in zip(history, dates, strict=True) if date <= cutoff
            )
            gold = data["evidence_ids"]
            if not isinstance(gold, list) or not all(isinstance(x, str) for x in gold):
                raise ValueError("evidence_ids must be a string list")
            if not set(gold).issubset(item.identifier for item in visible):
                raise ValueError("Gold evidence must exist before question_time")
            answerable, expected = data["answerable"], data["expected_answer"]
            aliases = data.get("answer_aliases", [])
            if not isinstance(answerable, bool) or not isinstance(expected, str):
                raise ValueError("Invalid answerability/expected answer")
            if not isinstance(aliases, list) or not all(
                isinstance(x, str) and x.strip() for x in aliases
            ):
                raise ValueError("answer_aliases must contain nonempty strings")
            if answerable and (not expected.strip() or not gold):
                raise ValueError("Answerable cases need an answer and evidence")
            if not answerable and (expected or gold or aliases):
                raise ValueError("Unanswerable cases must not supply answers/evidence/aliases")
            snapshot = data["l3_snapshot"]
            if not isinstance(snapshot, dict) or not all(
                key in L3_SLOTS and isinstance(value, str) for key, value in snapshot.items()
            ):
                raise ValueError("l3_snapshot must map known L3 slots to Markdown strings")
            cases.append(
                EvalCase(
                    case_id,
                    category,
                    CaseInput(
                        query,
                        visible,
                        tuple(snapshot.items()),
                        data["question_time"],
                        data["memory_as_of"],
                    ),
                    tuple([expected, *aliases]) if answerable else ("UNKNOWN",),
                    frozenset(gold),
                )
            )
            seen.add(case_id)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"{path.name}:{number}: {exc}") from exc
    if not cases:
        raise ValueError("Dataset must contain at least one case")
    return tuple(cases)


async def raw_recent(context: CaseInput) -> AdapterResult:
    return AdapterResult(
        tuple(
            Evidence(item.identifier, f"{item.timestamp} {item.text}")
            for item in reversed(context.history)
        ),
        True,
    )


def _words(text: str) -> list[str]:
    # Retain common operators so e.g. -2 cannot exactly match +2 or 2.
    return re.findall(r"\w+|[-+*/=<>^≤≥]", text.casefold().replace("−", "-"))


async def lexical_top2(context: CaseInput) -> AdapterResult:
    """Diagnostic ablation, not a dense retrieval/reranking baseline."""
    query = Counter(_words(context.query))
    ranked = sorted(
        enumerate(context.history),
        key=lambda pair: (sum((Counter(_words(pair[1].text)) & query).values()), pair[0]),
        reverse=True,
    )
    return AdapterResult(
        tuple(Evidence(item.identifier, f"{item.timestamp} {item.text}") for _, item in ranked[:2]),
        True,
    )


async def memory_snapshot(context: CaseInput) -> AdapterResult:
    """Restore only supplied L3 artifacts, read via the native facade, then clean up."""
    with TemporaryDirectory(prefix="deeptutor-memory-eval-") as directory:
        service = PathService(workspace_root=Path(directory))
        with memory_path_service_override(service):
            store = MemoryStore()
            for slot, text in context.l3_snapshot:
                await store.overwrite_doc("L3", slot, text)
            # Avoid treating the user-facing no-memory sentinel as evidence.
            if not any(text.strip() for _, text in context.l3_snapshot):
                return AdapterResult(())
            text = store.read_l3_concat()
    # One native tool response is one indivisible evidence span. Do not claim
    # original-source recall from the presence of references in a memory artifact.
    return AdapterResult((Evidence("l3", text),))


def pack_evidence(
    items: tuple[Evidence, ...], budget: int, count_tokens: TokenCounter
) -> tuple[str, list[str]]:
    if budget < 1:
        raise ValueError("Token budget must be positive")
    text, selected = "", []
    for item in items:
        candidate = text + f"[{item.identifier}] {item.text}\n"
        if count_tokens(candidate) <= budget:
            text = candidate
            selected.append(item.identifier)
    return text, selected


def score_answer(answer: str, expected: tuple[str, ...]) -> tuple[bool, float]:
    """Normalized exact match over declared aliases, plus bag-of-word token F1.

    F1 is partial lexical overlap, not semantic correctness. No substring match
    that would accept 'not Python' as 'Python'. Missing answers are failures.
    """
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Reader returned no answer")
    words = _words(answer)
    exact, scores = False, []
    for alias in expected:
        gold = _words(alias)
        exact |= words == gold
        overlap = sum((Counter(words) & Counter(gold)).values())
        scores.append(2 * overlap / (len(words) + len(gold)) if words or gold else 1.0)
    return exact, max(scores, default=0.0)


async def evaluate(
    cases: tuple[EvalCase, ...],
    *,
    count_tokens: TokenCounter,
    tokenizer: str,
    budget: int = 512,
    reader: Reader | None = None,
    adapters: Mapping[str, Adapter] | None = None,
) -> dict[str, Any]:
    if not cases or budget < 1:
        raise ValueError("A nonempty dataset and positive token budget are required")
    selected_adapters = (
        dict(adapters)
        if adapters is not None
        else {
            "raw_recent": raw_recent,
            "lexical_top2": lexical_top2,
            "native_l3_snapshot": memory_snapshot,
        }
    )
    rows: list[dict[str, Any]] = []
    for case in cases:
        for name, adapter in selected_adapters.items():
            started = time.perf_counter()
            row: dict[str, Any] = {
                "case_id": case.case_id,
                "category": case.category,
                "question_time": case.input.question_time,
                "memory_as_of": case.input.memory_as_of,
                "adapter": name,
                "error": None,
                "exact_match": None,
                "token_f1": None,
                "source_id_recall": None,
            }
            try:
                result = await adapter(case.input)
                context, ids = pack_evidence(result.evidence, budget, count_tokens)
                row.update(
                    offered_ids=[item.identifier for item in result.evidence],
                    omitted_ids=[
                        item.identifier for item in result.evidence if item.identifier not in ids
                    ],
                    evidence_context=context,
                    selected_ids=ids,
                    evidence_tokens=count_tokens(context),
                    preparation_seconds=time.perf_counter() - started,
                )
                if result.original_source_ids and case.evidence_ids:
                    row["source_id_recall"] = len(set(ids) & case.evidence_ids) / len(
                        case.evidence_ids
                    )
                if reader is not None:
                    reading = time.perf_counter()
                    answer = await reader(context, case.input.query)
                    row.update(
                        answer=answer.answer,
                        usage=dict(answer.usage or {}),
                        reader_seconds=time.perf_counter() - reading,
                    )
                    exact, f1 = score_answer(answer.answer, case.answers)
                    row.update(exact_match=exact, token_f1=f1)
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            row["seconds"] = time.perf_counter() - started
            rows.append(row)
    summary = {}
    for name in selected_adapters:
        selected = [row for row in rows if row["adapter"] == name]
        scored = [row for row in selected if row["exact_match"] is not None and not row["error"]]
        correct = sum(bool(row["exact_match"]) for row in scored)
        summary[name] = {
            "total": len(selected),
            "failed": sum(bool(row["error"]) for row in selected),
            "scored": len(scored),
            "correct": correct,
            "exact_match_scored": correct / len(scored) if scored else None,
            "exact_match_all_cases": correct / len(selected) if scored else None,
        }
    return {
        "tokenizer": tokenizer,
        "evidence_token_budget": budget,
        "budget_excludes": "question, system instructions and output tokens",
        "reader_executed": reader is not None,
        "consolidation_executed": False,
        "memory_source": "supplied L3 snapshots; not generated by this evaluator",
        "summary": summary,
        "rows": rows,
    }
