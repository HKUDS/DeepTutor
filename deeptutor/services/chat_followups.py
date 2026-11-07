"""Follow-up chips — the one-click adjustments offered under the latest answer.

Not the composer's "what you'll say next" hint (:mod:`deeptutor.services.chat_hints`,
which predicts one free line as placeholder text). These are a small, fixed set
of *intents*: ways a learner can react to what was just said without having to
articulate it. The complaint this answers is concrete — the answer was too
shallow or too deep, too term-heavy or example-light, drifted off the goal, or
never closed the loop — and a learner who cannot name the problem can still
tap the one that fits.

Each chip carries the message it sends as the learner's own turn, so a tap is
a normal request: "say it more simply", "explain the terms first", "add cause
and fix". Selection is heuristic and cheap — a few signals read off the last
answer — so it costs no model call and adds no latency. The set is a catalogue
with stable ids; the client renders them in order.
"""

from __future__ import annotations

import re
from typing import Any

from deeptutor.services.chat_hints import _collect, _response_language
from deeptutor.services.prompt.language import is_chinese as _is_zh

#: How many chips one answer offers. A few, not a menu.
_MAX_SUGGESTIONS = 6

# (id, zh label, zh prompt, en label, en prompt)
_CATALOGUE: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "simpler",
        "用更简单的话",
        "用更简单的说法重讲，分层次、降低密度，但保留关键结论。",
        "More simply",
        "Re-explain more simply: layer it, lower the density, but keep the key conclusions.",
    ),
    (
        "deeper",
        "再深入讲机制",
        "再深入一点：讲清背后的机制，以及为什么这样做。",
        "Go deeper",
        "Go deeper: explain the mechanism behind it and why it works this way.",
    ),
    (
        "summarize",
        "一句话说清是什么",
        "先用一句话说清：这是什么、解决什么问题、属于哪一类问题。",
        "What is this, in one line",
        "Start with one line: what this is, what problem it solves, and what class of problem it belongs to.",
    ),
    (
        "closure",
        "补成因和修复",
        "把闭环补齐：问题 → 成因 → 解决方案 → 如何验证；有失败场景就逐个给出成因和修复。",
        "Add cause and fix",
        "Close the loop: problem, cause, fix, and how to verify; give cause and fix for each failure case.",
    ),
    (
        "comments",
        "逐段加注释",
        "给代码逐段加注释，标清每块干什么、对应哪一步。",
        "Annotate the code",
        "Comment the code section by section: what each part does and which step it maps to.",
    ),
    (
        "example",
        "举个最小例子",
        "给一个具体、最小、能看懂的例子。",
        "A minimal example",
        "Give one concrete, minimal example that is easy to follow.",
    ),
    (
        "code",
        "给可跑的最小代码",
        "先按步骤讲清功能，再给可运行的最小代码骨架，然后填实现，最后合并并注释。",
        "Minimal runnable code",
        "Explain the steps, then a minimal runnable skeleton, then the implementation, merged and commented.",
    ),
    (
        "terms",
        "先解释里面的名词",
        "先逐个解释里面的名词/概念，给出定义和直觉，再继续讲。",
        "Define the terms",
        "First define each term/concept with its intuition, then continue.",
    ),
    (
        "generalize",
        "这类问题还有哪些",
        "概括成一类问题：通用模式是什么，还有哪些同类情形。",
        "Generalize",
        "Generalize: what is the common pattern, and what other cases belong to this class.",
    ),
    (
        "card",
        "做成可背的卡片",
        "把要点压成可背诵的卡片：一两句话 + 口诀 + 一道自测题。",
        "Make a revision card",
        "Compress it into a revision card: a line or two, a mnemonic, and one self-test question.",
    ),
    (
        "notes",
        "用我的话整理成笔记",
        "用更口语、像我自己的话，把重点整理成一份笔记。",
        "Rewrite as my notes",
        "Rewrite the key points as notes in plain, first-person language.",
    ),
    (
        "quiz",
        "出几道题考我",
        "针对刚才的内容出 3 道题考我，并在我回答后点评。",
        "Quiz me",
        "Ask me three questions on this and give feedback after I answer.",
    ),
)

_FAILURE_RE = re.compile(r"失败|报错|异常|错误|问题|坑|bug|error|fail|exception|crash", re.IGNORECASE)
_FIX_RE = re.compile(r"修复|解决|成因|原因|如何改|怎么改|fix|solve|cause|resolution", re.IGNORECASE)
_EXAMPLE_RE = re.compile(r"例如|比如|举例|示例|用例|for example|e\.g\.|example", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"总结|一句话|简言之|综上|要点|in short|to summarize|tl;?dr|summary|takeaway", re.IGNORECASE)
_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{3,}")
_CODE_COMMENT_RE = re.compile(r"^\s*(#|//|/\*|\*|--|%|<!--)")
_FENCE_RE = re.compile(r"^```")


def _last_assistant(material: Any) -> str:
    for role, content in reversed(getattr(material, "transcript", ())):
        if role == "assistant":
            return content
    return ""


def _code_has_comments(text: str) -> bool:
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence and _CODE_COMMENT_RE.match(line):
            return True
    return False


def _select(material: Any) -> list[str]:
    """Ordered intent ids for this answer — most useful first."""
    answer = _last_assistant(material)
    has_code = "```" in answer
    failure_without_fix = bool(_FAILURE_RE.search(answer)) and not _FIX_RE.search(answer)
    has_example = bool(_EXAMPLE_RE.search(answer))
    has_summary = bool(_SUMMARY_RE.search(answer))
    is_long = len(answer) > 1200
    latin_terms = len(set(_TERM_RE.findall(answer))) >= 3

    chosen: list[str] = ["simpler", "deeper"]
    if failure_without_fix:
        chosen.append("closure")
    if has_code and not _code_has_comments(answer):
        chosen.append("comments")
    if not has_example:
        chosen.append("example")
    if not has_code and is_long:
        chosen.append("code")
    if latin_terms:
        chosen.append("terms")
    if not has_summary:
        chosen.append("summarize")
    chosen.extend(["generalize", "card", "quiz", "notes"])

    seen: set[str] = set()
    ordered: list[str] = []
    for intent_id in chosen:
        if intent_id not in seen:
            seen.add(intent_id)
            ordered.append(intent_id)
    return ordered[:_MAX_SUGGESTIONS]


def _payload(intent_id: str, zh: bool) -> dict[str, str]:
    row = next((item for item in _CATALOGUE if item[0] == intent_id), None)
    if row is None:
        return {"id": intent_id, "label": intent_id, "prompt": intent_id}
    _, zh_label, zh_prompt, en_label, en_prompt = row
    return {
        "id": intent_id,
        "label": zh_label if zh else en_label,
        "prompt": zh_prompt if zh else en_prompt,
    }


async def get_followups(session_id: str) -> dict[str, Any]:
    """Ordered chips for the latest turn, or an empty list when there is none."""
    material = await _collect(session_id)
    if not material or not _last_assistant(material):
        return {"suggestions": []}
    zh = _is_zh(_response_language())
    return {"suggestions": [_payload(intent_id, zh) for intent_id in _select(material)]}


__all__ = ["get_followups"]
