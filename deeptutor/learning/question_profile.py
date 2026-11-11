"""What kind of question the learner keeps asking, across their history.

The tutor already knows *who* the learner is (``learner_profile``) and which
teaching moves helped (``teaching_observations``). It did not know *what kind
of thing they keep asking* — and that is the signal that decides how deep to
go and what to lead with. A learner whose history is mostly "what does this
word mean" needs definitions first; one asking "why" needs mechanism; one
asking "how do I" needs a concrete example; one asking "which one" needs a
decision frame; one asking "why does this fail" is already applying and should
be moved to practice.

Classification is deliberately local and deterministic: it reads the learner's
own messages and matches a small keyword set. That keeps it free, instant and
inspectable, and it never needs the model to remember to record anything.
"""

from __future__ import annotations

import time
from typing import Any

#: The kinds a learner question can carry. A question may carry more than one.
QUESTION_KINDS: tuple[str, ...] = (
    "definition",
    "mechanism",
    "procedure",
    "comparison",
    "debugging",
    "application",
    "confusion",
)

#: Order matters for ``recent`` labels: the most diagnostic kind wins.
_KIND_ORDER: tuple[str, ...] = (
    "confusion",
    "debugging",
    "comparison",
    "definition",
    "mechanism",
    "procedure",
    "application",
)

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "confusion": (
        "没听懂",
        "听不懂",
        "没懂",
        "不明白",
        "不清楚",
        "再讲一遍",
        "换个说法",
        "太抽象",
        "太难",
        "太浅",
        "没看明白",
        "confused",
        "don't understand",
        "did not understand",
        "didn't understand",
        "explain again",
        "too abstract",
        "too hard",
        "too shallow",
        "lost me",
    ),
    "debugging": (
        "报错",
        "出错",
        "失败",
        "不工作",
        "跑不起来",
        "异常",
        "崩溃",
        "为什么错",
        "哪里错",
        "边界情况",
        "error",
        "fails",
        "failed",
        "not working",
        "doesn't work",
        "does not work",
        "bug",
        "crash",
        "exception",
        "edge case",
    ),
    "comparison": (
        "区别",
        "差异",
        "对比",
        "取舍",
        "哪个好",
        "选哪个",
        "什么时候用哪个",
        "优劣",
        "vs",
        "versus",
        "difference",
        "compare",
        "trade-off",
        "tradeoff",
        "pros and cons",
        "which one",
    ),
    "definition": (
        "什么是",
        "是什么意思",
        "什么叫",
        "定义",
        "术语",
        "指的是",
        "含义",
        "what is",
        "what's",
        "what does",
        "meaning of",
        "definition",
        "term",
    ),
    "mechanism": (
        "为什么",
        "原理",
        "机制",
        "怎么运作",
        "如何运作",
        "底层",
        "内部怎么",
        "why",
        "how does",
        "how do",
        "under the hood",
        "mechanism",
        "internally",
    ),
    "procedure": (
        "怎么做",
        "怎么实现",
        "如何实现",
        "步骤",
        "怎么搭",
        "怎么用",
        "如何做",
        "how do i",
        "how to",
        "steps",
        "implement",
        "set up",
    ),
    "application": (
        "用在哪",
        "什么时候用",
        "实际",
        "场景",
        "举个例子",
        "举例",
        "例子",
        "应用",
        "use case",
        "example",
        "for example",
        "when should",
        "real world",
        "scenario",
    ),
}

_MAX_EXCERPT = 120
_CACHE_TTL_SECONDS = 20.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def classify_question(text: str) -> list[str]:
    """The kinds one learner message carries, most diagnostic first."""
    value = str(text or "").strip().lower()
    if len(value) < 2:
        return []
    matched = {
        kind
        for kind, words in _KEYWORDS.items()
        if any(word in value for word in words)
    }
    return [kind for kind in _KIND_ORDER if kind in matched]


def _excerpt(text: str) -> str:
    flat = " ".join(str(text or "").split())
    return flat[:_MAX_EXCERPT]


def _signals(counts: dict[str, int], total: int) -> list[str]:
    """The adjustments this history argues for, strongest evidence first."""
    if total < 3:
        return []
    signals: list[str] = []

    def share(kind: str) -> float:
        return counts.get(kind, 0) / total if total else 0.0

    if share("confusion") >= 0.2:
        signals.append("change_approach")
    if share("definition") >= 0.25:
        signals.append("define_terms")
    if share("mechanism") >= 0.25:
        signals.append("deepen_mechanism")
    if share("procedure") + share("application") >= 0.25:
        signals.append("more_examples")
    if share("comparison") >= 0.2:
        signals.append("decision_framework")
    if share("debugging") >= 0.2:
        signals.append("move_to_practice")
    return signals


def summarize_questions(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate classified learner messages into the profile the tutor reads."""
    counts = {kind: 0 for kind in QUESTION_KINDS}
    recent: list[dict[str, Any]] = []
    total = 0
    for sample in samples:
        kinds = [kind for kind in sample.get("kinds", []) if kind in counts]
        if not kinds:
            continue
        total += 1
        for kind in kinds:
            counts[kind] += 1
        recent.append(
            {
                "kind": kinds[0],
                "kinds": kinds,
                "text": sample.get("text", ""),
                **(
                    {"knowledge_point_id": sample["knowledge_point_id"]}
                    if sample.get("knowledge_point_id")
                    else {}
                ),
            }
        )
    counts = {kind: value for kind, value in counts.items() if value}
    dominant = sorted(counts, key=lambda kind: counts[kind], reverse=True)[:2]
    return {
        "total": total,
        "counts": counts,
        "dominant": dominant,
        "signals": _signals(counts, total),
        "recent": recent[-5:][::-1],
    }


async def question_profile_for_path(
    path_id: str,
    *,
    limit_sessions: int = 10,
) -> dict[str, Any] | None:
    """Classify this path's learner questions, newest sessions first.

    Bounded on purpose: only the most recently touched conversations are read,
    and the result is cached briefly so several tool calls in one turn share
    one pass over the transcript.
    """
    path_id = str(path_id or "").strip()
    if not path_id:
        return None
    cached = _cache.get(path_id)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    from deeptutor.learning.storage import LearningStore
    from deeptutor.services.session import get_session_store

    try:
        session_ids = LearningStore().list_session_ids(path_id)[:limit_sessions]
    except Exception:
        session_ids = []
    if not session_ids:
        return None

    store = get_session_store()
    reader = getattr(store, "list_bubble_texts", None)
    samples: list[dict[str, Any]] = []
    for session_id in session_ids:
        try:
            rows = (
                await reader(session_id)
                if callable(reader)
                else await store.get_messages(session_id)
            )
        except Exception:
            continue
        for row in rows or []:
            if not isinstance(row, dict) or str(row.get("role") or "") != "user":
                continue
            kinds = classify_question(str(row.get("content") or ""))
            if not kinds:
                continue
            samples.append(
                {
                    "kinds": kinds,
                    "text": _excerpt(str(row.get("content") or "")),
                }
            )

    profile = summarize_questions(samples)
    _cache[path_id] = (now, profile)
    return profile


def invalidate_question_profile(path_id: str = "") -> None:
    """Drop the cache for one path, or all of them."""
    if path_id:
        _cache.pop(str(path_id).strip(), None)
    else:
        _cache.clear()


__all__ = [
    "QUESTION_KINDS",
    "classify_question",
    "summarize_questions",
    "question_profile_for_path",
    "invalidate_question_profile",
]
