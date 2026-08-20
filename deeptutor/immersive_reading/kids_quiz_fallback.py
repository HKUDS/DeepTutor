"""Deterministic, source-grounded fallback quizzes for child reading."""

from __future__ import annotations

from collections import Counter
import hashlib
import random
import re
from typing import Any

_EN_STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "their",
    "there",
    "these",
    "thing",
    "this",
    "through",
    "under",
    "until",
    "want",
    "were",
    "what",
    "where",
    "which",
    "while",
    "would",
    "your",
    "chapter",
    "story",
}
_CAUSAL_RE = re.compile(
    r"because|therefore|so that|as a result|因为|所以|于是|因此|结果",
    re.IGNORECASE,
)


def primary_language(text: str) -> str:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "zh" if cjk and cjk >= latin // 3 else "en"


def _sentences(text: str, language: str) -> list[str]:
    if language == "zh":
        raw = re.findall(r"[^。！？!?.\n]+[。！？!?.]?", text)
    else:
        raw = re.split(r"(?<=[.!?])\s+|\n+", text)
    minimum = 12 if language == "zh" else 30
    result = []
    for sentence in raw:
        value = re.sub(r"\s+", " ", sentence).strip(" \t\r\n-*#")
        if minimum <= len(value) <= 420:
            result.append(value)
    return list(dict.fromkeys(result))


def _terms(text: str, language: str) -> list[str]:
    if language == "zh":
        candidates = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
    else:
        candidates = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text)
    counts = Counter(item.casefold() for item in candidates)
    ranked = [item for item, _ in counts.most_common() if item.casefold() not in _EN_STOPWORDS]
    return list(dict.fromkeys(ranked))


def _shorten(value: str, language: str) -> str:
    limit = 48 if language == "zh" else 105
    clean = re.sub(r"\s+", " ", value).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _shuffle_choices(choices: list[str], correct: str, rng: random.Random) -> tuple[list[str], int]:
    shuffled = choices[:]
    rng.shuffle(shuffled)
    return shuffled, shuffled.index(correct)


def _cloze(
    sentence: str,
    terms: list[str],
    language: str,
    kind: str,
    rng: random.Random,
) -> dict[str, Any] | None:
    available = [term for term in terms if term in sentence]
    if not available:
        return None
    correct = available[0]
    distractors = [term for term in terms if term.casefold() != correct.casefold()]
    rng.shuffle(distractors)
    if len(distractors) < 3:
        return None
    question = (
        "哪个词来自本章原句的空格处？"
        if language == "zh"
        else "Which word completes this sentence from the chapter?"
    )
    choices, answer_index = _shuffle_choices([correct, *distractors[:3]], correct, rng)
    return {
        "kind": kind,
        "question": f"{sentence.replace(correct, '____', 1)}\n{question}",
        "choices": choices,
        "answer_index": answer_index,
        "explanation": sentence,
    }


def _sequence(sentences: list[str], language: str, rng: random.Random) -> dict[str, Any] | None:
    if len(sentences) < 4:
        return None
    start = rng.randrange(0, min(3, len(sentences) - 1))
    candidates = sentences[start + 1 :]
    rng.shuffle(candidates)
    correct = _shorten(sentences[start], language)
    choices = [correct, *[_shorten(item, language) for item in candidates[:3]]]
    if len(set(choices)) != 4:
        return None
    choices, answer_index = _shuffle_choices(choices, correct, rng)
    return {
        "kind": "sequence",
        "question": "Which event happened first?" if language == "en" else "哪件事先发生？",
        "choices": choices,
        "answer_index": answer_index,
        "explanation": sentences[start],
    }


def _inference(sentences: list[str], language: str, rng: random.Random) -> dict[str, Any] | None:
    if len(sentences) < 5:
        return None
    index = rng.randrange(1, len(sentences) - 2)
    correct = _shorten(sentences[index + 1], language)
    candidates = [sentence for i, sentence in enumerate(sentences) if i not in {index, index + 1}]
    rng.shuffle(candidates)
    choices = [correct, *[_shorten(item, language) for item in candidates[:3]]]
    if len(set(choices)) != 4:
        return None
    choices, answer_index = _shuffle_choices(choices, correct, rng)
    return {
        "kind": "inference",
        "question": (
            f"Which sentence comes next?\n{sentences[index]}\n____"
            if language == "en"
            else f"接下来最符合原文的是哪一句？\n{sentences[index]}\n____"
        ),
        "choices": choices,
        "answer_index": answer_index,
        "explanation": sentences[index + 1],
    }


def _source_fact(
    sentences: list[str],
    terms: list[str],
    language: str,
    kind: str,
    rng: random.Random,
) -> dict[str, Any] | None:
    ordered = [sentence for sentence in sentences if any(term in sentence for term in terms)]
    pool = (
        [sentence for sentence in ordered if _CAUSAL_RE.search(sentence)]
        if kind == "comprehension"
        else ordered
    )
    if not pool:
        return None
    sentence = pool[min(len(pool) - 1, rng.randrange(0, len(pool)))]
    return _cloze(sentence, terms, language, kind, rng)


def _vocabulary(
    sentences: list[str],
    terms: list[str],
    language: str,
    rng: random.Random,
) -> dict[str, Any] | None:
    if language == "en":
        from deeptutor.immersive_reading.sight_words import generate_translation_quiz

        generated = generate_translation_quiz(
            "\n".join(sentences),
            num_questions=1,
            seed=int.from_bytes(hashlib.sha256("\n".join(sentences).encode()).digest()[:4], "big"),
        )
        if generated:
            item = generated[0]
            return {**item, "kind": "vocabulary"}
    return _source_fact(sentences, terms, language, "vocabulary", rng)


def generate_source_quiz(text: str, *, age_band: str = "6-8") -> list[dict[str, Any]]:
    """Build exactly three questions from chapter text, or return an empty list."""
    language = primary_language(text)
    source = _sentences(text, language)
    if len(source) < 4:
        return []
    if len(source) > 18:
        third = max(6, len(source) // 3)
        source = (
            source[:third] + source[len(source) // 2 : len(source) // 2 + third] + source[-third:]
        )
        source = list(dict.fromkeys(source))
    terms = _terms(text, language)
    if len(terms) < 4:
        return []

    seed = int.from_bytes(hashlib.sha256(f"{age_band}:{text}".encode()).digest()[:8], "big")
    rng = random.Random(seed)
    required_kinds = (
        ("comprehension", "inference", "vocabulary")
        if age_band == "9-12"
        else ("recall", "sequence", "vocabulary")
    )
    builders = {
        "comprehension": lambda: _source_fact(source, terms, language, "comprehension", rng),
        "inference": lambda: _inference(source, language, rng),
        "recall": lambda: _source_fact(source, terms, language, "recall", rng),
        "sequence": lambda: _sequence(source, language, rng),
        "vocabulary": lambda: _vocabulary(source, terms, language, rng),
    }
    questions = []
    for kind in required_kinds:
        question = builders[kind]()
        if not question or len(question.get("choices", [])) != 4:
            return []
        questions.append({"id": f"q{len(questions) + 1}", **question})
    return questions
