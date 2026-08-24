"""Optional schema-only actions for DeepTutor Immersive Reading."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingContext,
    ReadingExtensionManifest,
    ReadingExtensionResult,
)
from deeptutor.services.llm.exceptions import LLMConfigError
from deeptutor.utils.json_parser import parse_json_response

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _sentences(text: str, limit: int = 3) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    rows = [row.strip() for row in re.split(r"(?<=[.!?。！？])\s*", clean) if row.strip()]
    return rows[:limit] or ([clean[:240]] if clean else [])


def _language(context: ReadingContext) -> str:
    return "zh" if context.locale.lower().startswith("zh") else "en"


def _truncate(value: Any, limit: int) -> str:
    row = re.sub(r"\s+", " ", str(value or "")).strip()
    return row[:limit]


def _concept_row(term: str, explanation: str, analogy: str = "") -> dict[str, str]:
    return {
        "term": _truncate(term, 120),
        "explanation": _truncate(explanation, 900),
        "analogy": _truncate(analogy, 400),
    }


def _learn_fallback(source: str, language: str) -> dict[str, Any]:
    paragraphs = [row.strip() for row in re.split(r"\n+", source) if row.strip()]
    sentences = [
        row.strip()
        for paragraph in paragraphs
        for row in re.split(r"(?<=[.!?。！？])\s+", paragraph)
        if row.strip()
    ]
    substantive = [row for row in sentences if len(row) >= 12]
    candidates = substantive or sentences or paragraphs or ([source[:240]] if source else [])
    overview = " ".join(candidates[:2]) if language == "en" else "".join(candidates[:2])

    concepts: list[dict[str, str]] = []
    if language == "zh":
        definition_terms: list[str] = []
        for sentence in candidates:
            for match in re.finditer(r"“([^”]{2,12})”|叫(?:做)?([^”，。！？]{2,12})", sentence):
                for raw in match.groups():
                    term = _truncate(raw, 12)
                    if term and term not in definition_terms:
                        definition_terms.append(term)
        repeated: dict[str, int] = {}
        compact = re.sub(r"\s+", "", source)
        for size in (4, 3, 2):
            for index in range(len(compact) - size + 1):
                token = compact[index : index + size]
                if all(_CJK_RE.match(char) for char in token):
                    repeated[token] = repeated.get(token, 0) + 1
        terms = definition_terms + [
            term
            for term, count in sorted(repeated.items(), key=lambda row: (-row[1], -len(row[0])))
            if count >= 2
        ]
        for term in terms:
            sentence = next((row for row in candidates if term in row), overview)
            if all(term not in row["term"] for row in concepts):
                concepts.append(_concept_row(term, sentence))
            if len(concepts) == 3:
                break
    else:
        stop_words = {
            "about",
            "after",
            "again",
            "around",
            "before",
            "because",
            "cannot",
            "could",
            "every",
            "from",
            "have",
            "here",
            "into",
            "just",
            "like",
            "little",
            "made",
            "make",
            "many",
            "more",
            "most",
            "much",
            "must",
            "only",
            "other",
            "over",
            "said",
            "some",
            "such",
            "than",
            "the",
            "their",
            "there",
            "these",
            "they",
            "this",
            "very",
            "want",
            "were",
            "what",
            "when",
            "where",
            "which",
            "while",
            "will",
            "with",
            "would",
            "your",
        }
        counts: dict[str, int] = {}
        for word in re.findall(r"\b[A-Za-z][A-Za-z'-]{3,}\b", source):
            key = word.lower()
            counts[key] = counts.get(key, 0) + 1
        terms = [
            word
            for word, count in sorted(counts.items(), key=lambda row: -row[1])
            if count >= 1 and word not in stop_words
        ]
        proper_nouns = []
        for word in re.findall(r"\b[A-Z][a-z]{2,}\b", source):
            if word not in proper_nouns and word.lower() not in stop_words:
                proper_nouns.append(word)
        for term in proper_nouns + terms:
            sentence = next(
                (row for row in candidates if re.search(rf"\b{re.escape(term)}\b", row, re.I)), ""
            )
            if sentence and all(term.lower() not in row["term"].lower() for row in concepts):
                concepts.append(_concept_row(term, sentence))
            if len(concepts) == 3:
                break

    if not concepts:
        labels = ("主要意思", "重要细节") if language == "zh" else ("Main idea", "Key detail")
        concepts = [
            _concept_row(labels[0], overview),
            _concept_row(labels[1], candidates[0] if candidates else overview),
        ]

    first_term = concepts[0]["term"]
    if language == "zh":
        reflection = f"想一想：这一页中【{first_term}】为什么重要？"
        hint = "回到原文，找一找它出现的句子和前后发生的事情。"
    else:
        reflection = f"Why is {first_term} important on this page?"
        hint = "Return to the passage and find the sentence where it appears."
    return {
        "overview": _truncate(overview, 1200),
        "concepts": concepts,
        "reflection": reflection,
        "reflection_hint": hint,
        "source": "fallback",
    }


class _BaseExtension:
    manifest: ReadingExtensionManifest

    @staticmethod
    def _source(context: ReadingContext) -> str:
        return context.selection or context.visible_text or context.unit_text

    def _check(self, action: str) -> None:
        if action not in {row.id for row in self.manifest.actions}:
            raise ValueError(f"Unknown action {action!r}")

    def submit(
        self, interaction: dict[str, Any], submission: dict[str, Any]
    ) -> ReadingExtensionResult:
        raise ValueError("This extension has no interactive submission.")


class ReadAloudExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="read_aloud",
        version="0.1.0",
        name="Read aloud",
        actions=[ReadingAction(id="read", label="Read aloud", requires=["visible_text"])],
        result_types=["browser_speech"],
    )

    def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        return ReadingExtensionResult(
            type="browser_speech",
            title="Read aloud",
            payload={"text": self._source(context), "locale": context.locale},
        )


class GuidedLearnExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="guided_learn",
        version="0.2.0",
        name="Learn",
        actions=[ReadingAction(id="explain", label="Learn", requires=["visible_text"])],
        result_types=["card"],
    )

    async def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        source = context.visible_text or context.unit_text
        language = _language(context)
        model = os.environ.get("DEEPTUTOR_READING_LEARN_MODEL", "").strip()
        provider = os.environ.get("DEEPTUTOR_READING_LEARN_PROVIDER", "").strip()
        payload = _learn_fallback(source, language)
        if model:
            from deeptutor.services.llm import complete

            age_instruction = {
                "3-5": "For ages 3-5, use very short, vivid sentences.",
                "6-8": "For ages 6-8, use simple, engaging sentences.",
                "9-12": "For ages 9-12, use clear, thought-provoking sentences.",
            }.get(context.age_band, "For ages 6-8, use simple, engaging sentences.")
            language_label = "Simplified Chinese" if language == "zh" else "English"
            try:
                raw = await complete(
                    f"Page text:\n<visible_page>\n{source[:12_000]}\n</visible_page>",
                    system_prompt=(
                        "You are an encouraging teacher creating a concept guide for a young reader. "
                        "Focus only on the supplied visible page. Return JSON only matching: "
                        '{"overview":"...","concepts":[{"term":"...","explanation":"...",'
                        '"analogy":"..."}],"reflection":{"prompt":"...","hint":"...","answer":"..."}}. '
                        "Use two or three distinct concepts. "
                        f"{age_instruction} Write every value in {language_label}."
                    ),
                    model=model,
                    binding=provider or None,
                    temperature=0.2,
                    max_tokens=1200,
                )
                parsed = parse_json_response(raw, fallback={})
                concepts = [
                    _concept_row(item.get("term"), item.get("explanation"), item.get("analogy"))
                    for item in parsed.get("concepts", [])
                    if isinstance(item, dict)
                    and str(item.get("term", "")).strip()
                    and str(item.get("explanation", "")).strip()
                ][:3]
                reflection = parsed.get("reflection", {})
                overview = _truncate(parsed.get("overview"), 1200)
                if (
                    overview
                    and concepts
                    and isinstance(reflection, dict)
                    and _truncate(reflection.get("prompt"), 800)
                    and _truncate(reflection.get("answer"), 1200)
                ):
                    payload = {
                        "overview": overview,
                        "concepts": concepts,
                        "reflection": _truncate(reflection.get("prompt"), 800),
                        "reflection_hint": _truncate(reflection.get("hint"), 800) or overview,
                        "reference_answer": _truncate(reflection.get("answer"), 1200),
                        "source": "generated",
                    }
            except Exception:
                # A malformed or unavailable model response must never block reading.
                payload = _learn_fallback(source, language)

        details = payload["concepts"]
        return ReadingExtensionResult(
            type="card",
            title="Guided learning",
            payload={
                **payload,
                "concepts": [f"{row['term']}: {row['explanation']}" for row in details],
                "concept_details": details,
            },
        )


class VocabularyExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="vocabulary",
        version="0.2.0",
        name="Vocabulary",
        actions=[ReadingAction(id="hint", label="Vocabulary", requires=["selection"])],
        result_types=["card", "quiz", "feedback"],
    )

    def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        from deeptutor.immersive_reading.kids_word_hints import (
            build_kids_word_hint,
            normalize_hint_word,
        )

        word = normalize_hint_word(context.selection)[:80]
        dictionary = os.environ.get("DEEPTUTOR_READING_DICTIONARY", "").strip()
        if dictionary and word:
            definition, message = _dictionary_lookup(Path(dictionary), word)
            if definition:
                return ReadingExtensionResult(
                    type="card",
                    title=word,
                    message=message,
                    payload={
                        "word": word,
                        "definition": definition,
                        "context": _context_sentence(context),
                    },
                )

        hint = build_kids_word_hint(context.selection, context.age_band or "6-8")
        if not word or hint is None:
            return ReadingExtensionResult(
                type="card",
                title=word or "Vocabulary",
                message=(
                    "Select one supported English word to get a thinking clue."
                    if word
                    else "Select one word in the page to get a contextual clue."
                ),
                payload={"word": word, "context": _context_sentence(context)},
            )

        choices = [row for row in hint.choices if row]
        correct_index = choices.index(hint.correct_choice)
        interaction_id = sha256(
            f"vocabulary|{context.material_id}|{context.locator}|{hint.word}".encode()
        ).hexdigest()[:24]
        metadata = {
            "word": hint.word,
            "phonetic": hint.phonetic,
            "chinese": hint.chinese,
            "correct_choice": hint.correct_choice,
            "english_hint": hint.english_hint,
            "context": _context_sentence(context),
        }
        return ReadingExtensionResult(
            type="quiz",
            interaction_id=interaction_id,
            title=f"Word clue: {hint.word}",
            message=hint.english_hint,
            payload={
                "questions": [
                    {
                        "id": "meaning",
                        "prompt": "Which meaning fits this word?",
                        "choices": choices,
                    }
                ],
                "_answers": {"meaning": correct_index, "_metadata": metadata},
            },
        )

    def submit(
        self, interaction: dict[str, Any], submission: dict[str, Any]
    ) -> ReadingExtensionResult:
        private = interaction.get("private", {}).get("answers", {})
        metadata = private.get("_metadata", {}) if isinstance(private, dict) else {}
        expected = private.get("meaning") if isinstance(private, dict) else None
        submitted = submission.get("answers", {})
        selected = submitted.get("meaning") if isinstance(submitted, dict) else None
        correct = isinstance(expected, int) and selected == expected
        word = str(metadata.get("word") or "")
        return ReadingExtensionResult(
            type="feedback",
            interaction_id=str(interaction.get("interaction_id") or ""),
            title=f"Word result: {word}",
            message=(
                f"Correct! {word}: {metadata.get('chinese', '')}".strip()
                if correct
                else f"Not quite. {word}: {metadata.get('chinese', '')}".strip()
            ),
            payload={"correct": correct, "score": int(correct), "total": 1, **metadata},
        )


def _context_sentence(context: ReadingContext) -> str:
    source = context.unit_text or context.visible_text
    selection = context.selection.strip()
    word = selection.split()[0].strip(".,!?;:\"'()[]") if selection else ""
    rows = _sentences(source, limit=50)
    for row in rows:
        if word and word.casefold() in row.casefold():
            return row
    return rows[0] if rows else ""


class TranslationExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="translation",
        version="0.1.0",
        name="Translate",
        actions=[ReadingAction(id="translate", label="Translate", requires=["visible_text"])],
        result_types=["card"],
    )

    async def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        model = os.environ.get("DEEPTUTOR_READING_TRANSLATION_MODEL", "").strip()
        provider = os.environ.get("DEEPTUTOR_READING_TRANSLATION_PROVIDER", "").strip()
        if not model:
            return ReadingExtensionResult(
                type="card",
                title="Translation",
                message=(
                    "Configure DEEPTUTOR_READING_TRANSLATION_MODEL with an installed model "
                    "ID to enable translation."
                ),
                payload={"source_text": self._source(context)[:2000]},
            )

        from deeptutor.services.llm import complete

        source = self._source(context)[:12_000]
        try:
            translated = await complete(
                source,
                system_prompt=(
                    "Translate the supplied reading passage into Chinese. Preserve Markdown "
                    "structure and technical terms. Return only the translation."
                ),
                model=model,
                binding=provider or None,
                max_tokens=4096,
            )
        except LLMConfigError as exc:
            detail = str(exc)[:3900]
            return ReadingExtensionResult(
                type="card",
                title="Translation",
                message=f"Translation is not configured correctly: {detail}",
                payload={"source_text": source},
            )
        return ReadingExtensionResult(
            type="card",
            title="Translation",
            payload={"source_text": source, "translation": translated},
        )


def _dictionary_lookup(path: Path, word: str) -> tuple[str, str]:
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return "", "The configured dictionary exceeds the 2 MB safety limit."
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "", "The configured dictionary file does not exist."
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "", "The configured dictionary must be a readable JSON object."
    if not isinstance(payload, dict):
        return "", "The configured dictionary must contain a JSON object."
    entries = {str(key).casefold(): value for key, value in payload.items()}
    value = entries.get(word.casefold())
    if value is None:
        return "", f"No local definition was found for {word!r}."
    if isinstance(value, list):
        definition = "; ".join(str(item) for item in value)
    else:
        definition = str(value)
    return definition[:4000], "Local dictionary"


def _quiz_fallback(source: str, age_band: str, language: str, *, seed: int) -> list[dict[str, Any]]:
    from deeptutor.immersive_reading.sight_words import generate_story_comprehension_quiz

    rows = generate_story_comprehension_quiz(
        source,
        age_band=age_band,
        num_questions=3,
        language=language,
        seed=seed,
    )
    questions: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:3], start=1):
        choices = [str(choice) for choice in row.get("choices", []) if str(choice).strip()]
        answer_index = row.get("answer_index")
        if (
            len(choices) < 2
            or not isinstance(answer_index, int)
            or not 0 <= answer_index < len(choices)
        ):
            continue
        questions.append(
            {
                "id": f"q{index}",
                "prompt": _truncate(row.get("question"), 800),
                "choices": choices,
                "answer_index": answer_index,
                "explanation": _truncate(row.get("explanation"), 800),
            }
        )
    while len(questions) < 3:
        statement = (_sentences(source, 3) + [source[:240]])[min(len(questions), 2)]
        questions.append(
            {
                "id": f"q{len(questions) + 1}",
                "prompt": "Which statement appears in the current passage?",
                "choices": [statement, "Not stated in this passage"],
                "answer_index": 0,
                "explanation": "This sentence comes from the visible passage.",
            }
        )
    return questions


async def _llm_quiz(
    source: str, age_band: str, language: str, model: str, provider: str
) -> list[dict[str, Any]]:
    from deeptutor.services.llm import complete

    age_instruction = {
        "3-5": "Use very simple picture-book language and 1-3 word choices.",
        "6-8": "Use very simple language and 2-6 word choices.",
        "9-12": "Use clear reading-comprehension language and concise choices.",
    }.get(age_band, "Use very simple language and 2-6 word choices.")
    language_label = "Simplified Chinese" if language == "zh" else "English"
    raw = await complete(
        f"<story_text>\n{source[:6000]}\n</story_text>",
        system_prompt=(
            "Create a child-friendly reading comprehension quiz from the supplied text. "
            "Generate exactly three multiple-choice questions about the actual meaning: "
            "the subject, a detail or cause/effect, and a conclusion or phrase in context. "
            "Each question has two to four plausible choices and one correct answer. "
            f"{age_instruction} Return JSON only matching "
            '{"questions":[{"id":"q1","question":"...","choices":["..."],'
            '"answer_index":0,"explanation":"..."}]}. '
            f"Write every value in {language_label}."
        ),
        model=model,
        binding=provider or None,
        temperature=0.3,
        max_tokens=2500,
    )
    parsed = parse_json_response(raw, fallback={})
    questions: list[dict[str, Any]] = []
    for index, row in enumerate(parsed.get("questions", []), start=1):
        if not isinstance(row, dict):
            continue
        choices = [str(choice) for choice in row.get("choices", []) if str(choice).strip()]
        answer_index = row.get("answer_index")
        prompt = _truncate(row.get("question"), 800)
        if (
            not prompt
            or len(choices) < 2
            or not isinstance(answer_index, int)
            or not 0 <= answer_index < len(choices)
        ):
            continue
        questions.append(
            {
                "id": f"q{index}",
                "prompt": prompt,
                "choices": choices[:4],
                "answer_index": min(answer_index, len(choices[:4]) - 1),
                "explanation": _truncate(row.get("explanation"), 800),
            }
        )
    return questions


def _merge_quiz_questions(
    generated: list[dict[str, Any]], fallback: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    questions = generated[:3]
    for row in fallback:
        if len(questions) >= 3:
            break
        if all(row["prompt"].casefold() != item["prompt"].casefold() for item in questions):
            questions.append({**row, "id": f"q{len(questions) + 1}"})
    return questions[:3]


class QuizExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="quiz",
        version="0.2.0",
        name="Test",
        actions=[ReadingAction(id="start", label="Test", requires=["visible_text"])],
        result_types=["quiz", "feedback"],
    )

    async def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        source = context.visible_text or context.unit_text
        language = _language(context)
        questions = _quiz_fallback(
            source,
            context.age_band or "6-8",
            language,
            seed=int.from_bytes(sha256(source.encode()).digest()[:4], "big"),
        )
        model = os.environ.get("DEEPTUTOR_READING_QUIZ_MODEL", "").strip()
        provider = os.environ.get("DEEPTUTOR_READING_QUIZ_PROVIDER", "").strip()
        if model:
            try:
                questions = _merge_quiz_questions(
                    await _llm_quiz(source, context.age_band or "6-8", language, model, provider),
                    questions,
                )
            except Exception:
                # Reading practice remains available when model output is unusable.
                pass

        interaction_id = sha256(
            f"quiz|{context.material_id}|{context.locator}|{source}".encode()
        ).hexdigest()[:24]
        answers = {row["id"]: row["answer_index"] for row in questions}
        metadata = {row["id"]: row["explanation"] for row in questions}
        public_questions = [
            {"id": row["id"], "prompt": row["prompt"], "choices": row["choices"]}
            for row in questions
        ]
        return ReadingExtensionResult(
            type="quiz",
            interaction_id=interaction_id,
            title="Three-question check",
            payload={
                "questions": public_questions,
                "_answers": {**answers, "_metadata": metadata},
            },
        )

    def submit(
        self, interaction: dict[str, Any], submission: dict[str, Any]
    ) -> ReadingExtensionResult:
        expected = interaction.get("private", {}).get("answers", {})
        metadata = expected.get("_metadata", {}) if isinstance(expected, dict) else {}
        answers = submission.get("answers")
        answers = answers if isinstance(answers, dict) else {}
        checked = {
            key: value
            for key, value in expected.items()
            if key != "_metadata" and isinstance(key, str) and isinstance(value, int)
        }
        score = sum(1 for key, value in checked.items() if answers.get(key) == value)
        return ReadingExtensionResult(
            type="feedback",
            interaction_id=str(interaction.get("interaction_id") or ""),
            title="Quiz result",
            message=f"{score}/{len(checked)}",
            payload={
                "score": score,
                "total": len(checked),
                "completed": True,
                "explanations": metadata if isinstance(metadata, dict) else {},
            },
        )


__all__ = [
    "GuidedLearnExtension",
    "QuizExtension",
    "ReadAloudExtension",
    "TranslationExtension",
    "VocabularyExtension",
]
