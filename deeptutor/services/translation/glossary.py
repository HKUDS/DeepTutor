"""Terminology extraction and translation prompt guardrails."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import json
import re
from typing import Any

_CODE_AND_MATH = re.compile(
    r"(?s)(```.*?```|~~~.*?~~~|`[^`\n]+`|\$\$.*?\$\$|\$[^$\n]+\$)", re.MULTILINE
)
_API_TOKEN = re.compile(
    r"`([^`\n]{2,120})`|\b([A-Za-z][A-Za-z0-9]*(?:[._][A-Za-z0-9]+)+(?:\(\))?)\b"
)
_PROPER_NOUN = re.compile(r"\b[A-Z][a-z]{2,}(?:[ -][A-Z][a-z]{2,}){0,4}\b")
_CAMEL_NAME = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
_ENGLISH_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "but",
    "if",
    "no",
    "not",
    "one",
    "two",
    "about",
    "after",
    "again",
    "against",
    "before",
    "being",
    "below",
    "chapter",
    "every",
    "first",
    "great",
    "having",
    "their",
    "there",
    "these",
    "those",
    "through",
    "under",
    "until",
    "where",
    "which",
    "while",
    "whose",
}


def _clean_text(text: str) -> str:
    return _CODE_AND_MATH.sub(" ", text)


def extract_glossary_candidates(
    texts: Iterable[str], *, limit: int = 200
) -> list[dict[str, Any]]:
    """Extract recurring proper nouns, role names, and API identifiers.

    Code and math are excluded from prose extraction, while explicit inline-code
    and dotted/call-shaped identifiers are retained as protected terms.
    """
    corpus = "\n\n".join(text for text in texts if text)
    frequencies: Counter[str] = Counter()
    kinds: dict[str, str] = {}

    for match in _API_TOKEN.finditer(corpus):
        term = (match.group(1) or match.group(2) or "").strip("`$")
        if not term or any(char.isspace() for char in term) and "`" not in match.group(0):
            continue
        term = term.strip()
        if 2 <= len(term) <= 120:
            frequencies[term] += 1
            kinds.setdefault(term, "api_identifier")

    prose = _clean_text(corpus)
    for match in _PROPER_NOUN.finditer(prose):
        term = " ".join(match.group(0).split())
        if term.casefold() in _ENGLISH_STOPWORDS or term.istitle() is False:
            continue
        if 3 <= len(term) <= 120:
            frequencies[term] += 1
            kinds.setdefault(term, "proper_noun")

    for match in _CAMEL_NAME.finditer(prose):
        term = match.group(0)
        if 3 <= len(term) <= 120:
            frequencies[term] += 1
            kinds.setdefault(term, "proper_noun")

    ranked = sorted(
        frequencies.items(),
        key=lambda item: (
            -item[1],
            0 if kinds.get(item[0]) == "api_identifier" else 1,
            item[0].casefold(),
        ),
    )
    return [
        {
            "term": term,
            "translation": term,
            "kind": kinds.get(term, "proper_noun"),
            "frequency": count,
            "protected": kinds.get(term) == "api_identifier",
            "approved": False,
            "decision": "candidate",
        }
        for term, count in ranked[: max(1, min(limit, 500))]
        if count >= 2 or kinds.get(term) == "api_identifier"
    ]


def merge_glossary(
    existing: Iterable[Mapping[str, Any]], candidates: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Merge candidates while preserving reviewed mappings and custom entries."""
    merged: dict[str, dict[str, Any]] = {}
    for entry in existing:
        term = str(entry.get("term", "")).strip()
        if not term:
            continue
        current = dict(entry)
        current.update(
            term=term,
            translation=str(entry.get("translation") or term).strip() or term,
            kind=str(entry.get("kind") or "custom"),
            frequency=max(0, int(entry.get("frequency", 0))),
            protected=bool(entry.get("protected")),
            approved=bool(entry.get("approved")),
            decision=str(entry.get("decision") or ("approved" if entry.get("approved") else "candidate")),
        )
        if current["decision"] not in {"candidate", "approved", "rejected"}:
            current["decision"] = "candidate"
        current["approved"] = current["decision"] == "approved"
        merged[term.casefold()] = current

    for candidate in candidates:
        term = str(candidate.get("term", "")).strip()
        if not term:
            continue
        key = term.casefold()
        current = merged.setdefault(
            key,
            {
                "term": term,
                "translation": term,
                "kind": str(candidate.get("kind") or "proper_noun"),
                "frequency": 0,
                "protected": False,
                "approved": False,
                "decision": "candidate",
            },
        )
        current["frequency"] = max(
            int(current.get("frequency", 0)), int(candidate.get("frequency", 0))
        )
        if not current.get("approved"):
            current["kind"] = str(candidate.get("kind") or current.get("kind"))
            current["protected"] = bool(candidate.get("protected")) or bool(
                current.get("protected")
            )
    return sorted(merged.values(), key=lambda item: item["term"].casefold())


async def review_glossary_candidates(
    candidates: Iterable[Mapping[str, Any]], target_language: str
) -> list[dict[str, Any]]:
    """Ask an LLM to supplement deterministic terminology candidates.

    The model is deliberately optional. Every failure path returns the bounded
    deterministic input so planning and translation remain usable offline.
    """
    rule_candidates = [
        {
            "term": str(entry.get("term", ""))[:300],
            "translation": str(entry.get("translation", ""))[:500],
            "kind": str(entry.get("kind", "proper_noun"))[:50],
            "protected": bool(entry.get("protected")),
        }
        for entry in candidates
        if str(entry.get("term", "")).strip()
    ][:200]
    if not rule_candidates:
        return []

    async def call_model() -> list[dict[str, Any]]:
        from deeptutor.services.llm import clean_thinking_tags, complete

        raw = await complete(
            prompt=(
                "Review translation terminology. Return JSON only. Schema: "
                '{"entries":[{"term":str,"translation":str,"kind":str,'
                '"protected":bool,"aliases":[str]}]}. Include the supplied entries '
                "after correcting translations, and add recurring Chinese role/domain "
                f"names visible in the excerpts. Target language: {target_language}. "
                "Never translate API identifiers or code identifiers.\n\n"
                + json.dumps(rule_candidates, ensure_ascii=False, separators=(",", ":"))
            ),
            system_prompt="You are a precise bilingual terminology editor.",
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(clean_thinking_tags(raw).strip())
        entries = parsed.get("entries") if isinstance(parsed, dict) else None
        if not isinstance(entries, list):
            raise ValueError("Invalid glossary response")
        result: list[dict[str, Any]] = []
        for item in entries[:500]:
            if not isinstance(item, dict):
                continue
            terms = [str(item.get("term", "")).strip()]
            terms.extend(
                str(alias).strip()
                for alias in (item.get("aliases") or [])
                if str(alias).strip()
            )
            for term in terms:
                if not term or len(term) > 300:
                    continue
                translation = str(item.get("translation") or term).strip()[:500]
                result.append(
                    {
                        "term": term,
                        "translation": translation or term,
                        "kind": str(item.get("kind") or "proper_noun")[:50],
                        "frequency": 1,
                        "protected": bool(item.get("protected")),
                        "approved": False,
                        "decision": "candidate",
                    }
                )
        return result[:500]

    try:
        reviewed = await asyncio.wait_for(call_model(), timeout=25.0)
    except Exception:
        return [
            {
                **entry,
                "frequency": 1,
                "approved": False,
                "decision": "candidate",
            }
            for entry in rule_candidates
        ]
    return merge_glossary(reviewed, rule_candidates)


def terms_for_text(
    glossary: Iterable[Mapping[str, Any]], text: str, *, limit: int = 120
) -> list[dict[str, Any]]:
    haystack = text.casefold()
    selected = [
        dict(entry)
        for entry in glossary
        if str(entry.get("term", "")).strip().casefold() in haystack
        and str(entry.get("decision") or ("approved" if entry.get("approved") else "candidate"))
        != "rejected"
    ]
    return sorted(
        selected,
        key=lambda item: (
            not bool(item.get("approved")),
            not bool(item.get("protected")),
            -int(item.get("frequency", 0)),
            str(item.get("term", "")).casefold(),
        ),
    )[: max(0, limit)]


def build_translation_guardrail(
    target_language: str, glossary: Sequence[Mapping[str, Any]] | None
) -> str:
    parts = [
        f"Target language: {target_language}",
        "Terminology and formatting rules:",
        "- Use the translation shown for every listed term, exactly and consistently.",
        "- Terms marked protected must remain byte-for-byte unchanged.",
        "- Preserve fenced code blocks, inline code, URLs, HTML tags, and Markdown syntax.",
        "- Preserve inline math ($...$), display math ($$...$$), and LaTeX commands unchanged.",
        "- Translate only natural-language prose and never add commentary.",
    ]
    terms = [
        entry
        for entry in (glossary or [])
        if str(entry.get("term", "")).strip()
        and str(entry.get("translation", "")).strip()
        and str(entry.get("decision") or ("approved" if entry.get("approved") else "candidate"))
        != "rejected"
    ]
    if terms:
        payload = [
            {
                "source": entry["term"],
                "translation": entry["translation"],
                "protected": bool(entry.get("protected")),
            }
            for entry in terms
        ]
        parts.extend(
            [
                "",
                "Glossary JSON (source, translation, protected; obey each entry):",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ]
        )
    return "\n".join(parts)



def is_hymt_model(model: str | None) -> bool:
    """Check if the model name refers to Tencent Hunyuan MT / Hy-MT series."""
    if not model:
        return False
    norm = str(model).lower()
    return any(k in norm for k in ("hy-mt", "hy_mt", "hunyuan-mt", "hunyuan_mt", "hymt"))


def build_hymt_translation_prompt(
    text: str,
    target_language: str,
    glossary: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Build the official Hunyuan Translation (Hy-MT2) instruction prompt.

    Supports Terminology instruction and zero-commentary output formatting.
    """
    target = target_language.strip()
    is_zh = target in {"Chinese", "中文", "简体中文", "繁體中文", "繁体中文"}

    terms = [
        entry
        for entry in (glossary or [])
        if str(entry.get("term", "")).strip()
        and str(entry.get("translation", "")).strip()
        and str(entry.get("decision") or ("approved" if entry.get("approved") else "candidate"))
        != "rejected"
    ]

    if is_zh:
        target_name = "中文" if target == "Chinese" else target
        if terms:
            term_lines = "\n".join(
                f"{entry['term']} 翻译成 {entry['translation']}" for entry in terms
            )
            return (
                f"参考下面的翻译：\n"
                f"{term_lines}\n"
                f"将以下文本翻译为 {target_name}，注意只需要输出翻译后的结果，不要额外解释：\n\n"
                f"{text}"
            )
        return f"将以下文本翻译为 {target_name}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
    else:
        if terms:
            term_lines = "\n".join(
                f"{entry['term']} translates to {entry['translation']}" for entry in terms
            )
            return (
                f"Reference the following translations:\n"
                f"{term_lines}\n\n"
                f"Translate the following text into {target}. Note that you must ONLY output the translated result without any additional explanation:\n\n"
                f"{text}"
            )
        return (
            f"Translate the following text into {target}. Note that you should only output the translated result without any additional explanation:\n\n"
            f"{text}"
        )
